# Security guidelines for APIs

Every API of the Dataspace Management Service has at least one layer of authentication, and every new API follows
the rules below. The decisions behind them are [ADR-0002](../architecture/decisions/ADR-0002-api-security-baseline.md)
(API key and identity providers) and [ADR-0001](../architecture/decisions/ADR-0001-events-as-cloudevents.md) (event inbox).

## 1. Which layer protects which API

| API | Path | Authentication | Authorization |
|---|---|---|---|
| Module APIs | `/api/<module>/...` | token of the Portal IAM of the installation (FRAMEWORK 4.2), `tokens.require_spec` | permission from `x-permission` and its scope `company`, `osp` or `own` (FRAMEWORK 4.3) |
| Steps and queries over HTTP | `/api/<module>/steps/...`, `/internal/...` | token of the service account `svc-<module>` | `execute_steps_<module>`, `query_<module>` |
| Callbacks of external systems | paths named by the module | one service account per system, `private_key_jwt` (OP-22) | exactly one permission |
| APIs of the installation | `/api/v1/<category>/...` (`controllers/`) | the API key when enabled (section 3), **and** the controller's own check | per controller, e.g. the event inbox: the service account must own `source` and `type` |
| Server-Sent Events streams | paths ending in `/events` | token in the `Authorization` header only, never in the URL or a cookie | as the operation |
| Test tools | `/scaffold/...`, test IAM, EBW-Connector double | none | only with `TEST_TOOLS=true`; never in an operated installation |

## 2. Checklist for a new API

1. **No anonymous endpoint** outside the test tools. If you think an endpoint must be public (health, JWKS), say so in
   the pull request.
2. **Right place.** A module API goes to `modules/<id>/router.py` with path, permission and scope from the spec. An API
   of the installation goes to `controllers/fastapi/routers/<category>/v1/<name>_api.py`; it inherits the API key of
   `/api/v1` and adds its own authorization.
3. **Shared building blocks only:** `tokens.require_spec`, `tokens.check`, `tokens.claims_from`, `problems`. Never
   decode a token yourself, never accept a token in the query string or a cookie.
4. **Authorize every object.** Scope `company`: `company_id` of the token equals the company of the object, otherwise
   404. Scope `own`: `sub` equals the owner (FRAMEWORK 4.3).
5. **Bind identities to data.** Never trust an identity in the body. The caller may only act for what its token
   proves, e.g. the event inbox accepts only the `source` and the event types of the calling module.
6. **Validate strictly.** Models or explicit checks; errors as Problem Details `validation` (400, never 422); an
   unsupported `Content-Type` is 415.
7. **Limit sizes.** Endpoints that read raw bodies have a limit (the inbox: `EVENT_INBOX_MAX_BYTES`, 64 KiB, 413);
   lists have `size` at most 100 (FRAMEWORK 4.1).
8. **Errors without leaks:** no stack traces, secrets or internal addresses in `detail`; 401, 403 and 404 as in
   FRAMEWORK 4.3. Unhandled errors become 500 `internal-error` through `problems.route_class`.
9. **Secrets** never in logs, events, step results or URLs (FRAMEWORK 4.6). They come from environment variables
   backed by Kubernetes secrets. Compare them in constant time (`hmac.compare_digest`).
10. **Repeatable:** steps are idempotent, events are processed once per `id`, a retried call does no harm.
11. **Audit log** for every changing operation (FRAMEWORK 4.3).
12. **Tests** for the negative cases: 401 without or with a wrong token, 403 without the permission or for another
    identity, 404 for an object of another company, 400, 413 and 415 for bad input
    (example: `tests/test_events_inbox_api.py`).
13. **Documented** in the OpenAPI document: `x-permission`, `x-permission-scope`, the security scheme and the error
    answers.

## 3. API key: the minimum layer

The APIs of the installation under `/api/v1` can require an API key, as in the Industry Core Hub backend. The service
uses the API key manager of the [Eclipse Tractus-X SDK](https://github.com/eclipse-tractusx/tractusx-sdk)
(`AuthManager`), with a constant-time comparison. **It is disabled by default** and the service logs a warning at
start-up.

| Variable | Chart value | Meaning | Default |
|---|---|---|---|
| `API_AUTH_ENABLED` | `backend.authorization.enabled` | `true` requires the key on every call to `/api/v1` | `false` |
| `API_KEY_HEADER` | `backend.authorization.apiKey.header` | header that carries the key | `X-Api-Key` |
| `API_KEY` | `backend.authorization.apiKey.existingSecret` / `.value` | the key, at least 32 characters | – |

- A missing or wrong key answers 401 `urn:api:problem:unauthorized`. Enabled without `API_KEY`, every call answers
  500 `urn:api:problem:configuration`: the service fails closed, never open.
- The key comes before the controller's own check, never instead of it: the event inbox still needs the token of the
  publishing module. The module APIs keep their tokens of the Portal IAM and need no API key.
- Create a key with `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`, keep it in a Kubernetes secret,
  send it only over TLS. To rotate it, change the secret and restart the backend.
- An API key identifies a caller system, not a person. Never use it in place of a token for decisions about people
  or companies.

## 4. Bring your own identity provider (planned)

Operators will be able to use their own identity provider for the APIs of the installation (ADR-0002). It will be a
further mode of `get_authentication_dependency()` in `controllers/fastapi/routers/authentication/auth_api.py`: tokens
of the operator's IdP checked against its issuer, audience and JWKS (OpenID Connect discovery), with the SDK's
`OAuth2Manager` or the shared token validation. Until then, the Portal IAM and the API key are the two options.

## 5. Operation

- TLS and rate limiting at the ingress of the installation, not in the service.
- `TEST_TOOLS=false` in every operated installation (the test tools have no authentication).
- No CORS for the APIs: the UI calls them through its server part (backend for frontend).
- CI checks dependencies (Eclipse Dash), images (Trivy), code (CodeQL), secrets (TruffleHog) and Kubernetes
  manifests (KICS) on every pull request.

## NOTICE

This work is licensed under the [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/legalcode).

- SPDX-License-Identifier: CC-BY-4.0
- SPDX-FileCopyrightText: 2026 Contributors to the Eclipse Foundation
- Source URL: https://github.com/eclipse-tractusx/dataspace-mgm-services/blob/main/docs/developers/api-security.md
