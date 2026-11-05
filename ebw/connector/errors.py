# Copyright (c) 2026 Contributors to the Eclipse Foundation
# SPDX-License-Identifier: Apache-2.0
class VerificationError(Exception):
    """A check failed; `code` is a failure reason of C5-M1 6.2."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
