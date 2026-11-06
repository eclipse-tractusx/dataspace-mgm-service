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
"""Runtime profile of one process (FRAMEWORK 1, ADR-0002): which modules this pod serves.

`ENABLED_MODULES` is a comma separated list of module ids (`c1-m2,c3-m1`). Unset or empty means all
modules of the spec: the modular monolith. Every other module is reached through its address from
`MODULE_URLS` / `<MODULE>_URL` (FRAMEWORK 4.7), so the same image runs as monolith or as one pod per module.
"""
from __future__ import annotations

import os


def enabled_modules() -> frozenset[str] | None:
    """The module ids this process serves, or None for all of them."""
    raw = os.environ.get("ENABLED_MODULES", "")
    ids = frozenset(m.strip().lower() for m in raw.split(",") if m.strip())
    return ids or None


def is_enabled(module: str) -> bool:
    ids = enabled_modules()
    return ids is None or module in ids
