# This file is part of SecureVoting.
# Copyright (C) 2021 Lihi Dery, Tamir Tassa, Avishay Yanai, Arthur Zamarin
#
# Foobar is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Foobar is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Foobar.  If not, see <https://www.gnu.org/licenses/>.

import asyncio
from itertools import count, repeat, combinations
import socket
from struct import pack, unpack
import random
import sys
import math
from typing import Union

import impl
import config
config = config.load()
p = config.p

votes_vector = [0] * config.M

vandermond_first_row = impl.inverse([[(i ** j) % p for j in range(config.D)] for i in range(1, config.D + 1)], p)[0]

block_size = int(2 * math.ceil(math.sqrt(math.ceil(math.log2(p)))) ** 2)


def voter_uuid_to_id(voter_uuid) -> int:
    if isinstance(voter_uuid, str):
        if voter_uuid not in config.VOTERS:
            raise ValueError()
        return config.VOTERS.index(voter_uuid)
    assert 0 <= voter_uuid < (65536 / 10)
    return voter_uuid


class Tallier:
    def __init__(self, reader, writer):
        self.reader, self.writer = reader, writer
        self.queue = {}

    async def close(self):
        try:
            self.writer.close()
            await self.writer.wait_closed()
        finally:
            pass

    async def read(self, msgid: int) -> int:
        if msgid in self.queue:
            if len(a := self.queue[msgid]) > 1:
                return a.pop(0)
            else:
                return self.queue.pop(msgid)[0]
        else:
            fut = asyncio.get_event_loop().create_future()
            self.queue[msgid] = fut
            return await fut

    async def write(self, msgid: int, val: int):
        assert 0 <= val < config.p
        self.writer.write(pack('>HI', msgid, val))
        await self.writer.drain()

    async def receive_loop(self):
        try:
            while True:
                msgid, share = unpack('>HI', await self.reader.readexactly(6))
                if isinstance(a := self.queue.setdefault(msgid, []), list):
                    a.append(share)
                else:
                    self.queue.pop(msgid).set_result(share)
        except asyncio.CancelledError:
            await self.close()


class TallierSelf(Tallier):
    def __init__(self):
        Tallier.__init__(self, None, None)

    async def close(self):
        pass

    async def write(self, msgid: int, val: int):
        self.queue.setdefault(msgid, []).append(val)


