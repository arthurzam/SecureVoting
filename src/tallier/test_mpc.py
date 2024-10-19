import asyncio
import string
from itertools import count, product
from random import randint
from struct import Struct

import pytest
import pytest_asyncio

from mpc import TallierConn, MpcWinner, MpcValidation
from mytypes import Election, ElectionType
from utils import clean_gen_shamir, transpose

class QueueTallier(TallierConn):
    def __init__(self, size: int, reader: asyncio.Queue[bytes], writer: asyncio.Queue[bytes]):
        self.reader, self.writer = reader, writer
        self.queue: dict[int, list[tuple[int, ...]] | asyncio.Future] = {}
        self.size = size
        self.struct = Struct('>I' + self.size * 'I')

    async def close(self):
        assert self.writer.empty(), "Queue should be empty"

    async def read(self, msgid: int) -> tuple[int, ...]:
        if (a := self.queue.get(msgid)) is not None:
            assert isinstance(a, list)
            if len(a) > 1:
                return a.pop(0)
            else:
                del self.queue[msgid]
                return a[0]
        else:
            fut = asyncio.get_event_loop().create_future()
            self.queue[msgid] = fut
            return await fut

    async def write(self, msgid: int, values: tuple[int, ...]):
        pad = (0, ) * (self.size - len(values))
        await self.writer.put(self.struct.pack(msgid, *values, *pad))

    async def receive_loop(self):
        try:
            while True:
                data = await self.reader.get()
                assert len(data) == self.struct.size, "Invalid message size"
                msgid, *share = self.struct.unpack(data)
                if isinstance(a := self.queue.setdefault(msgid, []), list):
                    a.append(tuple(share))
                else:
                    del self.queue[msgid]
                    a.set_result(tuple(share))
        except asyncio.CancelledError:
            await self.close()


p = 2 ** 31 - 1
mock_election = Election(None, "Arthur", "a@a.com", ElectionType.approval, ("Alice", "Bob", "Charlie"), 1, p, 5)


def generate_clique_talliers(clique_size: int, tallier_size: int):
    M = tuple((tuple(asyncio.Queue() if i != j else None for i in range(clique_size)) for j in range(clique_size)))
    return tuple(
        tuple(QueueTallier(tallier_size, M[i][j], M[j][i]) if i != j else None for i in range(clique_size))
        for j in range(clique_size)
    )


@pytest_asyncio.fixture(params=(pytest.param(x, id=f"clique_size={x}") for x in (3, 5, 7)))
async def clique(request):
    talliers = generate_clique_talliers(request.param, tallier_size=1)
    clique_mpc = tuple(MpcWinner(mock_election, t) for t in talliers)
    yield clique_mpc
    await asyncio.gather(*(t.close() for t in clique_mpc))


@pytest_asyncio.fixture
async def clique_3():
    talliers = generate_clique_talliers(3, tallier_size=1)
    clique_mpc = tuple(MpcWinner(mock_election, t) for t in talliers)
    yield clique_mpc
    await asyncio.gather(*(t.close() for t in clique_mpc))


@pytest.mark.asyncio
async def test_resolve(clique_3):
    shares_5 = (882092131, 1764184257, 498792736)
    shares_6 = (934163148, 1868326290, 655005785)

    async def code(t: MpcWinner, a: int, b: int) -> tuple[int, int]:
        return tuple(await asyncio.gather(t.resolve(0, a), t.resolve(1, b)))

    response = await asyncio.gather(*map(code, clique_3, shares_5, shares_6))
    assert response == [(5, 6)] * len(clique_3)

