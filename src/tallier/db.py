from pathlib import Path

import logging
import uuid
import asyncpg

logger = logging.getLogger('db')
logger.setLevel(logging.INFO)

class DBconn:
    def __init__(self, user: str, database: str) -> None:
        self.user = user
        self.database = database
        self.conn: asyncpg.Connection = None
    
    async def __aenter__(self):
        await self.__create_tables()
        self.conn = await asyncpg.connect(host='db', user=self.user, password='password', database=self.database)
        return self

    async def __aexit__(self, *args, **kargs):
        await self.conn.close()

    async def register(self, email: str, name: str, secret_number: int) -> bool:
        try:
            async with self.conn.transaction():
                await self.conn.execute("""
                    INSERT INTO users(email, name, secret_number) VALUES ($1, $2, $3)
                """, email, name, secret_number)
                return True
        except asyncpg.UniqueViolationError:
            return False

    async def login(self, email: str, secret_number: int) -> bool:
        async with self.conn.transaction():
            return 1 == await self.conn.fetchval("""
                SELECT COUNT(*) FROM users WHERE email = $1 AND secret_number = $2
            """, email, secret_number)
    
    async def get_elections_ids(self, email: str) -> tuple[tuple[uuid.UUID, ...], tuple[uuid.UUID, ...]]:
        async with self.conn.transaction():
            managed = await self.conn.fetch("""
                SELECT election_id FROM elections WHERE manager_email = $1
            """, email)
            voting = await self.conn.fetch("""
                SELECT election_id FROM election_votes WHERE email = $1
            """, email)
            return tuple(r['election_id'] for r in managed), tuple(r['election_id'] for r in voting)

    async def __create_tables(self) -> None:
        try:
            conn = await asyncpg.connect(host='db', user=self.user, password='password', database=self.database)
            logger.info('Database was already ready')
            await conn.close()
        except asyncpg.PostgresError:
            try:
                logger.info('connecting as super user')
                sys_conn = await asyncpg.connect(
                    host='db', 
                    database='template1',
                    user='postgres',
                    password='password',
                )

                try:
                    logger.info('creating user %s', self.user)
                    await sys_conn.execute(f""" CREATE USER "{self.user}" PASSWORD 'password' """)
                except asyncpg.DuplicateObjectError:
                    logger.info('user %s already exists', self.user)
                logger.info('creating database %s for %s', self.database, self.user)
                await sys_conn.execute(f""" CREATE DATABASE "{self.database}" OWNER "{self.user}" """)
            finally:
                await sys_conn.close()

            try:
                conn = await asyncpg.connect(host='db', user=self.user, password='password', database=self.database)
                logger.info('filling database %s', self.database)

                with Path(__file__).with_name('init.sql').open('r') as f:
                    INIT_DB_SQL = f.read()
                
                await conn.execute(INIT_DB_SQL)
            finally:
                await conn.close()
