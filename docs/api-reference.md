# API reference

Этот документ фиксирует текущие HTTP-контракты API на уровне production-oriented справочника.

Его задача:

- быстро показать route groups;
- зафиксировать типы авторизации;
- объяснить общий shape ответов.

Он не заменяет Pydantic schemas и не пересказывает бизнес-сценарии. За сценарии отвечает `domain-flows.md`.

## Базовые правила

### Base path

Все прикладные ручки агрегируются под префиксом:

```text
/api
```

Отдельно на верхнем уровне API публикует:

- `GET /api/health`
- `GET /api/health/ready`

### Типы авторизации

В проекте есть два основных режима авторизации.

#### User JWT

Используется для web и user-driven административных действий:

- access token передается в `Authorization: Bearer <token>`;
- refresh token живет в HttpOnly cookie `refresh_token`;
- права определяются permission matrix и ролью пользователя.

#### Service bearer token

Используется сервисами `discord_bot` и `twitch_bot`:

- тот же `Authorization: Bearer <token>`;
- токен сопоставляется с service principal из `SERVICE_TOKENS`;
- права определяются scopes сервисного principal.

### Формат ответов

В проекте есть два семейства response shape:

- raw JSON для части health/auth endpoints;
- envelope-ответы для большинства прикладных ручек.

Типичный envelope выглядит так:

```json
{
  "status": "success",
  "data": {},
  "message": "Human readable message",
  "code": "OPTIONAL_CODE",
  "trace_id": "uuid"
}
```

## Health и service operations

### Public/operational

| Method | Path | Назначение |
| --- | --- | --- |
| `GET` | `/api/health` | Liveness API |
| `GET` | `/api/health/ready` | Readiness API с DB/broker diagnostics |

### Service-aware

| Method | Path | Кто обычно использует |
| --- | --- | --- |
| `POST` | `/api/services/heartbeat` | `discord_bot`, `twitch_bot` |
| `GET` | `/api/services/overview` | Discord admin UI, operators |
| `POST` | `/api/services/twitch/sync` | Ops/admin, service flows |

Примечания:

- `heartbeat` рассчитан на service principal;
- `overview` требует permission `monitoring.view`;
- `twitch/sync` публикует broker event, а не выполняет sync внутри API.

## Authentication

| Method | Path | Назначение |
| --- | --- | --- |
| `POST` | `/api/auth/login` | Логин, установка refresh cookie, возврат access token |
| `POST` | `/api/auth/refresh` | Rotation refresh token family |
| `POST` | `/api/auth/logout/current` | Logout текущей сессии |
| `POST` | `/api/auth/logout` | Legacy logout всех сессий |
| `GET` | `/api/auth/me` | Текущий пользователь и permissions |
| `GET` | `/api/auth/sessions` | Список активных сессий |
| `POST` | `/api/auth/sessions/{sid}/revoke` | Отзыв конкретной сессии |

Важные коды 401/503 для клиента:

- `TOKEN_EXPIRED`
- `TOKEN_INVALID`
- `SESSION_EXPIRED`
- `SESSION_REVOKED`
- `REFRESH_REUSE_DETECTED`
- `SITE_MAINTENANCE`

## Streamers

| Method | Path | Назначение |
| --- | --- | --- |
| `GET` | `/api/streamers` | Список стримеров |
| `GET` | `/api/streamers/{twitch_id}` | Карточка стримера |
| `POST` | `/api/streamers` | Создание стримера: `twitch_url` mode или full mode |
| `PATCH` | `/api/streamers/{twitch_id}` | Обновление метаданных стримера |
| `DELETE` | `/api/streamers/{twitch_id}` | Удаление стримера |
| `PATCH` | `/api/streamers/{twitch_id}/status` | Обновление live-state |
| `POST` | `/api/streamers/sync_status` | Массовая синхронизация статусов |

Практически:

- user/UI чаще использует URL mode;
- `twitch_bot` использует full mode и status updates;
- изменения стримеров активно завязаны на outbox и broker events.

## Assistants и runtime-сессии

### Assistants

| Method | Path | Назначение |
| --- | --- | --- |
| `GET` | `/api/assistants` | Список ассистентов |
| `GET` | `/api/assistants/{pr_id}` | Карточка ассистента |
| `PUT` | `/api/assistants/{pr_id}/assign` | Legacy/manual assign сценарий |
| `GET` | `/api/assistants/{pr_id}/logs` | Действия по ассистенту |
| `GET` | `/api/assistants/{pr_id}/sessions` | История сессий |
| `GET` | `/api/assistants/{pr_id}/capabilities` | Capability model для UI |
| `GET` | `/api/assistants/session-targets` | Доступные runtime targets |
| `POST` | `/api/assistants/{pr_id}/session` | Создание manual session |
| `PATCH` | `/api/assistants/{pr_id}/sessions/{session_id}` | Изменение session |
| `DELETE` | `/api/assistants/{pr_id}/sessions/{session_id}` | Удаление session |

### Spec

