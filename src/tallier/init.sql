CREATE TABLE users (
    email text PRIMARY KEY,
    name text NOT NULL,
    secret_number bigint NOT NULL
);

CREATE TYPE election_type AS ENUM ('plurality', 'range', 'approval', 'veto', 'borda', 'copeland', 'maximin');

CREATE TABLE elections (
    election_id uuid PRIMARY KEY,
    manager_email text NOT NULL REFERENCES users(email),
    name text,
    selected_election_type election_type NOT NULL,
    candidates text[] NOT NULL,
    winner_count smallint NOT NULL,
    p bigint NOT NULL,
    l smallint
);

CREATE TABLE election_votes (
    election_id uuid REFERENCES elections(election_id),
    email text NOT NULL,
    vote_state bigint NOT NULL,
    PRIMARY KEY (election_id, email)
);

CREATE TABLE running_election (
    election_id uuid REFERENCES elections(election_id) PRIMARY KEY,
    vote_vector bigint[]
);

CREATE TABLE finished_election (
    election_id uuid REFERENCES elections(election_id) PRIMARY KEY,
    winners text[] NOT NULL
);

CREATE OR REPLACE FUNCTION sum_int_arrays(bigint[], bigint[], bigint) RETURNS int[]
LANGUAGE SQL immutable AS $$
    SELECT ARRAY_AGG((COALESCE(a, 0) + b) % $3)
    FROM UNNEST($1, $2) AS u(a, b)
$$;

INSERT INTO users
    VALUES('a@a.com', 'Test', 42),
    ('b@a.com', 'Test', 42),
    ('c@a.com', 'Test', 42),
    ('d@a.com', 'Test', 42),
    ('e@a.com', 'Test', 42)
;
