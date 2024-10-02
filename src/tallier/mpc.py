# Copyright (C) 2021-2022 Arthur Zamarin
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from functools import lru_cache
from itertools import combinations, count, repeat
from typing import Callable, Awaitable, Dict, Iterable, List, Optional, Tuple, Sequence
from random import randint
import operator
import logging
import asyncio
import math

from mytypes import Election, ElectionType
import utils

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

class TallierConn:
    async def close(self):
        raise NotImplementedError()

    async def read(self, msgid: int) -> Tuple[int, ...]:
        raise NotImplementedError()

    async def write(self, msgid: int, values: Tuple[int, ...]):
        raise NotImplementedError()

    async def receive_loop(self):
        raise NotImplementedError()

TallierConnFactory = Callable[[asyncio.StreamReader, asyncio.StreamWriter], TallierConn]

class MpcBase:
    def __init__(self, election: Election, talliers: Sequence[TallierConn]):
        self.election = election
        self.D = len(talliers)
        self.p = election.p

        self.collectors = tuple(asyncio.create_task(tallier.receive_loop()) for tallier in talliers if tallier is not None)
        self.talliers = talliers

        self.vandermond_first_row = utils.inverse([[pow(i, j, self.p) for j in range(self.D)] for i in range(1, self.D + 1)], self.p)[0]
        self.gen_shamir = lambda val: utils.clean_gen_shamir(val, self.D, (self.D + 1) // 2, self.p)

    async def close(self):
        for collector in self.collectors:
            collector.cancel()
        await asyncio.gather(*(v.close() for v in self.talliers if v is not None))
        logger.info('Closed MPC for %s', self.election.election_id)


class MpcWinner(MpcBase):
    def __init__(self, election: Election, talliers: Sequence[TallierConn]):
        super().__init__(election, talliers)

        self.block_size = int(2 * math.ceil(math.sqrt(math.ceil(math.log2(self.p)))) ** 2)

    async def exchange(self, msgid: int, values: Tuple[int, ...]) -> Tuple[int, ...]:
        async def single_exchange(tallier: Optional[TallierConn], value: int) -> int:
            if not tallier:
                return value
            await tallier.write(msgid, (value, ))
            return (await tallier.read(msgid))[0]
        return tuple(await asyncio.gather(*map(single_exchange, self.talliers, values)))

    async def bgw_multiply(self, msgid: int, a: int, b: int) -> int:
        results = await self.exchange(msgid, self.gen_shamir((a * b) % self.p))
        return sum(map(operator.mul, self.vandermond_first_row, results)) % self.p

    async def rnd_multiply(self, msgid: int, a: int, b: int) -> int:
        # TODO: pregenerate random shares in D and 2D-1
        r_i = randint(0, self.p - 1)
        d = (self.D + 1) // 2
        r_i_d = utils.clean_gen_shamir(r_i, self.D, d, self.p) # r_i in D shares
        r_i_2d = utils.clean_gen_shamir(r_i, self.D, 2 * d - 1, self.p) # r_i in 2D-1 shares

        r_d = sum(await self.exchange(msgid, r_i_d)) % self.p
        r_2d = sum(await self.exchange(msgid, r_i_2d)) % self.p

        w_d = (a * b + r_2d) % self.p # in 2D-1 shares

        if T := self.talliers[msgid % len(self.talliers)]: # not selected computing tallier
            await T.write(msgid, (w_d, ))
            w_d = (await T.read(msgid))[0] # public value
        else: # computing tallier
            async def get_value(tallier: Optional[TallierConn]) -> int:
                if tallier is None:
                    return w_d
                return (await tallier.read(msgid))[0]

            shares = tuple(await asyncio.gather(*map(get_value, self.talliers)))
            w_d = utils.resolve(shares, self.p) # public value

            async def send_value(tallier: Optional[TallierConn]):
                if tallier is not None:
                    await tallier.write(msgid, (w_d, ))
            await asyncio.gather(*map(send_value, self.talliers))

        return (w_d - r_d) % self.p # in D shares

    multiply = rnd_multiply

    async def resolve(self, msgid: int, a: int) -> int:
        results = await self.exchange(msgid, tuple(a for _ in range(self.D)))
        return utils.resolve(results, self.p)

    async def random_number(self, msgid: int) -> int:  # Joint Random Number Sharing
        r_i = self.gen_shamir(randint(0, self.p - 1))
        return sum(await self.exchange(msgid, r_i)) % self.p

    async def random_bit(self, msgid: int) -> int:  # Joint Random Bit Sharing
        while True:
            r = await self.random_number(msgid)
            r2 = await self.resolve(msgid, await self.multiply(msgid, r, r))
            if r2 != 0:
                root_inv = pow(utils.modular_sqrt(r2, self.p), -1, self.p)
                return ((r * root_inv + 1) * pow(2, -1, self.p)) % self.p

    @lru_cache
    @staticmethod
    def __fan_in_or_coefficients(p: int, length: int):
        f_l = [(1, 0)] + [(i + 2, 1) for i in range(length)]
        return utils.lagrange_polynomial(f_l, p)

    async def fan_in_or(self, msgid: int, a_i: List[int]) -> int:  # Unbounded Fan-In Or
        assert len(a_i) > 0
        A = (1 + sum(a_i)) % self.p
        alpha_i = MpcWinner.__fan_in_or_coefficients(self.p, len(a_i))

        res = alpha_i[0] + alpha_i[1] * A
        mul_A = A
        for i in range(1, len(a_i)):
            res += alpha_i[i + 1] * (mul_A := await self.multiply(msgid, A, mul_A))
        return res % self.p

    async def prefix_or(self, msgid: int, a_i: List[int]) -> List[int]:  # Prefix-Or
        async def calc_mul(msgbase: int, first: int, seconds: Iterable[int]) -> Tuple[int]:
            return await asyncio.gather(*map(self.multiply, count(msgbase), repeat(first), seconds))
        assert len(a_i) > 0
        orig_len = len(a_i)
        lam = math.ceil(math.sqrt(len(a_i)))
        a_i = a_i + [0] * (lam ** 2 - len(a_i))
        a_ij = [a_i[i:i + lam] for i in range(0, len(a_i), lam)]
        x_i = await asyncio.gather(*map(self.fan_in_or, count(msgid, 2 * lam), a_ij))
        y_i = await asyncio.gather(*(self.fan_in_or(msgid + 2 * i * lam, x_i[:i + 1]) for i in range(lam)))
        f_i = [y_i[0]] + [y_i[i] - y_i[i - 1] for i in range(1, lam)]
        g_ij = await asyncio.gather(*map(calc_mul, count(msgid, lam), f_i, a_ij))
        c_j = [sum(g_ij[i][j] for i in range(lam)) % self.p for j in range(lam)]
        h_j = await asyncio.gather(*(self.fan_in_or(msgid + 2 * j * lam, c_j[:j + 1]) for j in range(lam)))
        s_ij = await asyncio.gather(*map(calc_mul, count(msgid, lam), f_i, repeat(h_j)))
        return [(s + y - f) % self.p for s_ij_i, y, f in zip(s_ij, y_i, f_i) for s in s_ij_i][:orig_len]

    async def xor(self, msgid: int, a_i: List[int], b_i: List[int]) -> List[int]:
        assert len(a_i) == len(b_i)
        c_i = await asyncio.gather(*map(self.multiply, count(msgid), a_i, b_i))
        return [(a + b - 2 * c) % self.p for a, b, c in zip(a_i, b_i, c_i)]

    async def less_bitwise(self, msgid: int, a_i: List[int], b_i: List[int]) -> int:  # Bitwise Less-Than
        assert len(a_i) == len(b_i) > 0
        c_i = await self.xor(msgid, a_i, b_i)
        c_i.reverse()
        d_i = await self.prefix_or(msgid, c_i)
        d_i.reverse()
        e_i = [(d_i[i] - d_i[i + 1]) % self.p for i in range(len(a_i) - 1)] + [d_i[-1]]
        h_i = await asyncio.gather(*map(self.multiply, count(msgid), e_i, b_i))
        return sum(h_i) % self.p

    async def random_number_bits(self, msgid: int) -> Tuple[int]:  # Joint Random Number Bitwise-Sharing
        while True:
            bits_count = math.ceil(math.log2(self.p))
            r_i = await asyncio.gather(*map(self.random_bit, range(msgid, msgid + bits_count)))
            p_i = [int(digit) for digit in reversed(bin(self.p)[2:])]
            check_bit = await self.resolve(msgid, await self.less_bitwise(msgid, r_i, p_i))
            if check_bit == 1:
                return r_i

    async def is_odd(self, msgid: int, x: int) -> int:  # LSB of number
        r_i = await self.random_number_bits(msgid)
        r = sum(bit * 2 ** idx for idx, bit in enumerate(r_i)) % self.p
        c = await self.resolve(msgid, (x + r) % self.p)
        d = r_i[0] if c % 2 == 0 else (1 - r_i[0]) % self.p
        c_i = [int(digit) for digit in reversed(bin(c)[2:])]
        c_i += [0] * (len(r_i) - len(c_i))
        e = await self.less_bitwise(msgid, c_i, r_i)
        return (e + d - 2 * await self.multiply(msgid, e, d)) % self.p

    async def less_middle(self, msgid: int, a: int) -> int:  # Is less than half p
        return (1 - await self.is_odd(msgid, (2 * a) % self.p)) % self.p

    async def less(self, msgid: int, a: int, b: int) -> int:  # Comparison
        w, x, y = await asyncio.gather(self.less_middle(msgid + 0, a),
                                       self.less_middle(msgid + self.block_size, b),
                                       self.less_middle(msgid + self.block_size * 2, (a - b) % self.p))
        c = await self.multiply(msgid, x, y)
        d = (x + y - c) % self.p
        return (await self.multiply(msgid, w, (d - c) % self.p) + 1 - d) % self.p

    async def __max_index(self, msgid: int, a: Tuple[Tuple[int, int], ...], b: Tuple[Tuple[int, int], ...]) -> Tuple[Tuple[int, int], ...]:
        c = await self.less(msgid, a[1], b[1])
        a = await asyncio.gather(self.multiply(msgid, c, b[1]),
                                    self.multiply(msgid + 1, c, b[0]),
                                    self.multiply(msgid + 2, (1 - c) % self.p, a[1]),
                                    self.multiply(msgid + 3, (1 - c) % self.p, a[0]))
        return (a[1] + a[3]) % self.p, (a[0] + a[2]) % self.p

    async def is_zero(self, msgid: int, a: int) -> int:
        n = self.p - 1
        result = 1
        while n > 0: # result = a ** (p - 1) mod p
            if n % 2 == 1:
                result = await self.multiply(msgid, result, a)
            result = await self.multiply(msgid, result, result)
            n = n // 2
        return (self.p + 1 - result) % self.p # 1 - result

    async def max(self, msgbase: int, votes: Sequence[int]) -> int:
        if len(votes) == 1:
            return 0
        votes_idx = list(enumerate(votes))
        while len(votes_idx) > 1:
            votes_idx = await asyncio.gather(*(map(self.__max_index, count(msgbase, 3 * self.block_size), votes_idx[::2], votes_idx[1::2]))) + votes_idx[len(votes_idx)^1:]
        return await self.resolve(msgbase, votes_idx[0][0])

    async def is_positive(self, msgid: int, a: int) -> int:
        val = (2 * self.p - 2 * a) % self.p # -2a mod p
        return await self.is_odd(msgid, val)

    async def copeland_scores(self, msgbase: int, M: int, s: int, t: int, votes: tuple[int, ...]) -> tuple[int, ...]:
        def gamma(m1: int, m2: int): # m1 <= m2
            if m1 == m2:
                return 0
            return votes[m2 - m1 - 1 + m1 * M - m1 * (m1 + 1) // 2]

        async def single_score(msgbase: int, m: int):
            positives = [gamma(m, m2) for m2 in range(m+1, M)] + [self.p - gamma(m2, m) for m2 in range(0, m)]
            zeros = [gamma(m, m2) for m2 in range(m+1, M)] + [gamma(m2, m) for m2 in range(0, m)]

            zeros, positives = await asyncio.gather(
                asyncio.gather(*map(self.is_zero, count(msgbase, 1), zeros)), # M-1 computations with width=1
                asyncio.gather(*map(self.is_positive, count(msgbase + M-1, self.block_size), positives)), # M-1 computations with width=block_size
            )
            return (t * sum(positives) + s * sum(zeros)) % self.p

        calc_width = (M - 1) * (1 + self.block_size)
        return tuple(await asyncio.gather(*map(single_score, count(msgbase, calc_width), range(M))))

def _transpose(values: Tuple[Tuple[int, ...], ...]) -> Tuple[Tuple[int, ...], ...]:
    return tuple(map(tuple, zip(*values)))

class MpcValidation(MpcBase):
    async def exchange(self, msgid: int, values: Tuple[Tuple[int, ...], ...]) -> Tuple[Tuple[int, ...], ...]:
        padding_len = self.message_size(self.election) - len(values)
        assert padding_len >= 0
        if padding_len > 0:
            values = tuple(values) + (0,) * padding_len
        async def single_exchange(tallier: Optional[TallierConn], values: Tuple[int, ...]) -> Tuple[int, ...]:
            if not tallier:
                return values
            await tallier.write(msgid, values)
            return (await tallier.read(msgid))[:len(values)]
        return _transpose(tuple(await asyncio.gather(*map(single_exchange, self.talliers, _transpose(values)))))

    async def multiply(self, msgid: int, a_i: Tuple[int, ...], b_i: Tuple[int, ...]) -> Tuple[int, ...]:
        res_i = await self.exchange(msgid, tuple(self.gen_shamir((a * b) % self.p) for a, b in zip(a_i, b_i)))
        return tuple(sum(map(operator.mul, self.vandermond_first_row, res)) % self.p for res in res_i)

    async def resolve(self, msgid: int, a_i: Tuple[int, ...]) -> Tuple[int, ...]:
        res_i = await self.exchange(msgid, tuple(tuple(a for _ in range(self.D)) for a in a_i))
        return tuple(utils.resolve(res, self.p) for res in res_i)

    async def random_number(self, msgid: int, amount: int) -> Tuple[int, ...]:  # Joint Random Number Sharing
        r_i_i = tuple(self.gen_shamir(randint(0, self.p - 1)) for _ in range(amount))
        return tuple(sum(res) % self.p for res in await self.exchange(msgid, r_i_i))

    def __calc_complement(self, votes: Tuple[int, ...], complement: int) -> Tuple[int, ...]:
        return tuple((complement - a) % self.p for a in votes)

    async def validate_approval(self, msgid: int, votes: Tuple[int, ...]) -> bool:
        a_i = await self.multiply(msgid, votes, self.__calc_complement(votes, 1))
        a_i = await self.resolve(msgid, a_i)
        return all((a == 0 for a in a_i))

    async def validate_plurality(self, msgid: int, votes: Tuple[int, ...]) -> bool:
        a_i = await self.multiply(msgid, votes, self.__calc_complement(votes, 1))
        s, *a_i = await self.resolve(msgid, (sum(votes) % self.p, ) + a_i)
        return s == 1 and all((a == 0 for a in a_i))

    async def validate_veto(self, msgid: int, votes: Tuple[int, ...]) -> bool:
        a_i = await self.multiply(msgid, votes, self.__calc_complement(votes, 1))
        s, *a_i = await self.resolve(msgid, (sum(votes) % self.p, ) + a_i)
        M = len(self.election.candidates)
        return s == M - 1 and all((a == 0 for a in a_i))

    async def validate_range(self, msgbase: int, votes: Tuple[int, ...], max_value: int):
        async def check_range(msgid: int, vote: int):
            mul = vote
            for i in range(max_value):
                mul = await self.multiply(msgid, mul, (i + 1 - vote) % self.p)
            return 0 == await self.resolve(msgid, mul)
        return all(await asyncio.gather(*map(check_range, count(msgbase), votes)))

    async def validate_borda(self, msgbase: int, votes: Tuple[int, ...]):
        async def check_pair(msgid, pair: Tuple[int, int]) -> bool:
            rnd = await self.random_number(msgid)
            mul = await self.multiply(msgid, rnd, (pair[0] - pair[1]) % self.p)
            return 0 != await self.resolve(msgid, mul)

        async def two_stage_permute(msgid: int):
            return (all(await asyncio.gather(*map(check_pair, count(msgid), combinations(votes, 2)))) or
                    all(await asyncio.gather(*map(check_pair, count(msgid), combinations(votes, 2)))))

        return all(await asyncio.gather(self.validate_range(msgbase, votes, self.M - 1),
                                        two_stage_permute(msgbase + self.M)))

    async def __validate_condorcer(self, msgbase: int, votes: Tuple[int, ...], q_m: Tuple[int, ...], is_maximin: bool):
        async def nop():
            return tuple()

        q_pairs = [(a - b) % self.p for a, b in combinations(q_m, 2)]
        product_pairs: int | None = None
        resolve_zero: list[int] = []
        ok_flag = True
        M = len(self.election.candidates)
        block_size = M - 1
        for i in range(M+1):
            muls1, muls2 = [], []
            if final_q_pairs := len(q_pairs) == 1:
                val = q_pairs.pop()
                muls1, muls2 = [val], [val]
            else:
                to_mul, q_pairs = q_pairs[:2*block_size], q_pairs[2*block_size:]
                if len(to_mul) % 2 == 1:
                    q_pairs.append(to_mul.pop())
                muls1, muls2 = to_mul[::2], to_mul[1::2]
            pairs_count = len(muls1)

            to_verify = block_size - len(muls1)
            if to_verify > 0:
                verify, votes = votes[:to_verify], votes[to_verify:]
                if is_maximin:
                    muls1.extend(verify)
                    muls2.extend((v - 1) % self.p for v in verify)
                else:
                    muls1.extend((v + 1) % self.p for v in verify)
                    muls2.extend((v - 1) % self.p for v in verify)

            resolve_block_size = block_size - int(bool(product_pairs))
            to_resolve, resolve_zero = resolve_zero[:resolve_block_size], resolve_zero[resolve_block_size:]
            if product_pairs:
                to_resolve.append(product_pairs)

            mul_results, resolve_results = await asyncio.gather(
                self.multiply(msgbase, muls1, muls2) if muls1 else nop(),
                self.resolve(msgbase+1, to_resolve+[0]*(block_size - len(to_resolve))) if to_resolve else nop())
            resolve_results = list(resolve_results[:len(to_resolve)])

            if product_pairs:
                ok_flag = ok_flag and resolve_results.pop() != 0
                product_pairs = None
            ok_flag = ok_flag and all(a == 0 for a in resolve_results)

            if not final_q_pairs:
                q_pairs.extend(mul_results[:pairs_count])
            resolve_zero.extend(mul_results[pairs_count:])
            if len(q_pairs) == 0 and pairs_count != 0:
                product_pairs = mul_results[0]

        return ok_flag

    async def validate_copeland(self, msgbase: int, votes: Tuple[int, ...]):
        def gamma(m1: int, m2: int):
            if m1 == m2:
                return 0
            return votes[m2 - m1 - 1 + m1 * M - m1 * (m1 + 1) // 2]

        M = len(self.election.candidates)
        q_m = tuple(sum(gamma(m2, m1) if m2 < m1 else gamma(m1, m2) for m2 in range(M)) % self.p for m1 in range(M))
        return await self.__validate_condorcer(msgbase, votes, q_m, False)

    async def validate_maximin(self, msgbase: int, votes: Tuple[int, ...]):
        def gamma(m1: int, m2: int):
            if m1 == m2:
                return 0
            return votes[m2 - m1 - 1 + m1 * M - m1 * (m1 + 1) // 2]

        M = len(self.election.candidates)
        q_m = tuple((sum(gamma(m2, m1) if m2 < m1 else gamma(m1, m2) for m2 in range(M)) + M - m1) % self.p for m1 in range(M))
        return await self.__validate_condorcer(msgbase, votes, q_m, True)

    def validate(self, msgid: int, votes: Tuple[int, ...]) -> Awaitable[bool]:
        if self.election.selected_election_type == ElectionType.approval:
            return self.validate_approval(msgid, votes)
        if self.election.selected_election_type == ElectionType.plurality:
            return self.validate_plurality(msgid, votes)
        if self.election.selected_election_type == ElectionType.veto:
            return self.validate_veto(msgid, votes)
        if self.election.selected_election_type == ElectionType.range:
            return self.validate_range(msgid, votes)
        if self.election.selected_election_type == ElectionType.borda:
            return self.validate_borda(msgid, votes)
        if self.election.selected_election_type == ElectionType.copeland:
            return self.validate_copeland(msgid, votes)
        if self.election.selected_election_type == ElectionType.maximin:
            return self.validate_maximin(msgid, votes)
        raise NotImplementedError()

    @staticmethod
    def message_size(election: Election) -> int:
        M = len(election.candidates)
        if election.selected_election_type == ElectionType.approval:
            return M
        if election.selected_election_type == ElectionType.plurality:
            return M + 1
        if election.selected_election_type == ElectionType.veto:
            return M + 1
        if election.selected_election_type == ElectionType.range:
            raise NotImplementedError()
        if election.selected_election_type == ElectionType.borda:
            raise NotImplementedError()
        if election.selected_election_type == ElectionType.copeland:
            return M - 1
        if election.selected_election_type == ElectionType.maximin:
            return M - 1
        raise NotImplementedError()
