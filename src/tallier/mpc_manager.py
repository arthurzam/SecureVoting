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

from struct import pack, unpack, Struct
from typing import Tuple, Dict, Optional, List, Union
from dataclasses import dataclass
from uuid import UUID
from pathlib import Path
import logging
import asyncio
import ssl

from mpc import MpcValidation, MpcWinner, TallierConn, TallierConnFactory
from mytypes import Election, TallierAddress

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

TALLIER_PORT = 18080


class Tallier(TallierConn):
    def __init__(self, reader: Optional[asyncio.StreamReader], writer: Optional[asyncio.StreamWriter]):
        self.reader, self.writer = reader, writer
        self.queue: Dict[int, Union[List[int], asyncio.Future]] = {}
        self.struct = Struct('>II')

    async def close(self):
        try:
            self.writer.close()
            await self.writer.wait_closed()
        except Exception as e:
            logger.error("MultiTallier::close", exc_info=e)

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
        self.writer.write(self.struct.pack(msgid, values[0]))
        await self.writer.drain()

    async def receive_loop(self):
        logger.info("receive_loop")
        try:
            while True:
                msgid, share = self.struct.unpack(await self.reader.readexactly(self.struct.size))
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
        self.struct = Struct('>I' + self.size * 'I')

    async def close(self):
        try:
            self.writer.close()
            await self.writer.wait_closed()
        except Exception as e:
            logger.error("MultiTallier::close", exc_info=e)

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
        pad = (0, ) * (self.size - len(values))
        self.writer.write(self.struct.pack(msgid, *values, *pad))
        await self.writer.drain()

    async def receive_loop(self):
        try:
            while True:
                msgid, *share = self.struct.unpack(await self.reader.readexactly(self.struct.size))
                if isinstance(a := self.queue.setdefault(msgid, []), list):
                    a.append(tuple(share))
                else:
                    self.queue.pop(msgid).set_result(tuple(share))
        except asyncio.CancelledError:
            await self.close()


def client_ssl_key(ca_certfile: Path) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(ca_certfile)
    context.check_hostname = False
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

    collected_all: asyncio.Event

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
            logger.debug("[Connect %s] start", destination)
            reader, writer = await asyncio.open_connection(host=destination.address, port=destination.port, ssl=client_ssl_key(self.ca_certfile))
            wait_item = self.mpc_wait_list[election_id]

            logger.debug("[Connect %s] data send", destination)
            writer.write(wait_item.self_id.to_bytes(1, 'big') + wait_item.election_id.bytes)
            await writer.drain()

            logger.debug("[Connect %s] data recv", destination)
            block = await reader.readexactly(17)
            conn_id = block[0]
            if wait_item.talliers[conn_id] is None:
                logger.debug("[Connect %s] adding", destination)
                wait_item.add_tallier(conn_id, reader, writer)
            else:
                logger.info('[Connect %s] Got another conn=%d for election %s', destination, conn_id, wait_item.election_id)
                writer.close()
                await writer.wait_closed()
        except asyncio.IncompleteReadError:
            logger.info('[Connect %s] closed', destination)
        except Exception as e:
            logger.error('failed connect %s', destination, exc_info=e)

    async def _react_conn(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        logger.debug("[###] Got connection")
        try:
            block = await reader.readexactly(17)
            conn_id = block[0]
            logger.debug("[###] Got data from %d", conn_id)

            wait_item = await self._get_wait_item(UUID(bytes=block[1:]))
            if wait_item.talliers[conn_id] is None:
                logger.debug("[%d] adding", conn_id)
                writer.write(wait_item.self_id.to_bytes(1, 'big') + wait_item.election_id.bytes)
                await writer.drain()

                wait_item.add_tallier(conn_id, reader, writer)
            else:
                logger.info('[###] Got another conn=%d for election %s', conn_id, wait_item.election_id)
                writer.close()
                await writer.wait_closed()
        except Exception as e:
            logger.error('failed on connection reaction', exc_info=e)

    async def start_clique(self, election_id: UUID, wanted_talliers: List[TallierAddress], self_id: int, tallier_factory: TallierConnFactory) -> List[TallierConn]:
        logger.info('Loading clique %s', election_id)
        base_talliers = [None for _ in wanted_talliers]
        wait_item = MpcWaitItem(self_id, election_id, tallier_factory, base_talliers, len(base_talliers) - 1, asyncio.Event())
        self.mpc_wait_list[election_id] = wait_item
        if wait_config := self.config_wait_list.pop(election_id, None):
            wait_config.set()
        for index, destination in enumerate(wanted_talliers):
            if index < self_id:
                asyncio.ensure_future(self._connect(election_id, destination))
        await wait_item.collected_all.wait()
        logger.info('Got all %s', election_id)
        del self.mpc_wait_list[election_id]
        return list(wait_item.talliers)

    async def start_election_voting(self, election: Election, wanted_talliers: List[TallierAddress], self_id: int) -> MpcValidation:
        m = MpcValidation.message_size(election)
        def tallier_factory(reader, writer):
            return MultiTallier(m, reader, writer)
        talliers = await self.start_clique(election.election_id, wanted_talliers, self_id, tallier_factory)
        return MpcValidation(election, talliers)

    async def calc_winners(self, election: Election, wanted_talliers: List[TallierAddress], self_id: int, votes_vector: Tuple[int, ...]) -> Tuple[str, ...]:
        logger.info('Starting winner for %s with %s', election.election_id, votes_vector)
        def tallier_factory(reader, writer):
            return Tallier(reader, writer)
        talliers = await self.start_clique(election.election_id, wanted_talliers, self_id, tallier_factory)
        mpc = MpcWinner(election, talliers)
        try:
            votes, names, winners = list(votes_vector), list(election.candidates), []
            for i in range(election.winner_count):
                logger.info('phase %d', i)
                winner = await mpc.max(0, votes)
                winners.append(names[winner])
                del votes[winner]
                del names[winner]
            return tuple(winners)
        finally:
            await mpc.close()
