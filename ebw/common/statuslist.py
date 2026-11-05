# Copyright (c) 2026 Contributors to the Eclipse Foundation
# SPDX-License-Identifier: Apache-2.0
"""IETF Token Status List with one bit per credential (0 valid, 1 revoked)."""

import json
import time
import zlib
from pathlib import Path

from common.jose import b64url, b64url_decode, sign_jws

SIZE = 1024  # credentials per list


class StatusList:
    """A list kept in a JSON file: next free index and the revoked indexes."""

    def __init__(self, path: Path, uri: str):
        self.path = path
        self.uri = uri
        self.state = json.loads(path.read_text()) if path.exists() else {"next": 0, "revoked": []}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.state))

    def allocate(self) -> dict:
        """Status claim for a new credential."""
        index = self.state["next"]
        if index >= SIZE:
            raise RuntimeError("status list is full")
        self.state["next"] = index + 1
        self._save()
        return {"status_list": {"idx": index, "uri": self.uri}}

    def set_revoked(self, index: int, revoked: bool = True) -> None:
        indexes = set(self.state["revoked"])
        indexes.add(index) if revoked else indexes.discard(index)
        self.state["revoked"] = sorted(indexes)
        self._save()

    def is_revoked(self, index: int) -> bool:
        return index in self.state["revoked"]

    def token(self, key, header: dict) -> str:
        bits = bytearray(SIZE // 8)
        for index in self.state["revoked"]:
            bits[index // 8] |= 1 << (index % 8)
        payload = {
            "sub": self.uri,
            "iat": int(time.time()),
            "ttl": 60,
            "status_list": {"bits": 1, "lst": b64url(zlib.compress(bytes(bits)))},
        }
        return sign_jws({"typ": "statuslist+jwt", **header}, payload, key)


def status_at(payload: dict, index: int) -> int:
    """Value at index of a status list token payload (already verified)."""
    status_list = payload["status_list"]
    bits = status_list.get("bits", 1)
    if bits not in (1, 2, 4, 8):
        raise ValueError("invalid bits")
    data = zlib.decompress(b64url_decode(status_list["lst"]))
    position = index * bits
    if position // 8 >= len(data):
        raise ValueError("index outside the status list")
    return (data[position // 8] >> (position % 8)) & ((1 << bits) - 1)
