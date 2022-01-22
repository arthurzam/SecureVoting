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