class MPC:
    def __init__(self, talliers: {int: Tallier}, server_socks: list[socket.socket]):
        self.collectors = [asyncio.create_task(tallier.receive_loop()) for tallier in talliers.values()]
        self.talliers = [talliers[i + 1] for i in range(config.D)]
        self.borda_random = None
        self.server_socks = server_socks

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args, **kargs):
        for collector in self.collectors:
            collector.cancel()
        await asyncio.gather(*(v.close() for v in self.talliers))
        for sock in self.server_socks:
            sock.close()
        if config.debug:
            print('Closed all')

    async def exchange(self, msgid: int, values: [[int, int]]) -> list[int]:
        await asyncio.gather(*(self.talliers[i - 1].write(msgid, val) for i, val in values))
        return list(await asyncio.gather(*(self.talliers[i].read(msgid) for i in range(config.D))))

    async def multiply(self, msgid: int, a: int, b: int) -> int:
        h_i = impl.gen_shamir((a * b) % p, config.D, config.t, p)
        results = await self.exchange(msgid, h_i)
        return sum((lam * h for lam, h in zip(vandermond_first_row, results))) % p

    async def resolve(self, msgid: int, a: int) -> int:
        results = await self.exchange(msgid, tuple((i + 1, a) for i in range(config.D)))
        return impl.resolve(results, p)

    async def random_number(self, msgid: int) -> int:  # Joint Random Number Sharing
        r_i = impl.gen_shamir(random.randint(0, p - 1), config.D, config.t, p)
        return sum(await self.exchange(msgid, r_i)) % p

    async def random_bit(self, msgid: int) -> int:  # Joint Random Bit Sharing
        while True:
            r = await self.random_number(msgid)
            r2 = await self.resolve(msgid, await self.multiply(msgid, r, r))
            if r2 != 0:
                root_inv = pow(impl.modular_sqrt(r2, p), -1, p)
                return ((r * root_inv + 1) * pow(2, -1, p)) % p

    async def fan_in_or(self, msgid: int, a_i: [int]) -> int:  # Unbounded Fan-In Or
        assert len(a_i) > 0
        A = 1 + sum(a_i)
        f_l = [(1, 0)] + [(i + 2, 1) for i in range(len(a_i))]
        alpha_i = impl.lagrange_polynomial(f_l, p)

        res = alpha_i[0] + alpha_i[1] * A
        mul_A = A
        for i in range(1, len(a_i)):
            res += alpha_i[i + 1] * (mul_A := await self.multiply(msgid, A, mul_A))
        return res % p

    async def prefix_or(self, msgid: int, a_i: list[int]) -> [int]:  # Prefix-Or
        async def calc_mul(msgbase: int, first: int, seconds: [int]) -> [int]:
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
        c_j = [sum(g_ij[i][j] for i in range(lam)) % p for j in range(lam)]
        h_j = await asyncio.gather(*(self.fan_in_or(msgid + 2 * j * lam, c_j[:j + 1]) for j in range(lam)))
        s_ij = await asyncio.gather(*map(calc_mul, count(msgid, lam), f_i, repeat(h_j)))
        return [(s + y - f) % p for s_ij_i, y, f in zip(s_ij, y_i, f_i) for s in s_ij_i][:orig_len]

    async def xor(self, msgid: int, a_i: [int], b_i: [int]) -> list[int]:
        assert len(a_i) == len(b_i)
        c_i = await asyncio.gather(*map(self.multiply, count(msgid), a_i, b_i))
        return [(a + b - 2 * c) for a, b, c in zip(a_i, b_i, c_i)]

    async def less_bitwise(self, msgid: int, a_i: [int], b_i: [int]) -> int:  # Bitwise Less-Than
        assert len(a_i) == len(b_i) > 0
        c_i = await self.xor(msgid, a_i, b_i)
        c_i.reverse()
        d_i = await self.prefix_or(msgid, c_i)
        d_i.reverse()
        e_i = [(d_i[i] - d_i[i + 1]) % p for i in range(len(a_i) - 1)] + [d_i[-1]]
        h_i = await asyncio.gather(*map(self.multiply, count(msgid), e_i, b_i))
        return sum(h_i) % p

    async def random_number_bits(self, msgid: int) -> [int]:  # Joint Random Number Bitwise-Sharing
        while True:
            bits_count = math.ceil(math.log2(p))
            r_i = await asyncio.gather(*map(self.random_bit, range(msgid, msgid + bits_count)))
            p_i = [int(digit) for digit in reversed(bin(p)[2:])]
            check_bit = await self.resolve(msgid, await self.less_bitwise(msgid, r_i, p_i))
            if check_bit == 1:
                return r_i

    async def is_odd(self, msgid: int, x: int) -> int:  # LSB of number
        r_i = await self.random_number_bits(msgid)
        r = sum(bit * 2 ** idx for idx, bit in enumerate(r_i)) % p
        c = await self.resolve(msgid, (x + r) % p)
        d = r_i[0] if c % 2 == 0 else (1 - r_i[0]) % p
        c_i = [int(digit) for digit in reversed(bin(c)[2:])]
        c_i += [0] * (len(r_i) - len(c_i))
        e = await self.less_bitwise(msgid, c_i, r_i)
        return (e + d - 2 * await self.multiply(msgid, e, d)) % p

    async def less_middle(self, msgid: int, a: int) -> int:  # Is less than half p
        return (1 - await self.is_odd(msgid, (2 * a) % p)) % p

    async def less(self, msgid: int, a: int, b: int) -> int:  # Comparison
        w, x, y = await asyncio.gather(self.less_middle(msgid + 0, a),
                                       self.less_middle(msgid + block_size, b),
                                       self.less_middle(msgid + block_size * 2, (a - b) % p))
        c = await self.multiply(msgid, x, y)
        d = (x + y - c) % p
        return (await self.multiply(msgid, w, (d - c) % p) + 1 - d) % p

    async def max(self, msgbase: int, votes: [int]) -> [int, int]:
        async def max_idx(msgid: int, a: [int, int], b: [int, int]) -> [int, int]:
            c = await self.less(msgid, a[1], b[1])
            a = await asyncio.gather(self.multiply(msgid, c, b[1]),
                                     self.multiply(msgid + 1, c, b[0]),
                                     self.multiply(msgid + 2, (1 - c) % p, a[1]),
                                     self.multiply(msgid + 3, (1 - c) % p, a[0]))
            return (a[1] + a[3]) % p, (a[0] + a[2]) % p
        if len(votes) == 1:
            return 0
        votes_idx = list(enumerate(votes))
        while len(votes_idx) > 1:
            votes_idx = await asyncio.gather(*(map(max_idx, count(msgbase, 3 * block_size), votes_idx[::2], votes_idx[1::2]))) + votes_idx[len(votes_idx)^1:]
        return await self.resolve(msgbase, votes_idx[0][0])

    async def validate_approval(self, msgbase: int, votes: [int]):
        a_i = await asyncio.gather(*(self.multiply(msgid, a, (1 - a) % p) for msgid, a in enumerate(votes, start=msgbase)))
        a_i = await asyncio.gather(*map(self.resolve, count(msgbase), a_i))
        return all((a == 0 for a in a_i))

    async def validate_plurality(self, msgbase: int, votes: [int]):
        s, f = await asyncio.gather(self.resolve(msgbase, sum(votes) % p),
                                    self.validate_approval(msgbase + 1, votes))
        return s == 1 and f

    async def validate_veto(self, msgbase: int, votes: [int]):
        s, f = await asyncio.gather(self.resolve(msgbase, sum(votes) % p),
                                    self.validate_approval(msgbase + 1, votes))
        return s == config.M - 1 and f

    async def validate_range(self, msgbase: int, votes: [int], max_value: int):
        async def check_range(msgid: int, vote: int):
            mul = vote
            for i in range(max_value):
                mul = await self.multiply(msgid, mul, (i + 1 - vote) % p)
            return 0 == await self.resolve(msgid, mul)
        return all(await asyncio.gather(*map(check_range, count(msgbase), votes)))

    async def validate_borda(self, msgbase: int, votes: [int]):
        async def check_pair(msgid, pair: [int, int]) -> bool:
            rnd = await self.random_number(msgid)
            mul = await self.multiply(msgid, rnd, (pair[0] - pair[1]) % p)
            return 0 != await self.resolve(msgid, mul)

        async def two_stage_permute(msgid: int):
            return (all(await asyncio.gather(*map(check_pair, count(msgid), combinations(votes, 2)))) or
                    all(await asyncio.gather(*map(check_pair, count(msgid), combinations(votes, 2)))))

        return all(await asyncio.gather(self.validate_range(msgbase, votes, config.M - 1),
                                        two_stage_permute(msgbase + config.M)))

    async def validate(self, msgid: int, votes: [int]) -> bool:
        if config.selected_vote_system == config.VoteSystem.PLURALITY:
            return await self.validate_plurality(msgid, votes)
        elif config.selected_vote_system == config.VoteSystem.RANGE:
            return await self.validate_range(msgid, votes, config.L)
        elif config.selected_vote_system == config.VoteSystem.APPROVAL:
            return await self.validate_approval(msgid, votes)
        elif config.selected_vote_system == config.VoteSystem.VETO:
            return await self.validate_veto(msgid, votes)
        elif config.selected_vote_system == config.VoteSystem.BORDA:
            return await self.validate_borda(msgid, votes)
        else:
            return True

    @staticmethod
    def validate_blocksize() -> int:
        if config.selected_vote_system == config.VoteSystem.PLURALITY:
            return config.M + 1
        elif config.selected_vote_system == config.VoteSystem.RANGE:
            return config.M
        elif config.selected_vote_system == config.VoteSystem.APPROVAL:
            return config.M
        elif config.selected_vote_system == config.VoteSystem.VETO:
            return config.M + 1
        elif config.selected_vote_system == config.VoteSystem.BORDA:
            return (config.M * (config.M + 1)) // 2
        else:
            return 0


