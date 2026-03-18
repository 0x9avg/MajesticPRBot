# API Endpoints
Base URL: `/api`

## Auth
| Method | Endpoint | Description |
|---|---|---|
| POST | `/auth/login` | Login and obtain refresh/access tokens |
| POST | `/auth/logout` | Logout current session |
| POST | `/auth/refresh` | Rotate refresh cookie and issue a new access token |
| GET | `/auth/me` | Current authenticated principal |

## Assistants
| Method | Endpoint | Description |
|---|---|---|
| GET | `/assistants` | List assistants with computed totals from spec + sanction ledger |
| POST | `/assistants` | Create or update assistant profile |
| GET | `/assistants/{pr_id}` | Assistant profile and computed balances |
| DELETE | `/assistants/{pr_id}` | Delete assistant |
| PUT | `/assistants/{pr_id}/assign` | Compatibility assignment helper |
| GET | `/assistants/{pr_id}/logs` | Assistant activity log |
| GET | `/assistants/{pr_id}/sessions` | Detailed spec sessions |
| GET | `/assistants/{pr_id}/capabilities` | Role capabilities |
| POST | `/assistants/{pr_id}/session` | Create manual spec session |
| PATCH | `/assistants/{pr_id}/sessions/{session_id}` | Patch spec session |
| DELETE | `/assistants/{pr_id}/sessions/{session_id}` | Soft-delete spec session |
| GET | `/assistants/{pr_id}/day-status?date=YYYY-MM-DD` | Day metrics, immunities, streak state |
| GET | `/assistants/{pr_id}/sanctions/summary?date=YYYY-MM-DD` | Active sanctions snapshot on date |
| GET | `/assistants/{pr_id}/sanctions/active` | Active sanctions with workoff items and progress |

## Day Adjustments
| Method | Endpoint | Description |
|---|---|---|
| POST | `/assistant-day-points` | Upsert one day-point delta per assistant/day |
| PUT | `/assistant-day-mchat` | Upsert one mchat total per assistant/day |

## Sanctions
| Method | Endpoint | Description |
|---|---|---|
| POST | `/assistant-sanctions` | Issue manual sanction for current MSK day with optional `workoff_items[]` |
| POST | `/assistant-sanctions/{id}/reliefs` | Add partial/full relief to sanction |
| POST | `/assistant-sanctions/{id}/replace` | Replace sanction through relief + re-issue |
| GET | `/sanctions/{id}/workoff-progress` | Workoff progress for sanction |

## Sanction Operations
| Method | Endpoint | Description |
|---|---|---|
| GET | `/sanction-operations` | List sanction operations (cancelled hidden by default) |
| POST | `/sanction-operations` | Create sanction operation for current MSK day and place it into issuance queue |
| GET | `/sanction-operations/{id}` | Operation detail with members and issue state |
| PATCH | `/sanction-operations/{id}` | Edit queued operation metadata, workoff items or explicit members |
| POST | `/sanction-operations/{id}/members` | Add assistant into explicit operation list |
| DELETE | `/sanction-operations/{id}/members/{assistant_id}` | Remove assistant from explicit operation list |
| POST | `/sanction-operations/{id}/issue-now` | Send async command to worker and issue operation immediately without immunity checks |
| POST | `/sanction-operations/{id}/cancel` | Cancel operation before processing |

## Monthly Sanction Settings
| Method | Endpoint | Description |
|---|---|---|
| GET | `/sanction-settings/{month_start}` | Get monthly immunity/default-relief/workoff settings |
| PUT | `/sanction-settings/{month_start}` | Update monthly settings |
| GET | `/sanction-settings/{month_start}/check-rules` | Get check escalation rules |
| PUT | `/sanction-settings/{month_start}/check-rules` | Replace check escalation rules |

## Streamers
| Method | Endpoint | Description |
|---|---|---|
| GET | `/streamers` | List streamers. Current-stream overrides are exposed only as `current_stream_priority_override` and `current_stream_pr_slots_override` |
| POST | `/streamers` | Add streamer |
| GET | `/streamers/{twitch_id}` | Get streamer details |
| PATCH | `/streamers/{twitch_id}` | Update streamer. Accepts only `current_stream_priority_override` and `current_stream_pr_slots_override` for per-stream overrides |
| DELETE | `/streamers/{twitch_id}` | Delete streamer |
| PATCH | `/streamers/{twitch_id}/status` | Update online/game status |
| POST | `/streamers/sync_status` | Bulk sync streamer statuses |

## Spec
| Method | Endpoint | Description |
|---|---|---|
| POST | `/spec/claim` | Claim streamer slot |
| POST | `/spec/unclaim` | Unclaim streamer slot |
| GET | `/spec/sessions/{pr_id}` | Recent self sessions |
| GET | `/spec/by-pr/{pr_id}` | Current assignment for PR |

## Events / Guild / Monitoring / Returns
These sections remain active. Event participant identity is canonicalized as `pr_id` across event lists, `/events/{id}/participants`, `/events/scheduled`, join/leave responses, and end-event payloads. See route files under `services/api/routes/`.

## Queue / Worker Contract
- `sanction_operations` are created during the day already in `queued` status and keep an explicit final member list.
- `live_without_active_session` is used only as a seed mode when the batch list is first generated.
- `POST /sanction-operations/{id}/issue-now` publishes a RabbitMQ task; API does not execute issuance synchronously.
- `issue-now` ignores immunities and issues sanctions to all members still present in the operation.
- After `00:00` MSK the worker processes all `queued` operations for `operation_date = yesterday`.
- Immunity is evaluated only by `spec_hours_on_day`.
- Night order:
  1. queued operation issuance
  2. check-rule escalation
  3. default auto-relief for sanctions active before the run
- Freshly-issued nightly sanctions do not participate in same-night auto-relief.
- Workoff is stored as `workoff_items[]` with `metric`, `multiplier`, `period_start`, `period_end` and fixed target amounts on issued sanctions.

## Deprecated Legacy Paths
- `/assistants/{pr_id}/sanctions`
- `/assistants/{pr_id}/warnings`
- `/assistants/{pr_id}/points/adjust`
- old `/assistants/{pr_id}/daily-stats` and reset-style contracts

These remain legacy-only and should not be used by new clients.