| Method | Path | Назначение |
| --- | --- | --- |
| `POST` | `/api/spec/claim` | Закрепить текущего пользователя |
| `POST` | `/api/spec/claim/{pr_id}` | Закрепить конкретный PR |
| `POST` | `/api/spec/unclaim` | Снять свое закрепление |
| `POST` | `/api/spec/unclaim/{pr_id}` | Снять закрепление конкретного PR |
| `GET` | `/api/spec/sessions/{pr_id}` | История spec sessions по PR |
| `GET` | `/api/spec/by-pr/{pr_id}` | Текущие назначения по PR |
| `GET` | `/api/spec/claimable` | Доступные targets для claim |
| `GET` | `/api/spec/claimable/{pr_id}` | Claimable targets для конкретного PR |

## Monitoring, notifications, stats, logs

| Method | Path | Назначение |
| --- | --- | --- |
| `GET` | `/api/monitoring/status` | Готовый monitoring view-model |
| `GET` | `/api/notifications/render/{event_type}` | Рендер шаблонов уведомлений |
| `GET` | `/api/stats/dashboard` | Dashboard агрегаты |
| `GET` | `/api/logs/admin` | Админские логи |
| `GET` | `/api/logs/assistant-actions/filters` | Фильтры для assistant action logs |
| `GET` | `/api/logs/pr-actions` | Логи действий по PR |

## Guild и game servers

### Guild settings

| Method | Path | Назначение |
| --- | --- | --- |
| `GET` | `/api/guild` | Сводка guild-конфига |
| `PUT` | `/api/guild/game-servers` | Замена списка игровых серверов в guild context |
| `GET` | `/api/guild/settings` | Guild settings snapshot |
| `PATCH` | `/api/guild/settings` | Обновление guild settings |
| `GET` | `/api/guild/templates` | Список notification templates |
| `PATCH` | `/api/guild/templates` | Обновление templates |
| `GET` | `/api/guild/templates/{event_type}` | Конкретный template |
| `GET` | `/api/guild/rates` | Текущие rates |
| `PATCH` | `/api/guild/rates` | Обновление rates |

### Public catalog

| Method | Path | Назначение |
| --- | --- | --- |
| `GET` | `/api/game-servers` | Каталог игровых серверов |

## Events

| Method | Path | Назначение |
| --- | --- | --- |
| `POST` | `/api/events` | Создание события |
| `GET` | `/api/events` | Все события |
| `GET` | `/api/events/active` | Активные события |
| `GET` | `/api/events/scheduled` | События, требующие runtime/start notification |
| `POST` | `/api/events/spec-request` | Создание spec request |
| `GET` | `/api/events/pending` | Pending spec requests |
| `PATCH` | `/api/events/{event_id}/pending` | Обновление pending spec request |
| `POST` | `/api/events/{event_id}/approve` | Approve spec request |
| `POST` | `/api/events/{event_id}/reject` | Reject spec request |
| `GET` | `/api/events/{event_id}` | Детали события |
| `GET` | `/api/events/{event_id}/participants` | Участники |
| `POST` | `/api/events/{event_id}/join` | Self join |
| `POST` | `/api/events/{event_id}/join/{pr_id}` | Join для конкретного PR |
| `POST` | `/api/events/{event_id}/leave` | Self leave |
| `POST` | `/api/events/{event_id}/leave/{pr_id}` | Leave для конкретного PR |
| `POST` | `/api/events/{event_id}/start` | Перевод события в runtime |
| `POST` | `/api/events/{event_id}/end` | Завершение события |
| `PATCH` | `/api/events/{event_id}` | Обновление данных события |
| `PATCH` | `/api/events/{event_id}/notification-sent` | Отметка отправки уведомления |

## Returns

| Method | Path | Назначение |
| --- | --- | --- |
| `POST` | `/api/returns` | Создание возврата |
| `GET` | `/api/returns/queue` | Очередь активных возвратов |
| `GET` | `/api/returns/history` | История возвратов |
| `POST` | `/api/returns/{return_id}/claim` | Взять возврат в работу |
| `POST` | `/api/returns/{return_id}/complete` | Завершить возврат |
| `POST` | `/api/returns/{return_id}/release` | Освободить возврат |
| `PATCH` | `/api/returns/{return_id}` | Изменение возврата |
| `DELETE` | `/api/returns/{return_id}` | Удаление возврата |

## Complaints

| Method | Path | Назначение |
| --- | --- | --- |
| `POST` | `/api/complaints` | Создание жалобы |
| `GET` | `/api/complaints/queue` | Очередь media-жалоб |
| `GET` | `/api/complaints/history` | История жалоб |
| `GET` | `/api/complaints/{complaint_id}` | Детали жалобы |
| `PATCH` | `/api/complaints/{complaint_id}` | Обновление жалобы |
| `DELETE` | `/api/complaints/{complaint_id}` | Удаление жалобы |
| `DELETE` | `/api/complaints/{complaint_id}/punishments/{punishment_id}` | Удаление наказания из жалобы |
| `POST` | `/api/complaints/{complaint_id}/issue` | Выдача жалобы/наказаний |

