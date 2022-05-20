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
from struct import pack, unpack
import sys

from impl import gen_shamir
import config
config = config.load()


def main(voter_id: int, votes: [int]):
    async def connect(addr) -> int:
        try:
            reader, writer = await asyncio.open_connection(host=addr[0], port=addr[1])
            writer.write(pack('>b', -1))
            await writer.drain()
            tallier_id = unpack('>b', await reader.readexactly(1))[0]

            writer.write(pack('>I', voter_id))
            for vote_shares in votes_shares:
                writer.write(pack('>I', vote_shares[tallier_id]))
            await writer.drain()
            valid_answer = unpack('>I', await reader.readexactly(4))[0]
            writer.close()
            await writer.wait_closed()
            return valid_answer
        except OSError:
            return -1

    votes_shares = [dict(gen_shamir(vote, config.D, config.t, config.p)) for vote in votes]
    valid_answers = asyncio.get_event_loop().run_until_complete(asyncio.gather(*map(connect, config.TALLIERS)))
    if all(x == voter_id for x in valid_answers):
        return 0
    elif all(x == 0 for x in valid_answers):
        return 1
    else:
        return 2


if __name__ == '__main__':
    if len(sys.argv) >= config.M + 2:
        voter_id = int(sys.argv[1])
        votes = map(int, sys.argv[2:])
    else:
        voter_id = int(input('Voter ID: '))
        votes = (int(input(f'Vote for #{i + 1}: ')) for i in range(config.M))
    main(voter_id, votes)

