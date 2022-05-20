# This file is part of SecureVoting.
# Copyright (C) 2021 Lihi Dery, Tamir Tassa, Avishay Yanai, Arthur Zamarin
#
# Foobar is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Foobar is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Foobar.  If not, see <https://www.gnu.org/licenses/>.

import json
from enum import Enum


class VoteSystem(Enum):
    PLURALITY = 0
    RANGE = 1
    APPROVAL = 2
    VETO = 3
    BORDA = 4


def load(path: str = 'config.json'):
    from types import SimpleNamespace
    res = SimpleNamespace()
    res.debug = False
    with open(path) as f:
        config = json.load(f)
        for name in ('p', 'CANDIDATES', 'TALLIERS', 'K', 'L', 'VOTERS', 'websockets'):
            if name in config:
                setattr(res, name, config[name])
        res.M = len(res.CANDIDATES)
        res.D = len(res.TALLIERS)
        res.t = (res.D + 1) // 2
        res.selected_vote_system = VoteSystem(config['selected_vote_system'])
        res.VoteSystem = VoteSystem
    return res
