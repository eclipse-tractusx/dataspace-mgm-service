# Copyright (c) 2026 Contributors to the Eclipse Foundation
# SPDX-License-Identifier: Apache-2.0
"""Setup check for the hackathon: is this laptop ready for Friday?

    uv run python check.py            # all checks, including demo.py (about 1 minute)
    uv run python check.py --no-demo  # without demo.py
    python check.py                   # also works without uv (then it tells you to install uv)

Every line is OK, WARN or FAIL. At the end the check lists what is still to do.
Exit code 0 = no FAIL. Uses only the Python standard library. It only reads, except that it installs
the Python packages into .venv with uv sync, as the Quickstart does.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ORG = "tx-arena-events"
REPO = "dataspace-mgm-service"   # fork of eclipse-tractusx/dataspace-mgm-service
KEYCLOAK_URL = "http://localhost:8080/auth/realms/CX-Central/.well-known/openid-configuration"
DEMO_PORTS = {8000: "OSP A", 8001: "OSP B", 8100: "CSP stand-in"}
AGENT_APIS = {
    "Anthropic (Claude)": "https://api.anthropic.com",
    "OpenAI (Codex, ChatGPT)": "https://api.openai.com",
    "GitHub Copilot": "https://api.githubcopilot.com",
}
AGENT_COMMANDS = ["claude", "codex", "copilot", "gh", "cursor", "code", "aider", "gemini"]

results: list[tuple[str, str, str]] = []  # (status, check, detail)
todos: list[str] = []


def report(status: str, check: str, detail: str = "", todo: str = "") -> None:
    results.append((status, check, detail))
    print(f"  [{status:<4}] {check}" + (f": {detail}" if detail else ""), flush=True)
    if todo:
        todos.append(todo)


def section(title: str) -> None:
    print(f"\n== {title}", flush=True)


def run(cmd: list[str], timeout: float = 30, cwd: Path = ROOT) -> tuple[int, str]:
    """Runs a command; returns (exit code, stdout+stderr). 127 = not found, 124 = timeout."""
    exe = shutil.which(cmd[0])
    if exe is None:
        return 127, ""
    try:
        p = subprocess.run([exe, *cmd[1:]], cwd=cwd, capture_output=True, text=True,
                           timeout=timeout, encoding="utf-8", errors="replace")
        return p.returncode, (p.stdout + p.stderr).strip()
    except subprocess.TimeoutExpired:
        return 124, ""
    except OSError as e:
        return 126, str(e)


def http_status(url: str, timeout: float = 8, verify: bool = True) -> tuple[int | None, str]:
    """HTTP status of a URL; any answer, also 4xx, means the host is reachable.

    On a certificate error it asks once more without verification, only to learn whether the host
    answers (HEAD request, nothing is sent). Then it returns the status with "tls": a company proxy
    breaks open TLS, and Python, uv or Docker may need its certificate."""
    ctx = None if verify else ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=timeout,
                                    context=ctx) as r:
            return r.status, "" if verify else "tls"
    except urllib.error.HTTPError as e:
        return e.code, "" if verify else "tls"
    except urllib.error.URLError as e:
        reason = e.reason
        if verify and (isinstance(reason, ssl.SSLError) or "CERTIFICATE" in str(reason).upper()):
            status, _ = http_status(url, timeout, verify=False)
            return status, "tls"
        return None, str(reason)
    except (socket.timeout, TimeoutError):
        return None, "timeout"
    except OSError as e:
        return None, str(e)


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) != 0


def install_hint(tool: str) -> str:
    win = os.name == "nt"
    if tool == "uv":
        return ('Install uv: powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"'
                if win else "Install uv: curl -LsSf https://astral.sh/uv/install.sh | sh")
    if tool == "git":
        return "Install git: https://git-scm.com/downloads"
    return "Install Docker Desktop (or Docker Engine with Compose): https://docs.docker.com/get-docker/"


def compose_images() -> list[str]:
    """Image names from docker-compose.yml, with ${VAR:-default} resolved like Compose does."""
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    images = re.findall(r"^\s*image:\s*(\S+)", text, flags=re.M)
    return [re.sub(r"\$\{(\w+):-([^}]*)\}", lambda m: os.environ.get(m.group(1)) or m.group(2), i) for i in images]


# --- checks ------------------------------------------------------------------------------------


def check_tools() -> dict[str, bool]:
    section("Tools")
    have = {}
    v = sys.version_info
    report("OK", "Python", f"{v.major}.{v.minor}.{v.micro} (this check runs with it)")

    code, out = run(["git", "--version"])
    have["git"] = code == 0
    if have["git"]:
        report("OK", "git", out)
        _, email = run(["git", "config", "user.email"])
        if email:
            report("OK", "git user.email", email)
            todos.append(f"Sign the Eclipse Contributor Agreement (ECA) with exactly this email address: {email} "
                         "(https://www.eclipse.org/legal/eca/). No ECA, no merge.")
        else:
            report("WARN", "git user.email", "not set",
                   'Set your commit email: git config --global user.email "you@example.com" (the same address '
                   "as your ECA, https://www.eclipse.org/legal/eca/)")
    else:
        report("FAIL", "git", "not found", install_hint("git"))

    code, out = run(["uv", "--version"])
    have["uv"] = code == 0
    if have["uv"]:
        report("OK", "uv", out)
    else:
        report("FAIL", "uv", "not found", install_hint("uv") + ", then open a new terminal")

    code, out = run(["docker", "--version"])
    have["docker"] = False
    if code != 0:
        report("FAIL", "Docker", "not found", install_hint("docker"))
    else:
        code, _ = run(["docker", "info"], timeout=20)
        if code != 0:
            report("FAIL", "Docker", "installed, but not running", "Start Docker Desktop (or the Docker service)")
        else:
            code, cv = run(["docker", "compose", "version"])
            if code != 0:
                report("FAIL", "Docker Compose", "not found", "Install Docker Compose v2 (part of Docker Desktop)")
            else:
                have["docker"] = True
                report("OK", "Docker", f"{out.split(',')[0]}, {cv}")

    found = [c for c in AGENT_COMMANDS if shutil.which(c)]
    if found:
        report("OK", "Coding agent tools on PATH", ", ".join(found))
    else:
        report("WARN", "Coding agent", "no known command found (claude, codex, copilot, gh, cursor, code, ...)",
               "Install and sign in to your coding agent on this laptop")
    return have


def check_repos(have: dict[str, bool], offline: bool) -> None:
    section("Repositories")
    spec = ROOT / "spec"
    if not (spec / "FRAMEWORK.md").exists():
        report("FAIL", "Spec in spec/", "missing",
               f"Clone the spec: git clone https://github.com/{ORG}/portal-backend-spec.git spec")
    else:
        report("OK", "Spec in spec/", "present")
    if not have.get("git"):
        report("FAIL", REPO, "not checked, git is missing")
        return
    code, url = run(["git", "remote", "get-url", "origin"])
    if code == 0 and f"{ORG}/{REPO}" in url:
        report("OK", REPO, url)
    elif code == 0 and f"/{REPO}" in url:
        report("WARN", REPO, f"origin is {url}, you cannot push there",
               f"Work in the fork of the hackathon: git clone https://github.com/{ORG}/{REPO}.git")
    elif code == 0 and "/portal-backend" in url:
        report("WARN", REPO, f"origin is the old repository {url}",
               f"The scaffold moved to Eclipse Tractus-X. Clone it again: git clone https://github.com/{ORG}/{REPO}.git")
    else:
        report("WARN", REPO, f"origin is {url or 'not set'}",
               f"Clone the scaffold: git clone https://github.com/{ORG}/{REPO}.git")

    if offline:
        return
    for name, path, pull in ((REPO, ROOT, "git pull --ff-only"),
                             ("spec", spec, "git -C spec pull --ff-only")):
        if not (path / ".git").exists():
            continue
        if run(["git", "fetch", "-q"], timeout=30, cwd=path)[0] != 0:
            report("WARN", f"{name} up to date", "could not fetch")
            continue
        code, behind = run(["git", "rev-list", "--count", "HEAD..@{u}"], cwd=path)
        if code == 0 and behind.isdigit() and int(behind) > 0:
            report("WARN", f"{name} up to date", f"{behind} commit(s) behind", f"Update {name}: {pull}")
        elif code == 0:
            report("OK", f"{name} up to date")

    _, branch = run(["git", "branch", "--show-current"])
    report("OK", "Current branch", branch or "(detached)")


def check_network(offline: bool) -> None:
    section("Network")
    if offline:
        report("WARN", "Network", "skipped (--offline)")
        return
    tls = False
    for name, url, required in (("GitHub", "https://github.com", True),
                                ("PyPI (Python packages)", "https://pypi.org/simple/", True),
                                ("quay.io (Keycloak image)", "https://quay.io", False)):
        status, err = http_status(url)
        tls = tls or err == "tls"
        if status and err == "tls":
            report("WARN", name, f"HTTP {status}, but TLS is broken open by a proxy")
        elif status:
            report("OK", name, f"HTTP {status}")
        else:
            report("FAIL" if required else "WARN", name, f"not reachable ({err})")
    reachable = []
    for name, url in AGENT_APIS.items():
        status, err = http_status(url)
        tls = tls or err == "tls"
        if status:
            reachable.append(name)
    if reachable:
        report("OK", "Coding agent APIs reachable", ", ".join(reachable))
    else:
        report("WARN", "Coding agent APIs", "none reachable", "Check that your coding agent can reach its API")
    if tls:
        todos.append("TLS errors: you are probably behind a company proxy (e.g. Zscaler). Use "
                     "UV_SYSTEM_CERTS=1 uv sync (older uv: UV_NATIVE_TLS=1), or switch the proxy off for the day.")


def check_python_env(have: dict[str, bool]) -> bool:
    section("Python environment")
    if not have.get("uv"):
        report("FAIL", "uv sync", "skipped, uv is missing")
        return False
    code, out = run(["uv", "sync", "--frozen", "-q"], timeout=300)
    if code == 0:
        report("OK", "uv sync", "packages installed")
        return True
    last = out.splitlines()[-1] if out else f"exit code {code}"
    hint = "Run: uv sync"
    if "certificate" in out.lower():
        hint = "Behind a TLS proxy run: UV_SYSTEM_CERTS=1 uv sync (older uv: UV_NATIVE_TLS=1 uv sync)"
    report("FAIL", "uv sync", last, hint)
    return False


def check_keycloak(have: dict[str, bool]) -> bool:
    section("Keycloak (test Portal IAM)")
    if not have.get("docker"):
        report("FAIL", "Keycloak", "skipped, Docker is not ready")
        return False
    missing = [i for i in compose_images() if run(["docker", "image", "inspect", i])[0] != 0]
    if missing:
        report("FAIL", "Docker images", "not pulled yet: " + ", ".join(missing),
               "Pull the images at home (Keycloak is about 750 MB, the venue Wi-Fi is shared): docker compose pull")
    else:
        report("OK", "Docker images", ", ".join(compose_images()))

    # A GET is not enough: other programs on 8080 (Open WebUI, Tomcat, ...) also answer 200 with HTML.
    body = None
    try:
        with urllib.request.urlopen(KEYCLOAK_URL, timeout=5) as r:
            body = r.read().decode("utf-8", errors="replace")
    except OSError:
        pass
    try:
        issuer = json.loads(body).get("issuer", "") if body else ""
    except (ValueError, AttributeError):
        issuer = ""
    if issuer.endswith("/realms/CX-Central"):
        report("OK", "Keycloak answers", "http://localhost:8080/auth")
        return True
    if body is not None:
        report("FAIL", "Port 8080", "another program answers there, not the Keycloak of the scaffold",
               "Stop the program on port 8080 (Keycloak needs it), then: docker compose up -d")
        return False
    if port_free(8080):
        report("WARN", "Keycloak", "not running",
               "Start Keycloak: docker compose up -d (ready after about a minute), then run this check again")
    else:
        report("FAIL", "Port 8080", "used by another program or Keycloak is still starting",
               "Free port 8080, or wait a minute if you just ran docker compose up -d")
    return False


def check_ports() -> None:
    section("Ports for demo.py")
    busy = [f"{p} ({n})" for p, n in DEMO_PORTS.items() if not port_free(p)]
    if busy:
        report("WARN", "Ports", "in use: " + ", ".join(busy),
               "Stop the program on " + ", ".join(busy) + " (maybe demo.py --serve is still running)")
    else:
        report("OK", "Ports 8000, 8001, 8100", "free")


def check_demo(ready: bool, have: dict[str, bool]) -> None:
    section("demo.py (acceptance, about 1 minute)")
    if not ready:
        report("WARN", "demo.py", "skipped, fix the points above first",
               "When all points above are OK: uv run python check.py (runs demo.py at the end)")
        return
    code, out = run(["uv", "run", "python", "demo.py"], timeout=600)
    counts = [tuple(map(int, m)) for m in re.findall(r"(\d+)/(\d+) checks OK", out)]
    passed, total = sum(c[0] for c in counts), sum(c[1] for c in counts)
    if code == 0:
        report("OK", "demo.py", f"{passed}/{total} checks OK in {len(counts)} scenarios" if counts else "exit code 0")
    else:
        report("FAIL", "demo.py", f"exit code {code}",
               "Run uv run python demo.py and read the first FAIL line; ask us on Friday or in the Teams chat")
        lines = [line for line in out.splitlines() if re.search(r"FAIL|Error|checks OK", line)]
        for line in (lines or out.splitlines())[-5:]:
            print(f"         {line.strip()}")


def check_github_org() -> None:
    section("GitHub organisation")
    if run(["gh", "auth", "status"], timeout=15)[0] != 0:
        report("WARN", f"Membership in {ORG}", "not checked (GitHub CLI gh is not installed or not signed in)")
        todos.append(f"Accept the invitation to the GitHub organisation {ORG} "
                     f"(https://github.com/orgs/{ORG}/invitation, it comes after you sent your GitHub handle)")
        return
    code, out = run(["gh", "api", f"user/memberships/orgs/{ORG}"], timeout=15)
    try:
        state = json.loads(out).get("state") if code == 0 else None
    except ValueError:
        state = None
    if state == "active":
        report("OK", f"Membership in {ORG}", "active")
    elif state == "pending":
        report("WARN", f"Membership in {ORG}", "invitation not accepted yet",
               f"Accept the invitation: https://github.com/orgs/{ORG}/invitation")
    else:
        report("WARN", f"Membership in {ORG}", "no invitation for the signed-in gh account",
               "Send your GitHub handle to the organisers, then accept the invitation")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-demo", action="store_true", help="do not run demo.py")
    parser.add_argument("--offline", action="store_true", help="skip all network checks")
    args = parser.parse_args()
    try:
        sys.stdout.reconfigure(errors="replace")  # old Windows consoles
    except AttributeError:
        pass

    print("Tractus-X hackathon: setup check (only reads; uv sync installs the packages like the Quickstart)")
    have = check_tools()
    check_repos(have, args.offline)
    check_network(args.offline)
    env_ok = check_python_env(have) if not args.offline else have.get("uv", False)
    kc_ok = check_keycloak(have)
    check_ports()
    if not args.offline:
        check_github_org()
    if not args.no_demo:
        no_fail_so_far = not any(s == "FAIL" for s, _, _ in results)
        check_demo(env_ok and kc_ok and no_fail_so_far, have)

    todos.append("Optional: the wallet app hidy on your phone. You do not need it to build; "
                 "we show the real wallet flow on site.")
    fails = sum(s == "FAIL" for s, _, _ in results)
    warns = sum(s == "WARN" for s, _, _ in results)
    print(f"\n== Result: {fails} FAIL, {warns} WARN")
    print("\nStill to do:" if todos else "")
    for i, t in enumerate(dict.fromkeys(todos), 1):
        print(f"  {i}. {t}")
    demo_ok = any(c == "demo.py" and s == "OK" for s, c, _ in results)
    if fails:
        print("\nNot ready yet: fix the FAIL points and run the check again.")
    elif demo_ok:
        print("\nReady for Friday.")
    else:
        print("\nNo blockers found. Run the check once more with Keycloak started, so that demo.py runs too.")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
