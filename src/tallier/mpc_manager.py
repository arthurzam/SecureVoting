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

from struct import pack, unpack
from typing import Tuple, Dict, Optional, List, Union
from dataclasses import dataclass
from uuid import UUID
from pathlib import Path
import logging
import asyncio
import ssl

from mpc import MpcBase, MpcValidation, TallierConn, TallierConnFactory
from mytypes import Election, TallierAddress

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

TALLIER_PORT = 18080


class Tallier(TallierConn):
    def __init__(self, reader: Optional[asyncio.StreamReader], writer: Optional[asyncio.StreamWriter]):
        self.reader, self.writer = reader, writer
        self.queue: Dict[int, Union[List[int], asyncio.Future]] = {}

    async def close(self):
        try:
            self.writer.close()
            await self.writer.wait_closed()
        finally:
            pass

    async def read(self, msgid: int) -> Tuple[int, ...]:
        if msgid in self.queue:
            if len(a := self.queue[msgid]) > 1:
                return (a.pop(0), )
            else:
                return (self.queue.pop(msgid)[0], )
        else:
            fut = asyncio.get_event_loop().create_future()
            self.queue[msgid] = fut
            return (await fut, )

    async def write(self, msgid: int, values: Tuple[int, ...]):
        self.writer.write(pack('>II', msgid, values[0]))
        await self.writer.drain()

    async def receive_loop(self):
        try:
            while True:
                msgid, share = unpack('>II', await self.reader.readexactly(8))
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

    async def write(self, msgid: int, values: Tuple[int, ...]):
        self.queue.setdefault(msgid, []).append(values[0])


class MultiTallier(TallierConn):
    def __init__(self, size: int, reader: Optional[asyncio.StreamReader], writer: Optional[asyncio.StreamWriter]):
        self.reader, self.writer = reader, writer
        self.queue: Dict[int, Union[List[int], asyncio.Future]] = {}
        self.size = size

    async def close(self):
        try:
            self.writer.close()
            await self.writer.wait_closed()
        finally:
            pass

    async def read(self, msgid: int) -> Tuple[int, ...]:
        if msgid in self.queue:
            if len(a := self.queue[msgid]) > 1:
                return a.pop(0)
            else:
                return self.queue.pop(msgid)[0]
        else:
            fut = asyncio.get_event_loop().create_future()
            self.queue[msgid] = fut
            return await fut

    async def write(self, msgid: int, values: Tuple[int, ...]):
        self.writer.write(pack('>I' + self.size * 'I', msgid, *values))
        await self.writer.drain()

    async def receive_loop(self):
        try:
            while True:
                msgid, *share = unpack('>I' + self.size * 'I', await self.reader.readexactly(4 * self.size + 4))
                if isinstance(a := self.queue.setdefault(msgid, []), list):
                    a.append(tuple(share))
                else:
                    self.queue.pop(msgid).set_result(tuple(share))
        except asyncio.CancelledError:
            await self.close()


class MultiTallierSelf(MultiTallier):
    def __init__(self):
        MultiTallier.__init__(self, None, None)

    async def close(self):
        pass

    async def write(self, msgid: int, values: Tuple[int, ...]):
        self.queue.setdefault(msgid, []).append(values)    


def client_ssl_key(ca_certfile: Path) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(ca_certfile)
    # context.check_hostname = False
    return context

def server_ssl_key(certfile: Path) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=certfile)
    return context

