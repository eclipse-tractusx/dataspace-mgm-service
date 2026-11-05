<!--
Copyright (c) 2026 Contributors to the Eclipse Foundation
SPDX-License-Identifier: Apache-2.0
-->

# EBW stack for real wallets

Three services for onboarding and sign-in with two wallets, following the spec `C5-M1 EBW-Connector` (version 0.2, `spec/C5-M1-EBWConnector`). Provided for the hackathon, for tests only.

| Service | Port | Task |
|---|---|---|
| EBW-Connector (`connector/`) | 8077 | implements C5-M1: OpenID Connect for clients (OSP, Business Wallet), OpenID4VP to the wallets, verification attestation for the registration |
| Business Wallet (`business_wallet/`) | 8078 | wallet of the company in the browser: holds and presents the LPID, issues powers of attorney to employees and revokes them; sign-in with the EUDI Wallet through the EBW-Connector |
| Test tools (`test_tools/`) | 8079 | test issuer (PID, LPID, mandate from the register), trust list of the core services, OSP 2.0 demo portal at `/osp` |

The EUDI Wallet of the person is a real wallet app on a phone.

| Wallet | Device | Holds |
|---|---|---|
| EUDI Wallet | phone | PID, mandate |
| Business Wallet | browser | LPID; issues powers of attorney |

This folder runs on its own: it needs no Docker, no Keycloak and nothing else from this repository. The rest of the repository does not use it either. There, the Portal IAM signs in at the stand-in `TEST-EBW` (`iam/`), and `tools/ebw_signer.py` issues the verification attestation. The demo portal is a small portal of its own, not the modules of `modules/`.

## Start

From this folder, with Python 3.12 or newer:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m tools.start
```

This starts the three services locally. Keys and data are created on the first start. A wallet on a phone needs public HTTPS addresses; the script builds three Cloudflare Quick Tunnels for them. This needs [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/) and no account:

```bash
.venv/bin/python -m tools.start --tunnel
```

The script shows the three addresses, the wallet address of the Business Wallet and the OSP 2.0 demo portal. Every start with `--tunnel` brings new addresses. Keys and data stay, but credentials issued before no longer work, because their status list is at the old address. After a restart, fetch the credentials in the wallet again, let an administrator fetch the company credential in the Business Wallet again, and issue powers of attorney again. Stop with Ctrl+C. cloudflared needs outgoing connections to Cloudflare; if a network blocks them, use another one, for example a phone hotspot.

One running copy is enough for a group. Every copy has its own keys and trust list, so credentials from one copy are not valid at another.

## What the wallet app needs

- OpenID4VCI with the pre-authorized code flow, without a transaction code; format `dc+sd-jwt`.
- OpenID4VP with DCQL and the client ID scheme `x509_san_dns`. The certificate of the request is self-signed, so the wallet has to accept that for tests.
- The response mode `direct_post.jwt`. For a wallet without it, start with `--direct-post`.

Requests use no `credential_sets` and only claims of the top level. The EBW-Connector accepts a presentation as a list or as a single string per credential.

## Demo

1. **Test tools:** Open them. Scan the QR code "EUDI Wallet of the person" with the wallet app: test PID and mandate of Erika Mustermann, legal representative of Beispiel Maschinenbau GmbH. Below every QR code the page shows whether it is still open, picked up or expired; an offer works once and for 10 minutes, and **New QR code** creates a new one.
2. **Set up the Business Wallet:** In the test tools, copy the LPID link and paste it into the Business Wallet under "Fetch the company credential (LPID)".
3. **Sign in at the Business Wallet:** "Sign in with EUDI Wallet", then scan with the wallet app on the page of the EBW-Connector. Erika is an administrator (mandate from the register, `trust_list`).
4. **Register the company:** In the OSP 2.0 demo portal, "Register company".
   - Step 1: scan with the wallet app (PID and mandate).
   - Step 2: enter the wallet address of the Business Wallet (it is on its start page; the browser remembers it) and "Open in Business Wallet". In the Business Wallet, "Approve".
   - The portal checks the verification attestation as C1-M2 does and then lists the company under "Registered companies". At sign-in it shows whether the represented company is registered.
5. **Power of attorney for an employee:** In the test tools, offer a test PID for another person and scan it with the wallet of that person. In the Business Wallet, "Issue a power of attorney" with the same name and the same date of birth; the person scans the QR code.
   - Sign-in of the employee at the Business Wallet: confirmed through the key of the Business Wallet (`client_key`).
   - Onboarding by the employee: confirmed through the key of the LPID (`company_key`).
   - Sign-in of the employee at the portal without the Business Wallet: `NOT_CONFIRMED` (`ISSUER_NOT_TRUSTED`), because the OSP does not know the Business Wallet.
6. **Revocation:** Revoke the power of attorney in the Business Wallet. The next sign-in of the employee fails with `CREDENTIAL_REVOKED` (status list, after 5 seconds at most).
7. **Start over:** "Reset portal" in the OSP 2.0 demo portal deletes the registrations; "Reset Business Wallet" deletes the LPID and the powers of attorney. Keys and the credentials in the wallet app stay.

## Tests

```bash
.venv/bin/python -m tools.run_tests
```

Starts the three services on test ports with empty folders and checks the acceptance cases of C5-M1 section 13. A script plays the browser and the EUDI Wallet; the Business Wallet is the real one.

## Layout

| Folder | Content |
|---|---|
| `common/` | JWS, JWE (ECDH-ES), SD-JWT VC, status lists, OID4VCI issuer, wallet side (holder), OIDC client, pages |
| `connector/` | EBW-Connector: OIDC (`app.py`), transactions and steps (`transactions.py`), checks of 6.3 and 6.5 (`checks.py`), trust list, clients, pages |
| `business_wallet/` | Business Wallet |
| `test_tools/` | test issuer, trust list, OSP 2.0 demo portal (`osp.py`) |
| `tools/` | `start.py`, `run_tests.py` |

Keys are in `.keys/` of each service, data in `data/`; git ignores both. The settings of the EBW-Connector are in C5-M1 section 4; without `CLIENTS_FILE`, the demo portal (`demo-osp`) and the Business Wallet are registered as clients. The services reload changed code by themselves.

## Left out on purpose

Authorization code flow and PIN at issuing, mdoc, a database (transactions are in memory), ETSI trust lists, design and accessibility of the pages, German pages (C5-M1 asks for German and English; `ui_locales` is ignored).
