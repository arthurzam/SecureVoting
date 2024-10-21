from pathlib import Path
import asyncio
import signal
import sys
import os

from mpc_manager import TallierManager, TallierAddress
from websock import websock_server
from db import DBconn

import logging
logging.basicConfig(format='{asctime} | {name:^11} | [{levelname}] {message}', style='{', level=logging.INFO)

wanted_talliers = [TallierAddress(ip, int(port)) for ip, port in (s.split(':') for s in os.getenv('TALLIERS_INTERNAL').split('|'))]


async def main(tallier_id: int):
    secrets_dir = Path("/run/secrets")
    async with DBconn(user=f'avote{tallier_id}', database=f'avote{tallier_id}') as db:
        await db.stop_all_elections()
        async with TallierManager(secrets_dir / 'certfile.pem', secrets_dir / 'avote_ca.crt') as manager:
            async with websock_server(db, manager, tallier_id, wanted_talliers):
                await cancel


def canceler(signum, frame):
    cancel.set_result(None)

if __name__ == '__main__':
    if len(sys.argv) >= 2:
        asyncio.set_event_loop(loop := asyncio.new_event_loop())
        cancel = loop.create_future()
        signal.signal(signal.SIGINT, canceler)
        signal.signal(signal.SIGTERM, canceler)

        loop.run_until_complete(main(int(sys.argv[1]) - 1))
        loop.run_forever()
