import websockets as ws
import logging
import asyncio
import json

from db import DBconn
from mpc_manager import TallierManager


async def websock_server(db: DBconn, manager: TallierManager) -> None:
    logger = logging.getLogger('websocket')
    logger.setLevel(logging.INFO)


    logging.getLogger('websockets.server').setLevel(logging.WARN)

    async def handler(websocket, path: str):
        try:
            message = json.loads(await websocket.recv())
            if path == "/register":
                res = await db.register(message['email'], message['name'], 42)
                logger.info('register %s <%s>: db result is %s', message['name'], message['email'], res)
            elif path == "/login":
                pass
        except Exception as e:
            logger.error('Error handling on %s', path, exc_info=e)

    async with ws.serve(handler, "", 8080):
        await asyncio.Future()
