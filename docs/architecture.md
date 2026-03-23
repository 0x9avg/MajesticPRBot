# Архитектура PRMajesticBot

Этот документ отвечает на три вопроса:

- из каких runtime-компонентов состоит система;
- кто владеет состоянием;
- как сервисы общаются между собой.

Этот документ не должен дублировать:

- команды локального запуска из `local-development.md`;
- production deploy playbook из `production-deployment.md`;
- endpoint catalog из `api-reference.md`;
- прикладные пользовательские сценарии из `domain-flows.md`.

## Общая картина

Система состоит из пяти прикладных runtime-сервисов и двух инфраструктурных зависимостей:

| Сервис | Стек | Назначение |
| --- | --- | --- |
| `web` | React 19, Vite, Tailwind | Панель управления и рабочие интерфейсы |
| `api` | FastAPI, aiomysql | Центральный API, бизнес-логика, auth, audit, schema bootstrap |
| `sanctions_worker` | Python | Ночной и ручной процессинг санкционных batch/job операций |
| `discord_bot` | Disnake | Discord UI, slash/button interactions, уведомления, control panels |
| `twitch_bot` | TwitchIO | Twitch EventSub, синхронизация live-статусов, верификация стримеров |
| `mysql` | MySQL 8.4 | Основное хранилище |
| `rabbitmq` | RabbitMQ 3.13 | Брокер интеграционных событий и фоновых команд |

## Кто за что отвечает

### API

- Поднимает пул БД и проверяет/мигрирует схему на старте.
- Поднимает RabbitMQ publisher и outbox relay.
- Хранит бизнес-правила для:
  - streamers/spec/events;
  - auth и session rotation;
  - returns/complaints/removals;
  - sanctions и assistant weekly.
- Хранит RBAC-матрицу и service principal scopes.

### sanctions_worker

- Отдельный процесс, использующий ту же базу данных.
- Слушает RabbitMQ routing key `sanction.operation.issue_now`.
- Выполняет ночной процессинг queued sanction batches.
- Не заменяет API и не встраивается в него как background task.

### Discord Bot

- Не хранит доменное состояние.
- Делает HTTP-запросы в API и рендерит Discord UI.
- Проверяет наличие пользователя в assistant-модели и кеширует permission map.
- Получает broker events для уведомлений и live-обновлений.

### Twitch Bot

- Является источником внешних live-событий Twitch.
- Не работает с MySQL напрямую.
- Получает стримеров через API, синхронизирует статусы и подписки EventSub.
- Пишет изменения обратно только через API.

### Web

- Использует API как единственный backend.
- Хранит access token только в памяти.
- Использует refresh token через HttpOnly cookie.
- Делает silent refresh и обрабатывает maintenance/login/session сценарии на клиенте.

## Ownership состояния

| Область | Источник правды |
| --- | --- |
| Пользователи, роли, permissions | API + MySQL |
| Стримеры и их persistent metadata | API + MySQL |
| Текущий live status Twitch | Twitch Bot -> API -> MySQL |
| Активные spec-сессии | API + MySQL (`spec_sessions`) |
| Event workflow и spec requests | API + MySQL |
| Returns / complaints / removals | API + MySQL |
| Sanctions / weekly review | API + MySQL + `sanctions_worker` |
| Discord messages, persistent views, control panel UI | Discord Bot |

## Каналы взаимодействия

### HTTP

- `web -> api`: вся панель управления.
- `discord_bot -> api`: команды, UI, guild settings, monitoring, event/spec действия.
- `twitch_bot -> api`: чтение стримеров, запись live-state, unclaim по событиям.

### RabbitMQ

- `api -> rabbitmq`: интеграционные события через outbox.
- `twitch_bot <- rabbitmq`: `streamer.verify`, `streamer.added`, `streamer.updated`, `streamer.removed`, `service.twitch.sync`.
- `discord_bot <- rabbitmq`: media/spec/event/guild related events для нотификаций и live UI.
- `sanctions_worker <- rabbitmq`: `sanction.operation.issue_now`.

## Важные архитектурные паттерны

### Outbox

- API сначала записывает событие в БД, затем relay публикует его в RabbitMQ.
- Это снижает риск потерять событие при проблемах с брокером.
- Если брокер временно недоступен, outbox остаётся в pending/failed состоянии и повторяет доставку позже.

### Active assignment model

- Привязка PR к стримеру или событию хранится через активные `spec_sessions`, а не через отдельную “таблицу закреплений”.
- Это делает историю и текущее состояние частью одной модели.

### Heartbeats и service registry

- Боты шлют heartbeat в API через `/api/services/heartbeat`.
- API строит runtime snapshot через `/api/services/overview`.
- Registry хранится в памяти процесса API, поэтому после рестарта API сервисы временно выглядят offline/stale до следующего heartbeat.

## Данные и SQL слой

API использует фасад `Database`, собранный из доменных mixin-ов. Это один из ключевых архитектурных выборов проекта:

- маршруты в основном оркестрируют auth/permissions/HTTP envelopes;
- большая часть бизнес-логики находится в `services/api/db/*`;
- сложные read-модели и агрегации реализованы через SQL и DB views.

Ключевые persistent сущности:

- `streamers`
- `settings`
- `assistants`
- `spec_sessions`
- `events`
- `event_participants`
- `web_auth`
- `sessions`
- `auth_logs`
- `role_permissions`
- `service_principals`
- `admin_logs`
- `game_servers`
- `punishment_returns`
- `complaints`
- `punishment_removals`
- санкционные таблицы и weekly review таблицы

Ключевые views, используемые системой:

- `active_assignments_v`
- `spec_session_day_slices`
- `daily_stats`
- `assistant_day_spec_totals`
- `sanction_balances`

## Порядок старта

### В production stack

1. `mysql`
2. `rabbitmq`
3. `api`
4. `sanctions_worker`
5. `discord_bot`
6. `twitch_bot`
7. `web`

### При ручном запуске

Рекомендуемый порядок тот же. API можно запустить без RabbitMQ для части сценариев, но тогда не будет полноценного real-time контура, outbox доставки и сервисных команд через broker.

## Где искать детали дальше

- Локальная разработка: [local-development.md](./local-development.md)
- Production deploy: [production-deployment.md](./production-deployment.md)
- Прикладные сценарии: [domain-flows.md](./domain-flows.md)
- API reference: [api-reference.md](./api-reference.md)
