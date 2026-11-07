#################################################################################
#  Copyright (c) 2026 Contributors to the Eclipse Foundation
#
#  See the NOTICE file(s) distributed with this work for additional
#  information regarding copyright ownership.
#
#  This program and the accompanying materials are made available under the
#  terms of the Apache License, Version 2.0 which is available at
#  https://www.apache.org/licenses/LICENSE-2.0.
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#  WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#  License for the specific language governing permissions and limitations
#  under the License.
#
#  AI Disclosure: This file was entirely AI-generated.
#  The AI-generated portions are made available under CC0-1.0 and not subject
#  to the project's license. The human contributor has reviewed and verified
#  that the code is correct.
#
#  SPDX-License-Identifier: Apache-2.0 AND CC0-1.0
#  Assisted-By: Claude Code (claude-opus-5-5)
#################################################################################
"""Module registry: one folder per module of the spec, `modules/<module id with _>/`.

Contract of a module folder (a team replaces only its folder):
- `interface.py` with a function for every step and query of the spec (README, module structure);
- `router.py` with `router` (an `APIRouter` under the base path of the spec) and `reset()`;
- optional in `router.py`: `on_event(event)` (subscriber of the event relay), `on_startup()`;
- `STANDIN = True` marks the stand-in, `PROVIDED = True` a provided module (C12-M1); a team's
  module sets neither;
- an empty `__init__.py`, no top-level modules beside the folders.

The list of modules comes from the spec (every folder with an `/api/<module>` base), limited to
`ENABLED_MODULES` when set (one runtime per module, ADR-0002). A module
without a folder is still mounted, as the spec-driven fallback (every path answers 501, steps DONE).
Every operation of the spec that a module does not implement is added from the fallback too.
"""
from __future__ import annotations

import importlib
import importlib.util
from dataclasses import dataclass
from types import ModuleType

from portal_common import runtime, spec

LAST = ("c11-m1", "c12-m1")   # subscribers that react to the events of all others


@dataclass
class Entry:
    id: str
    module: ModuleType | None   # router.py of the folder, None = spec fallback only
    kind: str                   # "stand-in", "provided", "team" or "fallback"


def load() -> list[Entry]:
    entries = []
    for mid in spec.modules():
        if not runtime.is_enabled(mid):
            continue   # served by another runtime, reached through MODULE_URLS
        name = f"modules.{mid.replace('-', '_')}.router"
        mod = importlib.import_module(name) if importlib.util.find_spec(name.rsplit(".", 1)[0]) and \
            importlib.util.find_spec(name) else None
        kind = ("fallback" if mod is None else "stand-in" if getattr(mod, "STANDIN", False)
                else "provided" if getattr(mod, "PROVIDED", False) else "team")
        entries.append(Entry(mid, mod, kind))
    return sorted(entries, key=lambda e: (e.id in LAST, LAST.index(e.id) if e.id in LAST else 0, e.id))
