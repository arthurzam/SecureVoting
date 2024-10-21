import asyncio
import json
import logging
import os
from uuid import UUID

import websockets as ws

from db import DBconn
from mpc_manager import TallierManager, Tallier
from mpc import MpcValidation, MpcWinner
from mytypes import Election, ElectionType


running_elections: dict[UUID, MpcValidation] = {}
computation_mpc: MpcWinner | None = None

enable_mail = os.getenv("MAIL_DISABLED") != "1"

def get_user_id(email: str):
    from hashlib import sha1
    return int(sha1(email.encode("utf-8")).hexdigest(), 16) % 2147483647


def clean_user_array(arr: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(k for k in dict.fromkeys(map(str.strip, arr)) if k)


def websock_server(db: DBconn, manager: TallierManager, tallier_id: int, wanted_talliers):
    async def make_computation_mpc() -> MpcWinner:
        computation_election = Election(UUID(bytes=b'\0'*16), "__computation__", "", ElectionType.approval, (), 1, 2147483647, 1)
        talliers = await manager.start_clique(computation_election.election_id, wanted_talliers, tallier_id, Tallier)
        return MpcWinner(computation_election, talliers)

    logging.getLogger('websockets.server').setLevel(logging.WARN)
    logger = logging.getLogger('websocket')
    logger.setLevel(logging.INFO)

    async def handler(websocket, path: str):
        try:
            message = json.loads(await websocket.recv())
            if path == "/register":
                code = get_user_id(message['email'])
                res = await db.register(message['email'], message['name'], code)
                logger.info('register %s <%s>: db result is %s', message['name'], message['email'], 'successful' if res else 'unsuccessful')
                if res and tallier_id == 0 and enable_mail:
                    from mail import register_email
                    register_email(message['email'], message['name'], code)
                return await websocket.close(code=(1000 if res else 1008))

            elif path == "/login":
                res = await db.login(message['email'], int(message['number']))
                logger.info('login <%s>: db result is %s', message['email'], 'successful' if res else 'unsuccessful')
                return await websocket.close(code=(1000 if res else 1008))

            elif path == "/elections":
                if not await db.login(message['email'], int(message['number'])):
                    return await websocket.close(code=1008)
                logger.info('user <%s>: Collected all elections', message['email'])
                elections = await db.get_elections_ids(message['email'])
                await websocket.send(json.dumps(elections))
                return await websocket.close(code=1000)

            elif path == "/election":
                if not await db.login(message['email'], int(message['number'])):
                    return await websocket.close(code=1008)
                election = await db.get_election(UUID(message['id']))
                await websocket.send(json.dumps(election._asdict() | {'election_id': str(election.election_id)}))
                return await websocket.close(code=1000)

            elif path == "/election/extra":
                if not await db.login(message['email'], int(message['number'])):
                    return await websocket.close(code=1008)
                await websocket.send(json.dumps(await db.get_election_extra(UUID(message['id']))))
                return await websocket.close(code=1000)

            elif path == "/elections/create":
                if not await db.login(message['email'], int(message['number'])):
                    return await websocket.close(code=1008)
                candidates = clean_user_array(message['candidates'])
                voters = clean_user_array(message['voters'])
                election = Election(UUID(message['id']), message['name'], message['email'], ElectionType(message['rule']), candidates,
                                    message['K'], message['p'], message['L'])
                if len(election.candidates) == 0 or len(message['voters']) == 0:
                    return await websocket.close(code=4000)
                res = await db.create_election(election, voters)
                return await websocket.close(code=(1000 if res else 1008))

            elif path == "/elections/start":
                if not await db.login(message['email'], int(message['number'])):
                    return await websocket.close(code=1008)
                election = await db.get_election(UUID(message['id']))

                await db.start_election(election)
                running_elections[election.election_id] = await manager.start_election_voting(election, wanted_talliers, tallier_id)
                if tallier_id == 0 and enable_mail:
                    from mail import start_election
                    manager_name, voters = await db.get_election_emails(election.election_id)
                    start_election(manager_name, election, voters)
                return await websocket.close(code=1000)

            elif path == "/elections/stop":
                if not await db.login(message['email'], int(message['number'])):
                    return await websocket.close(code=1008)
                election = await db.get_election(UUID(message['id']))
                if election.election_id not in running_elections:
                    return await websocket.close(code=1008)

                if vote_vector := await db.stop_election(election):
                    await running_elections.pop(election.election_id).close()
                    async def calc_winners():
                        winners = await manager.calc_winners(election, wanted_talliers, tallier_id, vote_vector)
                        if tallier_id == 0 and enable_mail:
                            from mail import stop_election
                            manager_name, voters = await db.get_election_emails(election.election_id)
                            stop_election(manager_name, election, voters, winners)
                        await db.finish_election(election, winners)
                    asyncio.ensure_future(calc_winners())
                    return await websocket.close(code=1000)
                else:
                    return await websocket.close(code=1008)

            elif path == "/elections/vote":
                global computation_mpc
                if computation_mpc is None:
                    computation_mpc = await make_computation_mpc()

                if not await db.login(message['email'], int(message['number'])):
                    return await websocket.close(code=1008)
                election = await db.get_election(UUID(message['id']))
                if election.election_id not in running_elections:
                    return await websocket.close(code=1008)

                email = message['email']
                votes = tuple(message['votes'])
                if len(votes) != election.vote_vector_size:
                    return await websocket.close(code=1007)
                not_abstain = int(message['not_abstain'])
                db_status = await db.vote_status(election.election_id, email)

                if not_abstain == 0:
                    logger.info("Abstain for %s in election %s", email, election.election_id)
                msg_id = get_user_id(email)
                validate = await running_elections[election.election_id].validate(msg_id, votes)
                if not validate:
                    logger.warning("Invalid vote for %s in election %s", email, election.election_id)
                if validate and election.selected_election_type == ElectionType.maximin:
                    votes = await running_elections[election.election_id].convert_copeland_to_maximin(msg_id, votes)
                votes_scale = int(validate) * await computation_mpc.multiply(msg_id, db_status, not_abstain)
                res = await computation_mpc.resolve(msg_id, votes_scale)
                new_votes = await running_elections[election.election_id].multiply(msg_id, votes, tuple(votes_scale for _ in votes))
                new_db_status = await computation_mpc.multiply(msg_id, db_status, 1 - votes_scale)
                await db.vote(election, new_votes, email, new_db_status)
                return await websocket.close(code=(1000 if res else 4000))

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
