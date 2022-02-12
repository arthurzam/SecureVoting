from typing import Dict
from uuid import UUID
import websockets as ws
import contextlib
import logging
import asyncio
import json

from db import DBconn
from mpc_manager import TallierManager
from mpc import MpcValidation
from mytypes import Election, ElectionType


running_elections: Dict[UUID, MpcValidation] = {}


def websock_server(db: DBconn, manager: TallierManager, tallier_id: int, wanted_talliers):
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

            elif path == "/election":
                if not await db.login(message['email'], int(message['number'])):
                    return await websocket.close(code=1008)
                election = await db.get_election(UUID(message['id']))
                await websocket.send(json.dumps({
                    "rule": election.selected_election_type.value - 1,
                    "candidates": election.candidates,
                    "p": election.p,
                    "L": election.L,
                }))
                return await websocket.close(code=1000)

            elif path == "/elections/create":
                print(message)
                if not await db.login(message['email'], int(message['number'])):
                    return await websocket.close(code=1008)
                election = Election(UUID(message['id']), message['email'], ElectionType(message['rule']), message['candidates'],
                                    message['K'], message['p'], message['L'])
                res = await db.create_election(message['name'], election, tuple(message['voters']))
                return await websocket.close(code=(1000 if res else 1008))

            elif path == "/elections/start":
                if not await db.login(message['email'], int(message['number'])):
                    return await websocket.close(code=1008)
                election = await db.get_election(UUID(message['id']))

                await db.start_election(election)
                running_elections[election.election_id] = await manager.start_election_voting(election, wanted_talliers, tallier_id)
                # TODO: notify all voters & manager
                return await websocket.close(code=1000)

            elif path == "/elections/stop":
                if not await db.login(message['email'], int(message['number'])):
                    return await websocket.close(code=1008)
                election = await db.get_election(UUID(message['id']))
                if election.election_id not in running_elections:
                    return await websocket.close(code=1008)

                if vote_vector := await db.stop_election(election):
                    await running_elections.pop(election.election_id).close()
                    asyncio.ensure_future(manager.calc_winners(election, wanted_talliers, tallier_id, vote_vector))
                    return await websocket.close(code=1000)
                else:
                    return await websocket.close(code=1008)

            elif path == "/elections/vote":
                if not await db.login(message['email'], int(message['number'])):
                    return await websocket.close(code=1008)
                election = await db.get_election(UUID(message['id']))
                if election.election_id not in running_elections:
                    return await websocket.close(code=1008)

                email = message['email']
                votes = tuple(message['votes'])
                if len(votes) != len(election.candidates):
                    return await websocket.close(code=1007)
                not_abstain = message['not_abstain']
                db_status = await db.vote_status(election.election_id, email)

                if not await running_elections[election.election_id].validate(1, votes):
                    logger.info("Invalid vote for %s in election %s", email, election.election_id)
                    return await websocket.close(code=1007)

                await db.vote(election, votes, email, db_status)
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
