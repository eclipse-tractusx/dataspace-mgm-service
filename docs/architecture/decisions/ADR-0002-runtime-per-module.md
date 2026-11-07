# ADR-0002: One runtime per module from a single image

**Status:** proposed (6 Nov 2026), proof of concept with C1-M2 and C3-M1
([docker-compose.poc.yml](../../../docker-compose.poc.yml)).
**Builds on:** [ADR-0001](ADR-0001-events-as-cloudevents.md) (event inbox), FRAMEWORK 1 and 4.7.

## Context

The service is a modular monolith: one process mounts every module under `/api/<module>`, modules call each
other in-process, and the event relay delivers in memory. FRAMEWORK 4.7 already lets a module be reached by URL,
and ADR-0001 added the event inbox for split-out modules. Two pieces were missing to run a module as its own
deployable unit: a way to start a process with only some modules, and a way for its events to reach the others.
Operators also want to scale, release and isolate modules (for example Notifications or Credentials) independently.

## Decision

1. **One image, many runtimes.** The container image does not change. `ENABLED_MODULES` (comma separated ids,
   `portal_common.runtime`) selects the modules a process serves; unset means all modules (the monolith, the
   default). `scaffold.registry` mounts only those, together with the shared controllers (`/api/v1/events/inbox`,
   `/health`). No second code base, no per-module build.
2. **Synchronous calls** use the existing address rule of FRAMEWORK 4.7: `MODULE_URLS` / `<MODULE>_URL` hold the
   Kubernetes service of each module; `portal_common.neighbours` calls it with the service token `svc-<module>`.
   An empty address keeps the built-in stand-in. Module code does not change.
3. **Events** published in a runtime are delivered locally as before and forwarded to the other runtimes
   (`EVENT_SINKS`, `portal_common.event_forwarder`) at `POST /api/v1/events/inbox` in CloudEvents structured mode
   with the token of the publishing module. Delivery runs on worker threads off the request path, retries with
   backoff (at least once), is bounded (oldest dropped and counted), and is idempotent because the inbox
   deduplicates by `source` and `id`. Events that arrive through the inbox are not forwarded again.
4. **Outgoing HTTP uses one pooled client** (`portal_common.http`), so calls between pods reuse connections.
5. **Edge.** One gateway or ingress routes `/api/<module>` to the service of that module; the UI keeps one base
   address. The Helm chart renders one Deployment and Service per runtime from a list in `values.yaml`.
6. **Rules stay.** Modules still import only `interface.py` of neighbours; the call convention, Problem Details and
   tokens do not depend on where a module runs. A team folder never contains deployment code.

## Alternatives

| Option | Why not |
|---|---|
| One image per module | Many pipelines, base layers and Eclipse Dash runs for the same dependencies; no benefit before modules differ in dependencies. |
| Controller per module as separate FastAPI projects | Duplicates settings, token and problem handling that `portal_common` owns; drifts from the spec. |
| Keep the monolith only | Cannot scale or release modules independently; a failure in one module stops all. |
| Broker (Kafka, NATS) for events now | Right next step for durability, but heavy for the first split. The CloudEvents format already fits a broker (ADR-0001). |
| Service mesh for service-to-service auth | Not needed: service tokens (FRAMEWORK 4.2) already authenticate each call. |

## Consequences

- Splitting a module out is configuration: a `runtimes` entry in the chart or a service in compose, no code change.
- Each runtime still needs the whole `spec/` and shared libraries in the image (small, read-only).
- **State:** modules keep state in memory unless they have a database (C3-M1 supports PostgreSQL). A split runtime
  with state needs its own database and one replica until then; stateless modules scale horizontally.
- **Event delivery is at least once, not durable.** A pod crash loses queued events. The transactional outbox with
  a broker or database is the follow-up; consumers already handle repeats by `id`.
- **Fan-out is to all sinks.** Every runtime posts every event to every sink; with many modules, subscriptions per
  event type (or a broker) reduce traffic.
- **Process Orchestration (C12-M1)** must run where it can reach every module by URL; as a runtime it is a normal
  module with `MODULE_URLS` for all others.
- Latency of a neighbour call changes from a function call to an HTTP call; the pooled client and keep-alive keep it
  low, and modules that call each other on every request are better kept in one runtime (several ids in
  `ENABLED_MODULES`).

## NOTICE

This work is licensed under the [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/legalcode).

- SPDX-License-Identifier: CC-BY-4.0
- SPDX-FileCopyrightText: 2026 Contributors to the Eclipse Foundation
- Source URL: https://github.com/eclipse-tractusx/dataspace-mgm-services/blob/main/docs/architecture/decisions/ADR-0002-runtime-per-module.md
