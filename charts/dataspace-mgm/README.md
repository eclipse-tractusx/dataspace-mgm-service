# dataspace-mgm

![Version: 0.1.0](https://img.shields.io/badge/Version-0.1.0-informational?style=flat-square) ![Type: application](https://img.shields.io/badge/Type-application-informational?style=flat-square) ![AppVersion: 0.1.0](https://img.shields.io/badge/AppVersion-0.1.0-informational?style=flat-square)

Product Helm chart of the Eclipse Tractus-X **Dataspace Management** (new portal).

It installs the portal of one onboarding service provider (OSP):

- the **Dataspace Management Service** (backend, modular monolith, image [`tractusx/dataspace-mgm-service`](https://hub.docker.com/r/tractusx/dataspace-mgm-service)), and
- the **Dataspace Management UI** (image [`tractusx/dataspace-mgm-ui`](https://hub.docker.com/r/tractusx/dataspace-mgm-ui)).

With the default values the chart starts a self-contained demo installation: OSP A of the hackathon scenario,
with the in-memory Portal IAM, the built-in CSP stand-in and the test doubles (`backend.testTools=true`).
For an operated installation see the [admin guide](https://github.com/eclipse-tractusx/dataspace-mgm-service/blob/main/docs/admin/README.md).

**Homepage:** <https://github.com/eclipse-tractusx/dataspace-mgm-service>

**Source code**: <https://github.com/eclipse-tractusx/dataspace-mgm-service> <https://github.com/eclipse-tractusx/dataspace-mgm-ui>

## Prerequisites

- Kubernetes 1.29+
- Helm 3.8.0+
- An ingress controller, if `backend.ingress.enabled` or `frontend.ingress.enabled` is set
- For an operated installation: a Portal IAM (Keycloak, realm of C2-M5) and access to the core services of a CSP

The service keeps its data in memory for now; no persistent volume and no database are needed (TRG 3.02).
PostgreSQL databases per module will be added as chart dependencies together with the persistence of the modules.

## TL;DR

```shell
helm repo add tractusx-dev https://eclipse-tractusx.github.io/charts/dev
helm install dataspace-mgm tractusx-dev/dataspace-mgm --namespace dataspace-mgm --create-namespace
helm test dataspace-mgm --namespace dataspace-mgm
```

Or from the chart repository of this product:

```shell
helm repo add dataspace-mgm https://eclipse-tractusx.github.io/dataspace-mgm-service
helm install dataspace-mgm dataspace-mgm/dataspace-mgm
```

Or from a checkout of the repository:

```shell
helm install dataspace-mgm charts/dataspace-mgm
```

## Use as a dependency

```yaml
dependencies:
  - name: dataspace-mgm
    repository: https://eclipse-tractusx.github.io/charts/dev
    version: 0.1.0
```

## Upgrade and uninstall

```shell
helm upgrade dataspace-mgm tractusx-dev/dataspace-mgm --namespace dataspace-mgm --reuse-values
helm uninstall dataspace-mgm --namespace dataspace-mgm
```

## Maintainers

| Name | Email | Url |
| ---- | ------ | --- |
| Mathias Brunkow Moser |  | <https://github.com/matbmoser> |

## Values

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| backend.affinity | object | `{}` | Affinity of the backend pods |
| backend.authorization.apiKey.existingSecret | string | `""` | Name of an existing secret with the API key (`API_KEY`). If empty and `value` is set, the chart creates it |
| backend.authorization.apiKey.header | string | `"X-Api-Key"` | Header that carries the API key (`API_KEY_HEADER`) |
| backend.authorization.apiKey.secretKey | string | `"API_KEY"` | Key of the API key in the secret |
| backend.authorization.apiKey.value | string | `""` | The API key, at least 32 characters; prefer `existingSecret` in operated installations |
| backend.authorization.enabled | bool | `false` | Requires an API key on the APIs of the installation under `/api/v1` (`API_AUTH_ENABLED`, ADR-0002). Disabled by default; the controllers keep their own authorization (e.g. service accounts) in any case |
| backend.baseUrl | string | `""` | Public base address of the installation (`BASE_URL`), used for callbacks and links. Defaults to the first ingress host, or to the in-cluster service address |
| backend.csp.url | string | `""` | Address of the core services of the CSP (`CSP_URL`, C3-M2). Empty uses the built-in CSP stand-in |
| backend.enabled | bool | `true` | Whether the Dataspace Management Service (backend) is installed |
| backend.env | object | `{}` | Further configuration variables of the modules as plain environment variables (section 4 of each module spec), e.g. `ISSUER_MODE: CSP`, `MODULE_URLS: ...` |
| backend.extraEnv | list | `[]` | Further environment variables in Kubernetes notation, e.g. from secrets |
| backend.extraVolumeMounts | list | `[]` | Further volume mounts for the backend container |
| backend.extraVolumes | list | `[]` | Further volumes for the backend pod |
| backend.iam.issuer | string | `""` | Expected token issuer (`IAM_ISSUER`); defaults to `<url>/realms/<realm>` |
| backend.iam.realm | string | `"CX-Central"` | Realm of the installation in the Portal IAM (`IAM_REALM`) |
| backend.iam.url | string | `""` | Address of the Portal IAM (Keycloak, C2-M5), e.g. `https://iam.example.org/auth` (`IAM_URL`). Empty uses the in-memory test IAM (only with `testTools=true`) |
| backend.image.pullPolicy | string | `"IfNotPresent"` | Image pull policy |
| backend.image.repository | string | `"tractusx/dataspace-mgm-service"` | Image repository on DockerHub |
| backend.image.tag | string | `""` | Image tag; defaults to the `appVersion` of the chart |
| backend.ingress.annotations | object | `{}` | Ingress annotations, e.g. for cert-manager |
| backend.ingress.className | string | `"nginx"` | Ingress class name |
| backend.ingress.enabled | bool | `false` | Whether an ingress is created for the backend API |
| backend.ingress.hosts | list | `[{"host":"api.dataspace-mgm.example.org","paths":[{"path":"/","pathType":"Prefix"}]}]` | Hosts and paths |
| backend.ingress.tls | list | `[]` | TLS configuration, e.g. `[{secretName: api-tls, hosts: [api.dataspace-mgm.example.org]}]` |
| backend.installation.enabled | bool | `false` | Whether the installation settings (FRAMEWORK 4.8) are provided by this chart. If `false`, the settings built into the image are used (OSP A of the hackathon scenario) |
| backend.installation.settings | object | `{"dataspace":{"memberOf":"Catena-X","name":"Catena-X"},"masterDataFile":"/app/config/master-data.json","ospCompanyId":"11111111-1111-4111-8111-111111111111","ospId":"22222222-2222-4222-8222-222222222222","ospName":"OSP A"}` | Installation settings, rendered as `installation.json` and passed with `SETTINGS_FILE`. Relative paths are resolved against the mount directory `/app/config/installation` |
| backend.livenessProbe | object | `{"failureThreshold":3,"httpGet":{"path":"/health","port":"http"},"initialDelaySeconds":10,"periodSeconds":20,"timeoutSeconds":5}` | Liveness probe of the backend |
| backend.nodeSelector | object | `{}` | Node selector of the backend pods |
| backend.podAnnotations | object | `{}` | Annotations for the backend pods |
| backend.podLabels | object | `{}` | Labels for the backend pods |
| backend.podSecurityContext | object | `{"fsGroup":10001,"runAsGroup":10001,"runAsUser":10001,"seccompProfile":{"type":"RuntimeDefault"}}` | Security context of the backend pods |
| backend.readinessProbe | object | `{"failureThreshold":3,"httpGet":{"path":"/health","port":"http"},"initialDelaySeconds":5,"periodSeconds":10,"timeoutSeconds":5}` | Readiness probe of the backend |
| backend.replicaCount | int | `1` | Number of replicas. The service keeps its state in memory for now: keep 1 replica |
| backend.resources | object | `{"limits":{"cpu":"750m","memory":"512Mi"},"requests":{"cpu":"250m","memory":"512Mi"}}` | Resource requests and limits of the backend (TRG 5.04: memory request = limit, CPU limit > request) |
| backend.secret.existingSecret | string | `""` | Name of an existing secret with the key `SERVICE_CLIENT_SECRET` (client secret of the service accounts `svc-<module>` in the Portal IAM). If empty and `serviceClientSecret` is set, the chart creates the secret |
| backend.secret.serviceClientSecret | string | `""` | Client secret of the service accounts in the Portal IAM; prefer `existingSecret` in operated installations |
| backend.securityContext | object | `{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]},"readOnlyRootFilesystem":true,"runAsGroup":10001,"runAsNonRoot":true,"runAsUser":10001}` | Security context of the backend container (TRG 4.03, TRG 4.07) |
| backend.service.port | int | `8000` | Service port |
| backend.service.type | string | `"ClusterIP"` | Service type |
| backend.signingKey.existingSecret | string | `""` | Name of an existing secret with the signing key of the OSP (JWK, ES256) for the calls to the CSP (`OSP_SIGNING_KEY_FILE`, C3-M2). Mounted read-only at `/app/secrets` |
| backend.signingKey.key | string | `"osp-signing-key.json"` | Key of the signing key in the secret |
| backend.testTools | bool | `true` | Starts the test tools of the installation (`TEST_TOOLS`): in-memory Portal IAM, EBW-Connector double, provider double. Only for demos and tests; set to `false` for an operated installation |
| backend.tolerations | list | `[]` | Tolerations of the backend pods |
| commonLabels | object | `{}` | Additional labels for all resources |
| frontend.affinity | object | `{}` | Affinity of the frontend pods |
| frontend.config | object | `{"apiBaseUrl":"","environment":"prod"}` | Runtime configuration of the UI, served as `/config.json` (no rebuild per environment) |
| frontend.config.apiBaseUrl | string | `""` | Address of the backend API. Defaults to the first backend ingress host, or to `http://localhost:8000` (port-forward) |
| frontend.config.environment | string | `"prod"` | Environment name shown by the UI: `local`, `dev`, `int` or `prod` |
| frontend.enabled | bool | `true` | Whether the Dataspace Management UI is installed |
| frontend.extraEnv | list | `[]` | Further environment variables of the frontend container |
| frontend.image.pullPolicy | string | `"IfNotPresent"` | Image pull policy |
| frontend.image.repository | string | `"tractusx/dataspace-mgm-ui"` | Image repository on DockerHub |
| frontend.image.tag | string | `""` | Image tag; defaults to the `appVersion` of the chart |
| frontend.ingress.annotations | object | `{}` | Ingress annotations, e.g. for cert-manager |
| frontend.ingress.className | string | `"nginx"` | Ingress class name |
| frontend.ingress.enabled | bool | `false` | Whether an ingress is created for the UI |
| frontend.ingress.hosts | list | `[{"host":"portal.dataspace-mgm.example.org","paths":[{"path":"/","pathType":"Prefix"}]}]` | Hosts and paths |
| frontend.ingress.tls | list | `[]` | TLS configuration |
| frontend.livenessProbe | object | `{"httpGet":{"path":"/","port":"http"},"initialDelaySeconds":5,"periodSeconds":20}` | Liveness probe of the frontend |
| frontend.nodeSelector | object | `{}` | Node selector of the frontend pods |
| frontend.podAnnotations | object | `{}` | Annotations for the frontend pods |
| frontend.podLabels | object | `{}` | Labels for the frontend pods |
| frontend.podSecurityContext | object | `{"fsGroup":101,"runAsGroup":101,"runAsUser":101,"seccompProfile":{"type":"RuntimeDefault"}}` | Security context of the frontend pods (nginx-unprivileged runs as user 101) |
| frontend.readinessProbe | object | `{"httpGet":{"path":"/","port":"http"},"initialDelaySeconds":3,"periodSeconds":10}` | Readiness probe of the frontend |
| frontend.replicaCount | int | `1` | Number of replicas |
| frontend.resources | object | `{"limits":{"cpu":"150m","memory":"128Mi"},"requests":{"cpu":"50m","memory":"128Mi"}}` | Resource requests and limits of the frontend (TRG 5.04) |
| frontend.securityContext | object | `{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]},"readOnlyRootFilesystem":true,"runAsGroup":101,"runAsNonRoot":true,"runAsUser":101}` | Security context of the frontend container (TRG 4.03, TRG 4.07) |
| frontend.service.port | int | `8080` | Service port |
| frontend.service.type | string | `"ClusterIP"` | Service type |
| frontend.tolerations | list | `[]` | Tolerations of the frontend pods |
| fullnameOverride | string | `""` | Overrides the full name of the release |
| imagePullSecrets | list | `[]` | Image pull secrets for private registries, e.g. `[{name: my-registry-secret}]` |
| nameOverride | string | `""` | Overrides the chart name |
| serviceAccount.annotations | object | `{}` | Annotations for the service account |
| serviceAccount.automountServiceAccountToken | bool | `false` | Whether the token of the service account is mounted into the pods (the components do not call the Kubernetes API) |
| serviceAccount.create | bool | `true` | Whether a service account is created |
| serviceAccount.name | string | `""` | Name of the service account; generated from the full name if empty |
| tests.image | object | `{"pullPolicy":"IfNotPresent","repository":"curlimages/curl","tag":"8.11.1"}` | Image used by `helm test` (TRG 5.09) |

----------------------------------------------
Autogenerated from chart metadata using [helm-docs](https://github.com/norwoodj/helm-docs). Regenerate with
`helm-docs --chart-search-root charts --template-files README.md.gotmpl` after changing `values.yaml`.

## NOTICE

This work is licensed under the [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/legalcode).

- SPDX-License-Identifier: CC-BY-4.0
- SPDX-FileCopyrightText: 2026 Contributors to the Eclipse Foundation
- Source URL: https://github.com/eclipse-tractusx/dataspace-mgm-service/tree/main/charts/dataspace-mgm
