CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE users (
    email text PRIMARY KEY,
    name text NOT NULL,
    secret_number bigint NOT NULL
);

CREATE TYPE election_type AS ENUM ('plurality', 'range', 'approval', 'veto', 'borda');

CREATE TABLE elections (
    election_id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    manager_email text REFERENCES users(email),
    name text,
    selected_election_type election_type NOT NULL,
    candidates text[] NOT NULL,
    winner_count smallint NOT NULL,
    p bigint NOT NULL,
    L smallint
);

CREATE TABLE election_votes (
    election_id uuid REFERENCES elections(election_id),
    email text REFERENCES users(email),
    PRIMARY KEY (election_id, email)
);
