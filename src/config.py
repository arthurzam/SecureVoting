# Copyright (C) 2021-2022 Arthur Zamarin
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

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
