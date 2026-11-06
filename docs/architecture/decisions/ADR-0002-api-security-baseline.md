# ADR-0002: API key as the minimum layer of the installation APIs, identity provider later

**Status:** accepted (6 Nov 2026), API key disabled by default.
**Guidelines:** [docs/developers/api-security.md](../../developers/api-security.md).

## Context

The module APIs are protected by tokens of the Portal IAM with permissions and scopes from the spec (FRAMEWORK 4.2,
4.3). The new APIs of the installation under `/api/v1` (`controllers/`, first the event inbox of ADR-0001) belong to
no module. Operators want at least one simple layer that they can switch on for every such API without an identity
provider, and later the option to bring their own identity provider. The Industry Core Hub backend already solves this
with an optional API key (`authorization.enabled`, `api_key.key`, `api_key.value`) built on the Eclipse Tractus-X SDK.

## Decision

1. Every API has at least one layer of authentication (guidelines, section 1). Test tools are the only exception and
   run only with `TEST_TOOLS=true`.
2. The routers under `/api/v1` share one dependency, `get_authentication_dependency()` in
   `controllers/fastapi/routers/authentication/auth_api.py`, as in the Industry Core Hub.
3. Its first mode is an API key with the SDK's `AuthManager` (`tractusx_sdk.dataspace.managers`), extended by a
   constant-time comparison. Configuration: `API_AUTH_ENABLED` (default `false`), `API_KEY_HEADER` (default
   `X-Api-Key`), `API_KEY` (secret); Helm values `backend.authorization.*`.
4. The key is checked before the controller's own authorization, never instead of it. Missing or wrong key: 401.
   Enabled without a key: 500 for every call (fail closed).
5. The next mode is an identity provider of the operator (OpenID Connect: issuer, audience, JWKS), added to the same
   dependency. The module APIs stay on the Portal IAM.

## Alternatives

| Option | Why not |
|---|---|
| No layer for `/api/v1` | The controllers would depend only on their own checks; no simple switch for operators. |
| API key on the module APIs too | They already have person and service tokens with permissions; a shared key adds nothing there. |
| Own API key code | The SDK already has it and the Industry Core Hub uses it; one approach across Tractus-X. |
| Enabled by default | Would break the hackathon set-up and demo.py without a key; the default stays off with a warning. |

## Consequences

- New dependency `tractusx-sdk` (0.8.x). It pins `fastapi <0.121` and `uvicorn <0.36.1`, while the service runs
  FastAPI 0.162 and uvicorn 0.54. `[tool.uv] override-dependencies` keeps the service's versions; the service imports
  only the API key manager, which needs nothing but `fastapi.Request`. Remove the override when the SDK supports the
  current FastAPI. The SDK brings further packages (for example SQLAlchemy, python-keycloak); `DEPENDENCIES` lists them
  for the Eclipse Dash check.
- The SDK's `AuthManager` compares the key with `==`; a constant-time comparison should go upstream.
- The OpenAPI document shows the API key as a security scheme of the `/api/v1` operations.

## NOTICE

This work is licensed under the [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/legalcode).

- SPDX-License-Identifier: CC-BY-4.0
- SPDX-FileCopyrightText: 2026 Contributors to the Eclipse Foundation
- Source URL: https://github.com/eclipse-tractusx/dataspace-mgm-services/blob/main/docs/architecture/decisions/ADR-0002-api-security-baseline.md
