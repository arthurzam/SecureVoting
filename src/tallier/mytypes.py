from typing import List, NamedTuple
from uuid import UUID
from enum import Enum


class ElectionType(int, Enum):
    plurality = 1
    range = 2
    approval = 3
    veto = 4
    borda = 5
    copeland = 6
    maximin = 7


class Election(NamedTuple):
    election_id: UUID
    election_name: str
    manager_email: str
    selected_election_type: ElectionType
    candidates: List[str]
    winner_count: int
    p: int
    L: int


class TallierAddress(NamedTuple):
    address: str
    port: int

    def __str__(self) -> str:
        return f'{self.address}:{self.port}'

__all__ = ['ElectionType', 'Election', 'TallierAddress']
