from typing import Dict
from uuid import UUID
import websockets as ws
import contextlib
import logging
import asyncio
import json

from db import DBconn
from mpc_manager import TallierManager, TallierAddress, TALLIER_PORT
from mpc import MpcValidation, MpcWinner
from mytypes import Election, ElectionType


running_elections: Dict[UUID, MpcValidation] = {}

wanted_talliers = [TallierAddress(f'avote{i}', TALLIER_PORT) for i in range(1, 4)]


def websock_server(db: DBconn, manager: TallierManager, tallier_id: int):
    logging.getLogger('websockets.server').setLevel(logging.WARN)
    logger = logging.getLogger('websocket')
    logger.setLevel(logging.INFO)

    async def handler(websocket, path: str):
        try:
            message = json.loads(await websocket.recv())
            if path == "/register":
                res = await db.register(message['email'], message['name'], 42)
                logger.info('register %s <%s>: db result is %s', message['name'], message['email'], 'successful' if res else 'unsuccessful')
                if res and tallier_id == 0:
                    from mail import register_email
                    register_email(message['email'], message['name'], 42)
                return await websocket.close(code=(1000 if res else 1008))
            elif path == "/login":
                res = await db.login(message['email'], int(message['number']))
                logger.info('login <%s>: db result is %s', message['email'], 'successful' if res else 'unsuccessful')
                return await websocket.close(code=(1000 if res else 1008))
            elif path == "/elections":
                if not await db.login(message['email'], int(message['number'])):
                    return await websocket.close(code=1008)
                managed, voting = await db.get_elections_ids(message['email'])
                await websocket.send(json.dumps({
                    'managed': managed,
                    'voting': voting,
                }))
                return await websocket.close(code=1000)
            elif path == "/elections/create":
                print(message)
                if not await db.login(message['email'], int(message['number'])):
                    return await websocket.close(code=1008)
                election = Election(message['id'], message['email'], ElectionType(message['rule']), message['candidates'],
                                    message['K'], message['p'], message['L'])
                res = await db.create_election(message['name'], election, tuple(message['voters']))
                return await websocket.close(code=(1000 if res else 1008))
            elif path == "/elections/start":
                if not await db.login(message['email'], int(message['number'])):
                    return await websocket.close(code=1008)
                election = await db.get_election(message['id'])
                running_elections[election.election_id] = await manager.start_election_voting(election, wanted_talliers, tallier_id)
                # TODO: notify all voters & manager
                return await websocket.close(code=1000)
            elif path == "/elections/stop":
                if not await db.login(message['email'], int(message['number'])):
                    return await websocket.close(code=1008)
                return await websocket.close(code=1000)
        except json.JSONDecodeError:
            logger.info('Badly formatted JSON message for %s', path)
            return await websocket.close(code=1003)
        except KeyError as e:
            logger.info('Missing keys in message for %s', path, exc_info=e)
            return await websocket.close(code=1007)
        except ws.exceptions.ConnectionClosedError:
            logger.info('Connection closed')
        except Exception as e:
            logger.error('Error handling on %s', path, exc_info=e)
            return await websocket.close(code=1003)

    return ws.serve(handler, "", 8080)
