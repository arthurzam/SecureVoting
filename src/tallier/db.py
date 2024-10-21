import asyncio
import logging
import uuid
from pathlib import Path

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
                        COUNT(email) FILTER(WHERE vote_state != 2147483648) AS voted,
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
                    INSERT INTO election_votes(election_id, email, vote_state)
                    SELECT $1, *, $3 FROM UNNEST($2::text[])
                """, election.election_id, voters, election.p + 1)
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

    async def get_election_extra(self, election_id: uuid.UUID):
        async with self.conn.transaction():
            values = await self.conn.fetchrow("""
                SELECT name, manager_email, selected_election_type AS rule, candidates, winner_count, p, l,
                    ARRAY_AGG(election_votes.email) AS voters,
                    COUNT(election_votes.email) FILTER(WHERE election_votes.vote_state != 2147483648) AS voted,
                    finished_election.winners AS winners
                FROM elections
                LEFT JOIN election_votes USING (election_id)
                LEFT JOIN finished_election USING (election_id)
                WHERE election_id = $1
                GROUP BY election_id, finished_election.winners
            """, election_id)
            if values is None:
                raise ValueError()
            return {
                k: values[k] for k in ("name", "manager_email", "rule", "candidates", "winner_count", "p", "l", "voters", "voted", "winners")
            } | {"election_id": str(election_id)}

    async def get_election_emails(self, election_id: uuid.UUID) -> tuple[str, tuple[str, ...]]:
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
            return values['manager_name'], tuple(values['voters'])

    async def start_election(self, election: mytypes.Election) -> bool:
        try:
            async with self.conn.transaction():
                await self.conn.execute("""
                    INSERT INTO running_election(election_id, vote_vector)
                    VALUES ($1, $2)
                """, election.election_id, [0] * election.vote_vector_size)
            return True
        except asyncpg.UniqueViolationError:
            return False

    async def stop_election(self, election: mytypes.Election) -> tuple[int, ...] | None:
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

    async def stop_all_elections(self):
        async with self.conn.transaction():
            await self.conn.execute("DELETE FROM running_election")
            logger.info("Stopped all elections")

    async def finish_election(self, election: mytypes.Election, winners: tuple[str, ...]):
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

    async def vote(self, election: mytypes.Election, ballot: tuple[int, ...], email: str, vote_status: int) -> None:
        async with self.conn.transaction():
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

    async def __create_db(self, sys_conn: asyncpg.Connection):
        for i in range(5):
            logger.info('creating database %r for %r, attempt %d',
                            self.database, self.user, i + 1)
            try:
                await sys_conn.execute(f""" CREATE DATABASE "{self.database}" OWNER "{self.user}" """)
                return
            except asyncpg.ObjectInUseError as e:
                logger.error('database %r is already in use', self.database)
                if i == 4:
                    raise e
                await asyncio.sleep(10)

    async def __create_tables(self) -> None:
        try:
            conn = await asyncpg.connect(host='db', user=self.user, password='password', database=self.database)
            logger.info('Database was already prepared')
            await conn.close()
        except asyncpg.PostgresError:
            try:
                logger.info('connecting as super user')
                sys_conn: asyncpg.Connection = await asyncpg.connect(
                    host='db',
                    database='template1',
                    user='postgres',
                    password='password',
                )

                try:
                    logger.info('creating user %r', self.user)
                    await sys_conn.execute(f""" CREATE USER "{self.user}" PASSWORD 'password' """)
                except asyncpg.DuplicateObjectError:
                    logger.info('user %s already exists', self.user)
                await self.__create_db(sys_conn)
            finally:
                await sys_conn.close()

            try:
                conn = await asyncpg.connect(host='db', user=self.user, password='password', database=self.database)
                logger.info('filling database %r', self.database)
                INIT_DB_SQL = Path(__file__).with_name('init.sql').read_text()
                await conn.execute(INIT_DB_SQL)
            finally:
                await conn.close()
