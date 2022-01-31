import asyncio
import sys

from pathlib import Path

from mpc_manager import TallierManager
from websock import websock_server
from db import DBconn

import logging
logging.basicConfig(format='{asctime} | {name:^20} | [{levelname}] {message}', style='{', level=logging.INFO)

async def main(tallier_id: int):
    secrets_dir = Path("/run/secrets")
    async with DBconn(user=f'avote{tallier_id}', database=f'avote{tallier_id}') as db:
        async with TallierManager(secrets_dir / 'certfile.pem', secrets_dir / 'avote_ca.crt') as manager:
            await websock_server(db, manager)

if __name__ == '__main__':
    if len(sys.argv) >= 2:
        asyncio.set_event_loop(loop := asyncio.new_event_loop())
        loop.run_until_complete(main(int(sys.argv[1]) - 1))
        loop.run_forever()
