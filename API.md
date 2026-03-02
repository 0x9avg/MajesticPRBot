# API Endpoints
Base URL: `/api`

## Authentication (`/auth`)
| Method | Endpoint | Description |
|---|---|---|
| POST | `/auth/login` | Login and obtain refresh/access tokens (access token includes `sid`) |
| POST | `/auth/logout` | Logout |
| GET | `/auth/me` | Get current authenticated user info |

## Admin (`/admin`)
| Method | Endpoint | Description |
|---|---|---|
| POST | `/admin/users` | Create web user + assistant profile (requires `can_register_users`, role hierarchy enforced) |

## Assistants (`/assistants`)
| Method | Endpoint | Description |
|---|---|---|
| GET | `/assistants` | List all assistants |
| POST | `/assistants` | Register a new assistant |
| GET | `/assistants/{pr_id}` | Get assistant details |
| DELETE | `/assistants/{pr_id}` | Remove an assistant |
| PUT | `/assistants/{pr_id}/assign` | Update assistant assignment (Manual) |
| GET | `/assistants/{pr_id}/logs` | Get logs for an assistant |
| GET | `/assistants/{pr_id}/capabilities` | Get assistant capabilities |
| POST | `/assistants/{pr_id}/reset` | Reset assistant stats/state |
| PUT | `/assistants/{pr_id}/daily-stats` | Update daily statistics |
| POST | `/assistants/{pr_id}/session` | Manage assistant session |

## Spec System (`/spec`)
| Method | Endpoint | Description |
|---|---|---|
| POST | `/spec/claim` | Claim a streamer (Start spec) |
| POST | `/spec/unclaim` | Unclaim a streamer (End spec) |
| GET | `/spec/sessions/{pr_id}` | Get recent spec sessions for a PR |
| GET | `/spec/by-pr/{pr_id}` | Get current streamer assigned to a PR |

## Monitoring (`/monitoring`)
| Method | Endpoint | Description |
|---|---|---|
| GET | `/monitoring/status` | Get full monitoring dashboard data |
| POST | `/monitoring/refresh` | Trigger dashboard refresh |

## Streamers (`/streamers`)
| Method | Endpoint | Description |
|---|---|---|
| GET | `/streamers` | List all streamers |
| POST | `/streamers` | Add a new streamer |
| GET | `/streamers/{twitch_id}` | Get streamer details |
| PATCH | `/streamers/{twitch_id}` | Update streamer details |
| DELETE | `/streamers/{twitch_id}` | Delete a streamer |
| PATCH | `/streamers/{twitch_id}/status` | Update streamer status (Online/Game/etc) |
| POST | `/streamers/sync_status` | Batch sync streamer statuses |

## Events (`/events`)
| Method | Endpoint | Description |
|---|---|---|
| GET | `/events/active` | Get active events |
| GET | `/events/scheduled` | Get scheduled events |
| POST | `/events` | Create a new event |
| GET | `/events/{event_id}` | Get event details |
| GET | `/events/{event_id}/participants` | Get event participants |
| POST | `/events/{event_id}/join` | Join an event |
| POST | `/events/{event_id}/leave` | Leave an event |
| POST | `/events/{event_id}/end` | End an event |
| PATCH | `/events/{event_id}/notification-sent` | Mark notification as sent |
| PATCH | `/events/{event_id}/message` | Update event message ID |
| GET | `/events/user/{user_id}/active` | Get active event participation for a user |

## Guild Settings (`/guild`)
| Method | Endpoint | Description |
|---|---|---|
| GET | `/guild` | Get guild general settings |
| GET | `/guild/settings` | Get specific settings |
| PATCH | `/guild/settings` | Update settings |
| GET | `/guild/templates` | Get notification templates |
| PATCH | `/guild/templates` | Update notification templates |
| GET | `/guild/templates/{event_type}` | Get specific template |
| GET | `/guild/rates` | Get payment/salary rates |
| PATCH | `/guild/rates` | Update rates |

## Notifications (`/notifications`)
| Method | Endpoint | Description |
|---|---|---|
| GET | `/notifications/channel` | Get configured notification channel ID |
| GET | `/notifications/render/{event_type}` | Render a notification message and component |

## Stats (`/stats`)
| Method | Endpoint | Description |
|---|---|---|
| GET | `/stats/dashboard` | Get high-level dashboard statistics |

## Notes
- Access token now contains `sid` (session ID). Tokens without `sid` are rejected and require relogin.
- `/auth/logout` revokes user sessions, so previously issued access tokens become invalid.
- Active sessions count for clients should be read from `/stats/dashboard` field `assigned_pr_count`.
- `POST /admin/users` authorization rules:
  - `403`: current user lacks `can_register_users`.
  - `403`: target role is disallowed by role hierarchy.
  - `400`: invalid role value or duplicates (`username`, `discord_id` in `web_auth` or `assistants`).
  - `500`: internal creation error (generic message without DB internals).
