import websockets as ws
import logging
import asyncio
import json

from db import DBconn
from mpc_manager import TallierManager


def websock_server(db: DBconn, manager: TallierManager, tallier_id: int):
    logger = logging.getLogger('websocket')
    logger.setLevel(logging.INFO)


    logging.getLogger('websockets.server').setLevel(logging.WARN)

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
