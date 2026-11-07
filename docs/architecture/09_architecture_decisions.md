# 9. Architecture decisions

| Date | Decision | Reason |
|---|---|---|
| 6 Nov 2026 | **One runtime per module:** the same image, selected with `ENABLED_MODULES`, deployed as one pod per module behind path routing ([ADR-0002](decisions/ADR-0002-runtime-per-module.md)). | Scale, release and fail modules on their own without a second code base; the monolith stays the default. |
| 6 Nov 2026 | **Events as CloudEvents 1.0** and the event inbox `POST /api/v1/events/inbox` for split-out modules ([ADR-0001](decisions/ADR-0001-events-as-cloudevents.md), proposal OP-54). | A standard format for transport and tooling; envelope and content separated; a module only publishes its own events. |
| 28 Oct 2026 | **OSP 2.0:** every OSP runs its own portal installation, the CSP provides trust. PSP admission, delegation and sign-in services per PSP are dropped; CSP Connection (C3-M2) is new. | No single party should run the portal for all participants of a dataspace. |
| 26 Oct 2026 | Callbacks from external systems use one service account per system with `private_key_jwt`, a client secret only as a transition (OP-22). | Strong authentication of external systems. |
| – | Modular monolith in Python with FastAPI; modules call each other through their public interface in the same process. | Simple operation now, modules can be split out later without changing callers. |
| – | Flows as data in Process Orchestration; modules call each other directly only for queries. | Flows can change without changing the modules. |
| – | One database per module, events through an outbox. | Loose coupling, no shared data model. |
| – | Sign-in without passwords through the EBW-Connector as the only identity provider. | The Company IAM with one realm per company is removed. |

Decisions with a full record (context, alternatives, consequences) are in [decisions/](decisions/).

The open questions that concern several modules are tracked as OP-xx in `open-points.md` of the specification; the
provisional decisions of each module are listed in its own `open-points.md`.

## NOTICE

This work is licensed under the [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/legalcode).

- SPDX-License-Identifier: CC-BY-4.0
- SPDX-FileCopyrightText: 2026 Contributors to the Eclipse Foundation
- Source URL: https://github.com/eclipse-tractusx/dataspace-mgm-service/blob/main/docs/architecture/09_architecture_decisions.md
