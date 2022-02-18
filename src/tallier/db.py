from pathlib import Path
import logging
from typing import Optional, Tuple
import uuid
import asyncpg

import mytypes

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

    async def get_elections_ids(self, email: str) -> tuple[dict, ...]:
        async with self.conn.transaction():
            elections = await self.conn.fetch("""
                WITH election_stats AS (
                    SELECT election_id, COUNT(email) AS voters,
                        COUNT(email) FILTER(WHERE vote_state != 2147483647) AS voted,
                        (1 = COUNT(email) FILTER(WHERE email = $1)) AS can_vote
                    FROM election_votes
                    GROUP BY election_id
                )
                SELECT name, election_stats.*, (manager_email = $1) AS is_manager,
                    (running_election.vote_vector IS NOT NULL) AS is_running,
                    (finished_election.winners IS NOT NULL) AS is_finished
                FROM elections JOIN election_stats USING (election_id)
                LEFT JOIN running_election USING (election_id)
                LEFT JOIN finished_election USING (election_id)
            """, email)
            def output(record):
                return {k: str(record[k]) for k in ('name', 'election_id', 'voters', 'voted', 'can_vote', 'is_running', 'is_manager', 'is_finished')}
            return tuple(map(output, elections))

    async def create_election(self, election: mytypes.Election, voters: tuple[str, ...]) -> bool:
        try:
            async with self.conn.transaction():
                await self.conn.execute("""
                    INSERT INTO elections(election_id, manager_email, name, selected_election_type, candidates, winner_count, p, l)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """, election.election_id, election.manager_email, election.election_name, election.selected_election_type.name, election.candidates, election.winner_count,
                    election.p, election.L)

                await self.conn.execute("""
                    INSERT INTO election_votes(election_id, email)
                    SELECT $1, * FROM UNNEST($2::text[])
                """, election.election_id, voters)
            return True
        except asyncpg.UniqueViolationError:
            return False

    async def get_election(self, election_id: uuid.UUID) -> mytypes.Election:
        async with self.conn.transaction():
            values = await self.conn.fetchrow("""
                SELECT name, manager_email, selected_election_type, candidates, winner_count, p, l
                FROM elections
                WHERE election_id = $1
            """, election_id)
            if values is None:
                raise ValueError()
            return mytypes.Election(election_id, values['name'], values['manager_email'],
                                    mytypes.ElectionType[values['selected_election_type']],
                                    values['candidates'], values['winner_count'], values['p'], values['l'])

    async def get_election_extra_data(self, election_id: uuid.UUID) -> Tuple[str, Tuple[str, ...]]:
        async with self.conn.transaction():
            values = await self.conn.fetchrow("""
                SELECT users.name AS manager_name, ARRAY_AGG(election_votes.email) AS voters
                FROM elections JOIN election_votes USING (election_id)
                JOIN users ON (elections.manager_email = users.email)
                WHERE election_id = $1
                GROUP BY users.name;
            """, election_id)
            if values is None:
                raise ValueError()
            return (values['manager_name'], tuple(values['voters']))

    async def start_election(self, election: mytypes.Election) -> bool:
        try:
            async with self.conn.transaction():
                await self.conn.execute("""
                    INSERT INTO running_election(election_id, vote_vector)
                    VALUES ($1, $2)
                """, election.election_id, [0] * len(election.candidates))
            return True
        except asyncpg.UniqueViolationError:
            return False

    async def stop_election(self, election: mytypes.Election) -> Optional[Tuple[int, ...]]:
        async with self.conn.transaction():
            vote_vector = await self.conn.fetchval("""
                SELECT vote_vector
                FROM running_election
                WHERE election_id = $1
            """, election.election_id)
            if vote_vector is None:
                return None
            await self.conn.execute("""
                DELETE FROM running_election
                WHERE election_id = $1
            """, election.election_id)
            return tuple(vote_vector)

    async def finish_election(self, election: mytypes.Election, winners: Tuple[str, ...]):
        async with self.conn.transaction():
            await self.conn.execute("""
                INSERT INTO finished_election(election_id, winners)
                VALUES ($1, $2)
            """, election.election_id, winners)

    async def vote_status(self, election_id: uuid.UUID, email: str) -> int:
        async with self.conn.transaction():
            status = await self.conn.fetchval("""
                SELECT vote_state
                FROM running_election JOIN election_votes USING (election_id)
                WHERE election_id = $1 AND email = $2
            """, election_id, email)
            if status is None:
                raise ValueError()
            return status

    async def vote(self, election: mytypes.Election, ballot: tuple[int], email:str, vote_status: int) -> None:
        async with self.conn.transaction():
            logger.info(f"voting with {ballot}")
            await self.conn.execute("""
                UPDATE running_election
                SET vote_vector = sum_int_arrays($2::int[], vote_vector, $3)
                WHERE election_id = $1
            """, election.election_id, ballot, election.p)
            await self.conn.execute("""
                UPDATE election_votes
                SET vote_state = $1
                WHERE election_id = $2 AND email = $3
            """, vote_status, election.election_id, email)

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
