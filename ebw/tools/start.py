# Copyright (c) 2026 Contributors to the Eclipse Foundation
# SPDX-License-Identifier: Apache-2.0
"""Starts test tools, EBW-Connector and Business Wallet.

    .venv/bin/python -m tools.start                 local only (http://localhost:8077, 8078, 8079)
    .venv/bin/python -m tools.start --tunnel        with three Cloudflare quick tunnels, for a wallet on a phone
    .venv/bin/python -m tools.start --direct-post   unencrypted wallet responses (for wallets without direct_post.jwt)

Ctrl+C stops everything.
"""

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "logs"
_OFFSET = int(os.environ.get("EBW_PORT_OFFSET", "0"))
SERVICES = {"test_tools": 8079 + _OFFSET, "connector": 8077 + _OFFSET, "business_wallet": 8078 + _OFFSET}
TITLES = {"test_tools": "Test tools", "connector": "EBW-Connector", "business_wallet": "Business Wallet"}


def local(name: str) -> str:
    return f"http://localhost:{SERVICES[name]}"


def start_tunnel(name: str, metrics_port: int, processes: list) -> str:
    log = open(LOGS / f"cloudflared-{name}.log", "w")
    processes.append(
        subprocess.Popen(
            ["cloudflared", "tunnel", "--no-autoupdate", "--url", local(name), "--metrics", f"127.0.0.1:{metrics_port}"],
            stdout=log, stderr=subprocess.STDOUT,
        )
    )  # fmt: skip
    for _ in range(120):
        try:
            hostname = httpx.get(f"http://127.0.0.1:{metrics_port}/quicktunnel", timeout=1).json().get("hostname")
            if hostname:
                return f"https://{hostname}"
        except (httpx.HTTPError, ValueError):
            pass
        time.sleep(0.5)
    raise RuntimeError(f"no tunnel address for {name}; see {log.name}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tunnel", action="store_true", help="public HTTPS addresses through Cloudflare quick tunnels")
    parser.add_argument("--direct-post", action="store_true", help="RESPONSE_MODE=direct_post")
    args = parser.parse_args()
    LOGS.mkdir(exist_ok=True)
    processes: list[subprocess.Popen] = []
    try:
        if args.tunnel:
            if not shutil.which("cloudflared"):
                sys.exit("cloudflared is missing; on a Mac: brew install cloudflared")
            print("Building the tunnels …", flush=True)
            public = {name: start_tunnel(name, 20300 + i, processes) for i, name in enumerate(SERVICES)}
        else:
            public = {name: local(name) for name in SERVICES}
        common_env = {
            "CONNECTOR_URL": public["connector"],
            "TEST_TOOLS_URL": public["test_tools"],
            "BUSINESS_WALLET_URL": public["business_wallet"],
            "TRUST_LIST_URL": f"{local('test_tools')}/trust-list",
            "TRUST_LIST_SIGNER_FILE": str(ROOT / "test_tools" / ".keys" / "trust-list-signer.json"),
            "STATUS_LIST_CACHE_SECONDS": "5",
            "RESPONSE_MODE": "direct_post" if args.direct_post else "direct_post.jwt",
            "PYTHONUTF8": "1",  # files and logs in UTF-8; Windows would use its code page and fail on names like Łukasz
        }
        for name, port in SERVICES.items():
            # wallets on phones fetch the status list from the URI in the credential, so it must be the public one
            env = {**os.environ, **common_env, "PUBLIC_URL": public[name], "STATUS_BASE_URL": public[name]}
            log = open(LOGS / f"{name}.log", "a")
            processes.append(
                subprocess.Popen(
                    [sys.executable, "-m", "uvicorn", f"{name}.app:app", "--port", str(port),
                     "--reload", "--reload-dir", "common", "--reload-dir", name],
                    cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                )
            )  # fmt: skip
            for _ in range(60):
                try:
                    httpx.get(local(name) + "/", timeout=1)
                    break
                except httpx.HTTPError:
                    time.sleep(0.25)
        print()
        for name in SERVICES:
            print(f"  {TITLES[name]:<16} {public[name]}")
        print(f"\n  Wallet address of the Business Wallet: {public['business_wallet']}/present")
        print(f"  OSP 2.0 demo portal:                  {public['test_tools']}/osp")
        print(f"  Response mode: {common_env['RESPONSE_MODE']}. Logs in {LOGS}. Stop with Ctrl+C.\n", flush=True)
        while all(p.poll() is None for p in processes):
            time.sleep(1)
        print("A service stopped; see logs/.")
    except KeyboardInterrupt:
        pass
    finally:
        for process in processes:
            process.terminate()


if __name__ == "__main__":
    main()