async def connect_to_all(tallier_id: int) -> MPC:
    talliers = {}
    clique_event, end_votes = asyncio.Event(), asyncio.Event()
    socks = []
    collected_voters_id = set()

    def get_socket() -> socket.socket:  # Get locally bind socket object
        conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if sys.platform != 'win32':
            conn.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        conn.bind(('0.0.0.0', config.TALLIERS[tallier_id - 1][1]))
        socks.append(conn)
        return conn

    async def connect(addr):  # Try to connect to that tallier
        if addr == config.TALLIERS[tallier_id - 1]:
            return
        try:
            (conn := get_socket()).connect(tuple(addr))
            reader, writer = await asyncio.open_connection(sock=conn)

            writer.write(pack('>b', tallier_id))
            await writer.drain()
            t_id = unpack('>b', await reader.readexactly(1))[0]

            assert t_id not in talliers
            talliers[t_id] = Tallier(reader, writer)
            if len(talliers) + 1 == config.D:
                clique_event.set()
        except OSError:
            pass

    async def collect(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            writer.write(pack('>b', tallier_id))
            await writer.drain()
            msg_id = unpack('>b', await reader.readexactly(1))[0]

            if msg_id == -1:  # voter
                if mpc is None:
                    await clique_event.wait()
                voter_id = unpack('>I', await reader.readexactly(4))[0]
                vote = unpack('>' + 'I' * config.M, await reader.readexactly(4 * config.M))
                if voter_id in collected_voters_id:  # already voted
                    writer.write(pack('>I', 0))
                elif await mpc.validate(mpc.validate_blocksize() * voter_uuid_to_id(voter_id), vote):  # valid vote
                    for idx, val in enumerate(vote):
                        votes_vector[idx] += val
                    writer.write(pack('>I', voter_id))
                    collected_voters_id.add(voter_id)
                else:  # invalid vote
                    writer.write(pack('>I', 0))
                await writer.drain()
                writer.close()
                await writer.wait_closed()
            elif msg_id == -2:  # End Votes
                end_votes.set()
                writer.close()
                await writer.wait_closed()
            else:  # tallier
                assert msg_id not in talliers
                talliers[msg_id] = Tallier(reader, writer)
                if len(talliers) + 1 == config.D:
                    clique_event.set()
        except OSError:
            pass

    async def websocket_server(port):
        async def websocket_react(websocket, path):
            import json
            message = json.loads(await websocket.recv())
            if message['U'] in collected_voters_id:  # already voted
                await websocket.send("1")
            elif await mpc.validate(mpc.validate_blocksize() * voter_uuid_to_id(message['U']), message['V']):  # valid vote
                for idx, val in enumerate(message['V']):
                    votes_vector[idx] += val
                await websocket.send("0")
                collected_voters_id.add(message['U'])
            else:  # invalid vote
                await websocket.send("3")
        if not hasattr(config, 'websockets') or not config.websockets:
            return
        import websockets
        async with websockets.serve(websocket_react, "0.0.0.0", port):
            await end_votes.wait()

    (sock := get_socket()).listen(1)
    print('tallier on', config.TALLIERS[tallier_id - 1])
    mpc = None
    server = await asyncio.start_server(collect, sock=sock)
    await asyncio.gather(*map(connect, config.TALLIERS), clique_event.wait())
    mpc = MPC(talliers | {tallier_id: TallierSelf()}, socks)
    if config.debug or __name__ != '__main__':
        print('got all needed talliers')
    await asyncio.gather(end_votes.wait(), websocket_server(1000 + config.TALLIERS[tallier_id - 1][1]))
    if config.debug:
        print('vote finished')
    server.close()
    await server.wait_closed()
    return mpc


def main(tallier_curr: int) -> [str]:
    async def calc() -> [str]:
        async with await connect_to_all(tallier_curr) as mpc:
            votes, names, maxs = votes_vector, config.CANDIDATES, []
            for _ in range(config.K):
                winner = await mpc.max(0, votes)
                maxs.append(names[winner])
                del votes[winner]
                del names[winner]
            return maxs
    try:
        asyncio.set_event_loop(asyncio.new_event_loop())
        return asyncio.get_event_loop().run_until_complete(calc())
    except ConnectionError:
        return []


if __name__ == '__main__':
    if len(sys.argv) >= 2:
        main(int(sys.argv[1]))
    else:
        tallier_curr = int(input("Enter tallier number (d:1,2,...): "))
        for pos, name in enumerate(main(tallier_curr)):
            print(f'#{pos + 1} took {name}')