## Removals

| Method | Path | Назначение |
| --- | --- | --- |
| `POST` | `/api/removals` | Создание снятия наказания |
| `GET` | `/api/removals/queue` | Очередь снятий |
| `GET` | `/api/removals/history` | История снятий |
| `GET` | `/api/removals/{removal_id}` | Детали снятия |
| `PATCH` | `/api/removals/{removal_id}` | Обновление снятия |
| `DELETE` | `/api/removals/{removal_id}` | Удаление снятия |
| `POST` | `/api/removals/{removal_id}/issue` | Выдача снятия |

## Sanctions

Обратите внимание: санкционные ручки не имеют общего `/sanctions` префикса. Это текущий runtime-контракт.

### Day adjustments и individual sanctions

| Method | Path | Назначение |
| --- | --- | --- |
| `POST` | `/api/assistant-day-points` | Корректировка дневных points |
| `PUT` | `/api/assistant-day-mchat` | Корректировка дневного mchat |
| `GET` | `/api/assistants/{pr_id}/day-status` | Дневной статус ассистента |
| `GET` | `/api/assistants/{pr_id}/sanctions/summary` | Сводка санкций |
| `GET` | `/api/assistants/{pr_id}/sanctions/active` | Активные санкции |
| `POST` | `/api/assistant-sanctions` | Ручная выдача санкции |
| `POST` | `/api/assistant-sanctions/{sanction_id}/reliefs` | Снятие/relief санкции |
| `POST` | `/api/assistant-sanctions/{sanction_id}/replace` | Замена санкции |
| `GET` | `/api/sanctions/{sanction_id}/workoff-progress` | Прогресс отработки |
| `POST` | `/api/sanctions/workoff-preview` | Предпросмотр отработки |

### Policy и operations

| Method | Path | Назначение |
| --- | --- | --- |
| `GET` | `/api/sanction-settings` | Текущая политика санкций |
| `PUT` | `/api/sanction-settings` | Сохранение политики |
| `GET` | `/api/sanction-settings/check-rules` | Правила check cycles |
| `PUT` | `/api/sanction-settings/check-rules` | Замена правил check cycles |
| `GET` | `/api/sanction-operations` | Список queued operations |
| `POST` | `/api/sanction-operations` | Создание queued operation |
| `GET` | `/api/sanction-operations/{operation_id}` | Детали operation |
| `PATCH` | `/api/sanction-operations/{operation_id}` | Обновление operation |
| `POST` | `/api/sanction-operations/{operation_id}/members` | Добавление участника |
| `DELETE` | `/api/sanction-operations/{operation_id}/members/{assistant_id}` | Удаление участника |
| `POST` | `/api/sanction-operations/{operation_id}/issue-now` | Публикация немедленной выдачи в worker |
| `POST` | `/api/sanction-operations/{operation_id}/cancel` | Отмена operation |

## Assistant weekly

| Method | Path | Назначение |
| --- | --- | --- |
| `GET` | `/api/assistant-weekly/current` | Weekly overview для сотрудника |
| `GET` | `/api/assistant-weekly/admin` | Admin review list |
| `GET` | `/api/assistant-weekly/admin/{assistant_id}` | Детали review по ассистенту |
| `PUT` | `/api/assistant-weekly/admin/{assistant_id}` | Сохранение weekly review |
| `PUT` | `/api/assistant-weekly/admin/{assistant_id}/payout-issue` | Обновление payout issue status |

Примечание:

- admin weekly ручки используют `week_start` как query parameter;
- по умолчанию логика ориентируется на текущую MSK-неделю.

## Admin, RBAC и site maintenance

### User administration

| Method | Path | Назначение |
| --- | --- | --- |
| `POST` | `/api/admin/users` | Создание пользователя и assistant profile |
| `PATCH` | `/api/admin/users/{discord_id}/role` | Смена роли |
| `POST` | `/api/admin/users/{discord_id}/deactivate` | Деактивация пользователя |

### RBAC

| Method | Path | Назначение |
| --- | --- | --- |
| `GET` | `/api/admin/rbac` | Snapshot permission matrix |
| `PUT` | `/api/admin/rbac` | Полная/частичная замена управляемой части matrix |

### Site maintenance

| Method | Path | Назначение |
| --- | --- | --- |
| `GET` | `/api/admin/site-maintenance` | Текущее состояние maintenance mode |
| `PATCH` | `/api/admin/site-maintenance` | Включение/выключение maintenance mode |

## Что стоит помнить интегратору

- `X-Trace-Id` можно передавать во входящем запросе и получать обратно в ответе.
- `services/overview` и большая часть прикладных ручек возвращают envelope, а не raw arrays/objects.
- Не все endpoint-группы имеют единый префикс; самый заметный пример — санкции.
- Часть сервисных сценариев работает асинхронно через outbox/RabbitMQ, поэтому `202 Accepted` или успешный HTTP-ответ не всегда означает, что downstream processing уже завершен.
