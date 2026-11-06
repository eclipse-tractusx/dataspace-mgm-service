# Administrator guide

This guide is for operators who install and run the Dataspace Management of an onboarding service provider (OSP)
(TRG 1.06). The installation itself is described in [INSTALL.md](../../INSTALL.md); all values of the Helm chart are
listed in the [chart README](../../charts/dataspace-mgm/README.md).

## Components

| Component | Image | Port | Health |
|---|---|---|---|
| Dataspace Management Service | `tractusx/dataspace-mgm-service` | 8000 | `GET /health` → `{"status": "UP", ...}` |
| Dataspace Management UI | `tractusx/dataspace-mgm-ui` | 8080 | `GET /` |

Both containers run as non-root users with a read-only root file system; `/tmp` is an `emptyDir` volume.

## Demo installation and operated installation

With the default values, the chart starts a **demo installation**: OSP A of the hackathon scenario with the in-memory
Portal IAM, the built-in CSP stand-in and test doubles (`backend.testTools=true`). Never expose a demo installation to the
internet.

For an **operated installation**:

1. Set up the Portal IAM (Keycloak) with the realm of C2-M5 and the client `portal-core`.
2. Get the OSP admitted to the trust list of the CSP and create the signing key of the OSP (JWK, ES256).
3. Create the secrets (see below) and a values file with at least:

```yaml
backend:
  testTools: false
  baseUrl: https://api.osp.example.org
  iam:
    url: https://iam.osp.example.org/auth
    realm: CX-Central
  csp:
    url: https://core.csp.example.org
  installation:
    enabled: true
    settings:
      ospId: "<ospId from the trust list of the CSP>"
      ospName: "OSP Example"
      ospCompanyId: "<companyId of the company that owns the OSP>"
      dataspace:
        memberOf: "Catena-X"
        name: "Catena-X"
      masterDataFile: "/app/config/master-data.json"
  secret:
    existingSecret: dataspace-mgm-backend
  signingKey:
    existingSecret: dataspace-mgm-signing-key
  ingress:
    enabled: true
    hosts:
      - host: api.osp.example.org
        paths:
          - path: /
            pathType: Prefix
    tls:
      - secretName: api-osp-tls
        hosts:
          - api.osp.example.org
frontend:
  config:
    environment: prod
  ingress:
    enabled: true
    hosts:
      - host: portal.osp.example.org
        paths:
          - path: /
            pathType: Prefix
    tls:
      - secretName: portal-osp-tls
        hosts:
          - portal.osp.example.org
```

UI and API must share the same registrable domain (session cookie `SameSite=Lax`), and the API must allow the origin of
the UI in CORS with credentials.

## Secrets

Never put secrets into a committed values file. Create them in the namespace before the installation:

```shell
kubectl create secret generic dataspace-mgm-backend \
  --from-literal=SERVICE_CLIENT_SECRET='<client secret of the service accounts svc-<module>>'
kubectl create secret generic dataspace-mgm-signing-key \
  --from-file=osp-signing-key.json=./osp-signing-key.json
```

| Secret | Key | Used for |
|---|---|---|
| `backend.secret.existingSecret` | `SERVICE_CLIENT_SECRET` | Tokens of the service accounts `svc-<module>` in the Portal IAM |
| `backend.signingKey.existingSecret` | `backend.signingKey.key` | `private_key_jwt` towards the CSP (C3-M2), mounted at `/app/secrets` |
| `backend.authorization.apiKey.existingSecret` | `backend.authorization.apiKey.secretKey` (`API_KEY`) | API key of the APIs under `/api/v1`, only with `backend.authorization.enabled` |

## Configuration reference

The chart sets the following environment variables of the service; further configuration variables of the modules
(section 4 of each module specification, e.g. `ISSUER_MODE`, `ISSUER_ROUTES`, `MODULE_URLS`) are set with `backend.env`.

| Variable | Chart value | Meaning |
|---|---|---|
| `BASE_URL` | `backend.baseUrl` | Public address of the installation |
| `TEST_TOOLS` | `backend.testTools` | Starts the test tools (demo only) |
| `IAM_URL`, `IAM_REALM`, `IAM_ISSUER` | `backend.iam.*` | Portal IAM of the installation |
| `CSP_URL` | `backend.csp.url` | Core services of the CSP; empty: built-in stand-in |
| `SETTINGS_FILE` | `backend.installation.*` | Installation settings (FRAMEWORK 4.8) |
| `OSP_SIGNING_KEY_FILE` | `backend.signingKey.*` | Signing key of the OSP |
| `SERVICE_CLIENT_SECRET` | `backend.secret.*` | Client secret of the service accounts |
| `API_AUTH_ENABLED`, `API_KEY_HEADER` | `backend.authorization.enabled`, `.apiKey.header` | API key on the APIs under `/api/v1` (default off, [api-security.md](../developers/api-security.md)) |
| `API_KEY` | `backend.authorization.apiKey.existingSecret` or `.value` | The API key (secret, at least 32 characters) |

The UI reads its runtime configuration from `/config.json` (`frontend.config.apiBaseUrl`, `frontend.config.environment`),
so the same image runs in every environment.

## Operation

- **Health and readiness:** both deployments have liveness and readiness probes; `helm test <release>` checks the
  backend health endpoint and the configuration of the UI.
- **Logs:** both containers log to standard output.
- **Scaling:** the service keeps its state in memory for now, so run exactly one backend replica. The UI can be scaled freely.
- **Resources:** the defaults (backend 250m/750m CPU, 512Mi memory; UI 50m/150m CPU, 128Mi memory) can be changed with
  `backend.resources` and `frontend.resources`.

## Upgrade

```shell
helm repo update
helm upgrade dataspace-mgm tractusx-dev/dataspace-mgm --namespace dataspace-mgm -f my-values.yaml
```

Read the [CHANGELOG](../../CHANGELOG.md) before an upgrade. The last three minor versions of the chart are supported
(TRG 5.10). As long as the data is kept in memory, an upgrade restarts the installation with empty data.

## Uninstall

```shell
helm uninstall dataspace-mgm --namespace dataspace-mgm
```

## NOTICE

This work is licensed under the [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/legalcode).

- SPDX-License-Identifier: CC-BY-4.0
- SPDX-FileCopyrightText: 2026 Contributors to the Eclipse Foundation
- Source URL: https://github.com/eclipse-tractusx/dataspace-mgm-service/blob/main/docs/admin/README.md
