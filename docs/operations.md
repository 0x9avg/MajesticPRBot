# Эксплуатация и диагностика

Этот документ описывает только runtime-эксплуатацию:

- health/readiness;
- heartbeats;
- tracing;
- логи;
- типовые troubleshooting-сценарии.

Он не должен дублировать deployment steps из `production-deployment.md` и не должен объяснять бизнес-домены вместо `domain-flows.md`.

## Базовые health endpoints

### `GET /api/health`

Назначение:

- liveness check для API;
- быстрый ответ без тяжелой прикладной логики;
- используется container healthcheck.

Что возвращает:

- `status=alive`
- имя сервиса
- версия
- uptime
- `startup_complete`
- `checked_at`

### `GET /api/health/ready`

Назначение:

- readiness check;
- диагностика зависимостей.

Что реально проверяет сейчас:

- доступность MySQL;
- статус broker connection;
- завершение startup lifecycle API.

Важно: readiness считается `ready` только при доступных DB и RabbitMQ. Даже если API уже отвечает на HTTP, при потере broker этот endpoint будет показывать деградацию.

## Runtime overview

### `GET /api/services/overview`

Это главный operational snapshot прикладной части. В ответе есть:

- `api` runtime status;
- `services` heartbeat registry;
- `domain` counters/statistics.

Использование:

- Discord service panel;
- ручная диагностика проблем между сервисами;
- быстрый ответ на вопрос "видит ли API остальные runtime-компоненты".

### Как работает heartbeat registry

- heartbeat отправляют сервисы `discord_service` и `twitch_service`;
- API ожидает имена сервисов из `SERVICE_TOKENS`;
- heartbeat age старше 120 секунд помечается как `stale`;
- после рестарта API registry пустой до следующего heartbeat.

Практическое следствие:

- `offline` сразу после рестарта API не всегда означает падение сервиса;
- сначала проверьте `last_seen_at`, `heartbeat_age_seconds` и логи бота.

## Heartbeat behavior

Оба бота отправляют heartbeat примерно каждые 30 секунд.

`discord_bot` передает в details:

- `ready`
- `gateway_latency_ms`
- `guilds_connected`
- `target_guild_connected`
- `broker_connected`
- `uptime_seconds`

`twitch_bot` передает runtime status `online` или `syncing` в зависимости от текущего full sync.

## Tracing

API использует middleware с header `X-Trace-Id`.

Поведение:

- если клиент прислал `X-Trace-Id`, API его сохраняет;
- если нет, API генерирует новый UUID;
- `X-Trace-Id` возвращается в response headers;
- trace id также прокидывается в envelope responses и audit metadata.

Практический смысл:

- удобно связывать frontend error, API request, outbox event и admin/audit запись;
- при разборе инцидента trace id стоит собирать первым.

## Логи

### Где лежат логи при локальном запуске

Сервисы по умолчанию пишут в общий каталог:

- `logs/api.log`
- `logs/discord_bot.log`
- `logs/twitch_bot.log`

Это путь относительно корня репозитория, а не только папки сервиса.

### Где лежат логи в контейнерах

В production compose логи сервисов пробрасываются в named volumes и доступны в контейнерах по пути:

- `/opt/prmajestic/logs`

### Полезные команды

```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f api
docker compose -f docker-compose.prod.yml logs -f sanctions_worker
docker compose -f docker-compose.prod.yml logs -f discord_bot
docker compose -f docker-compose.prod.yml logs -f twitch_bot
docker compose -f docker-compose.prod.yml logs -f web
```

## Частые operational сценарии

### API отвечает на `/api/health`, но `/api/health/ready` не ready

Проверить:

- доступность MySQL;
- доступность RabbitMQ;
- логи `api` на startup errors;
- корректность `DB_*`, `RABBITMQ_*`, `SERVICE_TOKENS`.

Это штатный симптом, когда HTTP-процесс жив, но одна из зависимостей недоступна.

### `services/overview` показывает `discord_service` или `twitch_service` как `offline`

Проверить:

- действительно ли сервис запущен;
- совпадает ли `SERVICE_TOKEN` у бота с `SERVICE_TOKENS` в API;
- может ли бот достучаться до `POST /api/services/heartbeat`;
- не был ли недавно рестартован API.

### Сервис показывает `stale`

Это значит, что heartbeat был, но старше 120 секунд. Обычно причины такие:

- бот завис в event loop;
- проблемы сети между ботом и API;
- длительный reconnect/restart cycle;
- внезапное падение, после которого старый heartbeat еще сохраняется в registry.

### Web логин проходит, но пользователь "вылетает"

Проверить:

- `WEB_PANEL_URL` и cookie-конфигурацию API;
- `COOKIE_SECURE` и схему `http/https`;
- что refresh cookie реально устанавливается на `/api/auth`;
- не возникает ли `REFRESH_REUSE_DETECTED` или `SESSION_REVOKED`.

### `twitch_bot` не подхватывает новых стримеров

Проверить последовательно:

1. Создал ли API outbox event `streamer.verify`.
2. Доступен ли RabbitMQ.
3. Слушает ли `twitch_bot` broker consumer.
4. Может ли бот резолвить Twitch user ID и забирать Twitch API данные.
5. Удалось ли `twitch_bot` вызвать full-mode создание стримера в API.

Если нужно форсировать синхронизацию уже известных стримеров, используйте `POST /api/services/twitch/sync`.

### `sanction-operations/{id}/issue-now` принято, но выдача не произошла

Проверить:

- запущен ли `sanctions_worker`;
- доступен ли RabbitMQ;
- существует ли очередь `prmajesticbot.sanctions_worker`;
- не упирается ли worker в ошибки DB processing;
- не переведена ли операция уже из статуса `queued`.

Важно: `202 Accepted` от API означает только успешную постановку задачи в event-driven контур, а не завершенную обработку.

## RabbitMQ и degraded режим

Нужно различать два режима:

- ручной запуск из исходников;
- production stack из `docker-compose.prod.yml`.

При ручном запуске API умеет переживать временную недоступность RabbitMQ и ретраить соединение. При этом часть HTTP-функций может продолжать работать, но event-driven контур будет неполным.

В production compose RabbitMQ остается фактической обязательной зависимостью для runtime-контура, но не все сервисы ожидают его одинаково:

- `api` ожидает healthy broker;
- `discord_bot` и `twitch_bot` зависят от broker;
- `sanctions_worker` по `docker-compose.prod.yml` не имеет `depends_on` на RabbitMQ, но по коду подключается к брокеру сразу при старте.

Из этого следует вывод: `sanctions_worker` operationally тоже зависит от RabbitMQ, но compose не откладывает его запуск до готовности брокера.

## База данных и schema bootstrap

Схема БД создается и доводится кодом API на старте.

Operational implications:

- первый запуск API нельзя прерывать без необходимости;
- проблемы schema bootstrap проявляются в логах `api`, а не в отдельном migration tool;
- для новых окружений именно успешный старт API является сигналом, что базовая схема готова.

## What to check first при инциденте

Короткий порядок диагностики:

1. `docker compose ... ps`
2. `GET /api/health`
3. `GET /api/health/ready`
4. `GET /api/services/overview`
5. Логи `api`
6. Логи конкретного проблемного сервиса
7. Наличие и совпадение критичных env (`DB_*`, `RABBITMQ_*`, `SERVICE_TOKENS`, bot `SERVICE_TOKEN`)

Обычно этого достаточно, чтобы быстро понять, проблема в инфраструктуре, межсервисной авторизации, broker-доставке или в доменной логике конкретного workflow.