@dataclass
class MpcWaitItem():
    self_id: int
    election_id: UUID

    tallier_factory: TallierConnFactory
    talliers: List[Optional[TallierConn]]
    missing_talliers: int

    collected_all = asyncio.Event()

    def add_tallier(self, id: int, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.talliers[id] = self.tallier_factory(reader, writer)
        self.missing_talliers -= 1
        if self.missing_talliers == 0:
            self.collected_all.set()

class TallierManager:
    def __init__(self, server_certfile: Path, ca_certfile: Path):
        self.mpc_wait_list: Dict[UUID, MpcWaitItem] = {}
        self.config_wait_list: Dict[UUID, asyncio.Event] = {}
        self.server = asyncio.start_server(self._react_conn, port=TALLIER_PORT, ssl=server_ssl_key(server_certfile))
        self.ca_certfile = ca_certfile
    
    async def __aenter__(self):
        self.server = await self.server
        return self

    async def __aexit__(self, *args, **kargs):
        self.server.close()
        await self.server.wait_closed()

    async def _get_wait_item(self, election_id: UUID) -> MpcWaitItem:
        if election_id in self.mpc_wait_list:
            pass
        elif election_id in self.config_wait_list:
            await self.config_wait_list[election_id].wait()
        else:
            self.config_wait_list[election_id] = event = asyncio.Event()
            await event.wait()
        return self.mpc_wait_list[election_id]

    async def _connect(self, election_id: UUID, destination: TallierAddress):
        try:
            logger.info("[Connect %s] start", destination)
            reader, writer = await asyncio.open_connection(host=destination.address, port=destination.port, ssl=client_ssl_key(self.ca_certfile))
            wait_item = self.mpc_wait_list[election_id]

            logger.info("[Connect %s] data send", destination)
            writer.write(wait_item.self_id.to_bytes(1, 'big') + wait_item.election_id.bytes)
            await writer.drain()

            logger.info("[Connect %s] data recv", destination)
            block = await reader.readexactly(17)
            conn_id = block[0]
            if wait_item.talliers[conn_id] is None:
                logger.info("[Connect %s] adding", destination)
                wait_item.add_tallier(conn_id, reader, writer)
            else:
                print(f'Got another conn={conn_id} for election {wait_item.election_id}')
                writer.close()
                await writer.wait_closed()
        except Exception as e:
            pass
            # logger.error('failed connect %s', destination, exc_info=e)

    async def _react_conn(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        logger.info("[###] Got connection")
        try:
            block = await reader.readexactly(17)
            conn_id = block[0]
            logger.info("[###] Got data from %d", conn_id)

            wait_item = await self._get_wait_item(UUID(bytes=block[1:]))
            if wait_item.talliers[conn_id] is None:
                logger.info("[%d] adding", conn_id)
                writer.write(wait_item.self_id.to_bytes(1, 'big') + wait_item.election_id.bytes)
                await writer.drain()

                wait_item.add_tallier(conn_id, reader, writer)
            else:
                print(f'Got another conn={conn_id} for election {wait_item.election_id}')
                writer.close()
                await writer.wait_closed()
        except Exception as e:
            pass
            # logger.error('failed on connection reaction', exc_info=e)

    async def start_clique(self, election_id: UUID, wanted_talliers: List[TallierAddress], self_id: int, tallier_factory: TallierConnFactory) -> Tuple[TallierConn, ...]:
        base_talliers = [None for _ in wanted_talliers]
        wait_item = MpcWaitItem(self_id, election_id, tallier_factory, base_talliers, len(base_talliers) - 1)
        self.mpc_wait_list[election_id] = wait_item
        if wait_config := self.config_wait_list.pop(election_id, None):
            wait_config.set()
        for index, destination in enumerate(wanted_talliers):
            if index != self_id:
                asyncio.ensure_future(self._connect(election_id, destination))
        await wait_item.collected_all.wait()
        logger.info('Got all %s', election_id)
        return tuple(wait_item.talliers)

async def main(number):
    secrets_dir = Path("/run/secrets")
    async with TallierManager(secrets_dir / 'certfile.pem', secrets_dir / 'avote_ca.crt') as manager:
        wanted_talliers = [TallierAddress(f'avote{i}', TALLIER_PORT) for i in range(1, 4)]
        def tallier_factory(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
            return Tallier(reader, writer)
        await manager.start_clique(UUID('84137fa9-3cfd-414a-bef5-27b026f835c6'), wanted_talliers, number, tallier_factory)
        await manager.start_clique(UUID('74137fa9-3cfd-414a-bef5-27b026f835c9'), wanted_talliers, number, tallier_factory)
        
if __name__ == '__main__':
    import sys
    if len(sys.argv) >= 2:
        asyncio.set_event_loop(loop := asyncio.new_event_loop())
        loop.run_until_complete(main(int(sys.argv[1]) - 1))

# def main(tallier_curr: int) -> [str]:
#     async def calc() -> [str]:
#         async with await connect_to_all(tallier_curr) as mpc:
#             votes, names, maxs = votes_vector, config.CANDIDATES, []
#             for _ in range(config.K):
#                 winner = await mpc.max(0, votes)
#                 maxs.append(names[winner])
#                 del votes[winner]
#                 del names[winner]
#             return maxs
#     try:
#         loop = asyncio.new_event_loop()
#         asyncio.set_event_loop(loop)
#         return loop.run_until_complete(calc())
#     except ConnectionError:
#         return []


# if __name__ == '__main__':
#     if len(sys.argv) >= 2:
#         main(int(sys.argv[1]))
#     else:
#         tallier_curr = int(input("Enter tallier number (d:1,2,...): "))
#         for pos, name in enumerate(main(tallier_curr)):
#             print(f'#{pos + 1} took {name}')