@pytest.mark.asyncio
async def test_multiply_bgw(clique):
    a = randint(0, p - 1)
    b = randint(0, p - 1)
    expected = (a * b) % p

    shares_a = clean_gen_shamir(a, len(clique), (len(clique) + 1) // 2, p)
    shares_b = clean_gen_shamir(b, len(clique), (len(clique) + 1) // 2, p)

    async def code(t: MpcWinner, x: int, y: int) -> int:
        return await t.resolve(0, await t.bgw_multiply(0, x, y))

    response = await asyncio.gather(*map(code, clique, shares_a, shares_b))
    assert response == [expected] * len(clique)

@pytest.mark.asyncio
async def test_multiply_rnd(clique):
    a = randint(0, p - 1)
    b = randint(0, p - 1)
    expected = (a * b) % p

    shares_a = clean_gen_shamir(a, len(clique), (len(clique) + 1) // 2, p)
    shares_b = clean_gen_shamir(b, len(clique), (len(clique) + 1) // 2, p)

    async def code(t: MpcWinner, x: int, y: int) -> int:
        return await t.resolve(0, await t.rnd_multiply(0, x, y))

    response = await asyncio.gather(*map(code, clique, shares_a, shares_b))
    assert response == [expected] * len(clique)


@pytest.mark.asyncio
async def test_random_number(clique):
    async def code(t: MpcWinner) -> tuple[int, int]:
        a, b = await asyncio.gather(t.random_number(0), t.random_number(1))
        a, b = await asyncio.gather(t.resolve(0, a), t.resolve(1, b))
        return a, b

    response = await asyncio.gather(*map(code, clique))
    assert response[0] == response[1] == response[2]

@pytest.mark.asyncio
@pytest.mark.parametrize("a", (0, 1, 2, 3, 4))
async def test_is_zero(clique, a):
    shares = clean_gen_shamir(a, len(clique), (len(clique) + 1) // 2, p)
    expected = int(a == 0)

    async def code(t: MpcWinner, x: int) -> int:
        return await t.resolve(0, await t.is_zero(0, x))

    response = await asyncio.gather(*map(code, clique, shares))
    assert response == [expected] * len(clique)

@pytest.mark.asyncio
@pytest.mark.parametrize("a", (-2, -1, 0, 1, 2, 3, p//2, -(p//2)))
async def test_is_positive(clique, a):
    shares = clean_gen_shamir(a % p, len(clique), (len(clique) + 1) // 2, p)
    expected = int(a > 0)

    async def code(t: MpcWinner, x: int) -> int:
        return await t.resolve(0, await t.is_positive(0, x))

    response = await asyncio.gather(*map(code, clique, shares))
    assert response == [expected] * len(clique)

def build_ballot(scores: tuple[int, ...], is_maximin = False):
    for i, c1 in enumerate(scores):
        for c2 in scores[i+1:]:
            if c1 > c2:
                yield 1
            elif is_maximin or c1 == c2:
                yield 0
            else:
                yield p-1

def build_ballot_shares(scores: tuple[int, ...], is_maximin = False) -> tuple[tuple[int, ...], ...]:
    return tuple(clean_gen_shamir(a, 3, 2, p) for a in build_ballot(scores, is_maximin))

@pytest.mark.asyncio
@pytest.mark.parametrize(("ballot", "expected"), (
    pytest.param((3, 2, 1), (4, 2, 0), id="ballot=3,2,1"),
    pytest.param((5, 3, 3), (4, 1, 1), id="ballot=5,3,3"),
    pytest.param((4, 2, 3, 1), (6, 2, 4, 0), id="ballot=4,2,3,1"),
))
async def test_copeland_score(clique_3, ballot, expected):
    alpha_s, alpha_t = 1, 2
    ballot_shares = build_ballot_shares(ballot)

    async def code(t: MpcWinner, *votes: int) -> tuple[int, ...]:
        scores = await t.copeland_scores(0, len(ballot), alpha_s, alpha_t, votes)
        return tuple(await asyncio.gather(*map(t.resolve, count(1), scores)))

    response = await asyncio.gather(*map(code, clique_3, *ballot_shares))
    assert response == [expected] * len(clique_3)


@pytest.mark.asyncio
@pytest.mark.parametrize(("ballot", "expected"), (
    pytest.param((3, 2, 1), 0, id="ballot=3,2,1"),
    pytest.param((5, 3, 3), 0, id="ballot=5,3,3"),
    pytest.param((2, 4, 3, 1), 1, id="ballot=2,4,3,1"),
))
async def test_copeland_winner(clique_3, ballot, expected):
    alpha_s, alpha_t = 1, 2
    ballot_shares = build_ballot_shares(ballot)

    async def code(t: MpcWinner, *votes: int) -> int:
        scores = await t.copeland_scores(0, len(ballot), alpha_s, alpha_t, votes)
        return await t.max(0, scores)

    response = await asyncio.gather(*map(code, clique_3, *ballot_shares))
    assert response == [expected] * len(clique_3)

@pytest.mark.asyncio
@pytest.mark.parametrize(("ballot", "expected"), (
    pytest.param((3, 2, 1), (1, 0, 0), id="ballot=3,2,1"),
    pytest.param((5, 3, 3), (1, 0, 0), id="ballot=5,3,3"),
    pytest.param((4, 2, 3, 1), (1, 0, 0, 0), id="ballot=4,2,3,1"),
))
async def test_maximin_score(clique_3, ballot, expected):
    ballot_shares = build_ballot_shares(ballot, is_maximin=True)

    async def code(t: MpcWinner, *votes: int) -> tuple[int, ...]:
        scores = await t.maximin_scores(0, len(ballot), votes)
        return tuple(await asyncio.gather(*map(t.resolve, count(1), scores)))

    response = await asyncio.gather(*map(code, clique_3, *ballot_shares))
    assert response == [expected] * len(clique_3)


@pytest.mark.asyncio
class TestMpcValidation:
    copeland_candidates = 4
    tallier_size = copeland_candidates * (copeland_candidates - 1) // 2

    @pytest.fixture(scope="class")
    def mock_election(self):
        candidates = tuple(string.ascii_uppercase)[:self.copeland_candidates]
        return Election(None, "Arthur", "a@a.com", ElectionType.copeland, candidates, 1, p, 5)

    @pytest_asyncio.fixture
    async def clique(self, mock_election):
        talliers = generate_clique_talliers(clique_size=3, tallier_size=self.tallier_size)
        clique_mpc = tuple(MpcValidation(mock_election, t) for t in talliers)
        yield clique_mpc
        await asyncio.gather(*(t.close() for t in clique_mpc))

    async def test_multiply(self, clique):
        a = [randint(0, p - 1) for _ in range(self.tallier_size)]
        b = [randint(0, p - 1) for _ in range(self.tallier_size)]
        expected = tuple((x * y) % p for x, y in zip(a, b))

        shares_a = transpose(clean_gen_shamir(x, len(clique), (len(clique) + 1) // 2, p) for x in a)
        shares_b = transpose(clean_gen_shamir(y, len(clique), (len(clique) + 1) // 2, p) for y in b)

        async def code(t: MpcValidation, x: tuple[int, ...], y: tuple[int, ...]) -> tuple[int, ...]:
            return await t.resolve(0, await t.multiply(0, x, y))

        response = await asyncio.gather(*map(code, clique, shares_a, shares_b))
        assert response == [expected] * len(clique)

    async def test_is_zero(self, clique):
        a = list(range(self.tallier_size))
        shares = transpose(clean_gen_shamir(x, len(clique), (len(clique) + 1) // 2, p) for x in a)
        expected = tuple(int(x == 0) for x in a)

        async def code(t: MpcValidation, x: tuple[int, ...]) -> tuple[int, ...]:
            return await t.resolve(0, await t.is_zero(0, x))

        response = await asyncio.gather(*map(code, clique, shares))
        assert response == [expected] * len(clique)

    valid_ballots = sorted({tuple(build_ballot(scores)) for scores in product(range(copeland_candidates), repeat=copeland_candidates)})
    invalid_ballots = sorted(set(product((p-1,0,1), repeat=tallier_size)) - set(valid_ballots))

    @pytest.mark.parametrize("ballot", (pytest.param(s, id=f"scores={s}") for s in valid_ballots))
    async def test_validate_copeland_valid(self, clique, ballot):
        shares = transpose(clean_gen_shamir(x, len(clique), (len(clique) + 1) // 2, p) for x in ballot)

        async def code(t: MpcValidation, x: tuple[int, ...]) -> bool:
            return await t.validate_copeland(0, x)

        response = await asyncio.gather(*map(code, clique, shares))
        assert response == [True] * len(clique)

    @pytest.mark.parametrize("ballot", (pytest.param(s, id=f"scores={s}") for s in invalid_ballots))
    async def test_validate_copeland_invalid(self, clique, ballot):
        shares = transpose(clean_gen_shamir(x, len(clique), (len(clique) + 1) // 2, p) for x in ballot)

        async def code(t: MpcValidation, x: tuple[int, ...]) -> bool:
            return await t.validate_copeland(0, x)

        response = await asyncio.gather(*map(code, clique, shares))
        assert response == [False] * len(clique)

    @pytest.mark.parametrize("ballot", (pytest.param(s, id=f"scores={s}") for s in product(range(copeland_candidates), repeat=copeland_candidates)))
    async def test_convert_copeland_to_maximin(self, clique, ballot):
        shares = transpose(build_ballot_shares(scores=ballot, is_maximin=False))
        expected = tuple(build_ballot(scores=ballot, is_maximin=True))

        async def code(t: MpcValidation, x: tuple[int, ...]) -> bool:
            return await t.resolve(0, await t.convert_copeland_to_maximin(0, x))

        response = await asyncio.gather(*map(code, clique, shares))
        assert response == [expected] * len(clique)
