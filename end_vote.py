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

def main():
    import asyncio
    from struct import pack
    from config import load

    async def connect(addr):
        try:
            reader, writer = await asyncio.open_connection(host=addr[0], port=addr[1])
            writer.write(pack('>b', -2))
            await writer.drain()
            writer.close()
        except ConnectionError:
            pass

    asyncio.set_event_loop(asyncio.new_event_loop())
    asyncio.get_event_loop().run_until_complete(asyncio.gather(*map(connect, load().TALLIERS)))


if __name__ == '__main__':
    main()
