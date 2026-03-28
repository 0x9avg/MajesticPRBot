# PRMajesticBot

PRMajesticBot — микросервисная система для PR-команды Majestic RP. В проект входят web-панель, центральный API, Discord и Twitch боты, санкционный worker и инфраструктурный event-driven контур на MySQL и RabbitMQ.

## Что это за система

Проект закрывает несколько рабочих областей одной платформой:

- мониторинг и ведение Twitch-стримеров;
- spec-сессии и event workflows;
- web-auth и RBAC;
- workflows по возвратам, жалобам и снятиям;
- weekly review и санкционный контур.

Главный архитектурный принцип: источник правды находится в API и MySQL. Боты и web не владеют доменным состоянием, а работают через API и broker events.

## Состав системы

| Компонент | Назначение |
| --- | --- |
| `web` | React-панель управления |
| `api` | Центральный FastAPI backend, auth, бизнес-логика, schema bootstrap |
| `sanctions_worker` | Отдельный worker для queued/nightly санкций |
| `discord_bot` | Discord UI, команды, панели, уведомления |
| `twitch_bot` | Twitch EventSub, streamer verification, live-state sync |
| `mysql` | Основная база данных |
| `rabbitmq` | Broker для интеграционных событий и фоновых команд |

## Как читать документацию

Если вы впервые открыли проект:

1. Прочитайте [docs/architecture.md](docs/architecture.md), чтобы понять состав системы.
2. Затем откройте [docs/local-development.md](docs/local-development.md), если вам нужен локальный запуск.
3. После этого переходите к [docs/domain-flows.md](docs/domain-flows.md), чтобы понять реальные прикладные сценарии.
4. Для интеграции с API используйте [docs/api-reference.md](docs/api-reference.md).
5. Для production deploy и эксплуатации используйте [docs/production-deployment.md](docs/production-deployment.md) и [docs/operations.md](docs/operations.md).

## Карта документации

| Файл | Что в нем должно быть |
| --- | --- |
| [docs/architecture.md](docs/architecture.md) | Границы сервисов, ownership состояния, каналы взаимодействия, ключевые паттерны |
| [docs/local-development.md](docs/local-development.md) | Локальное окружение, `.env`, ручной запуск, dev workflow, тесты |
| [docs/production-deployment.md](docs/production-deployment.md) | Текущий production stack по `docker-compose.prod.yml`, порты, сети, volumes, bootstrap |
| [docs/domain-flows.md](docs/domain-flows.md) | Прикладные потоки по доменам: streamers, spec, events, auth, workflows, sanctions |
| [docs/api-reference.md](docs/api-reference.md) | HTTP endpoint catalog, auth-модели, response shapes |
| [docs/operations.md](docs/operations.md) | Health, readiness, heartbeats, tracing, логи и troubleshooting |

## Быстрый локальный старт

1. Создайте env-файлы для Docker-контура:

```bash
cp deploy/env/api.env.example deploy/env/api.env
cp deploy/env/discord_bot.env.example deploy/env/discord_bot.env
cp deploy/env/twitch_bot.env.example deploy/env/twitch_bot.env
cp deploy/env/mysql.env.example deploy/env/mysql.env
cp deploy/env/rabbitmq.env.example deploy/env/rabbitmq.env
cp deploy/env/web.env.example deploy/env/web.env
```

2. Создайте сервисные `.env` для ручного запуска:

- `services/api/.env`
- `services/discord_bot/.env`
- `services/twitch_bot/.env`

3. Поднимите инфраструктуру:

```bash
docker compose -f docker-compose.prod.yml up -d mysql rabbitmq
```

4. Запустите прикладные сервисы локально. Для полного контура нужны 5 процессов:

- `api`
- `sanctions_worker`
- `discord_bot`
- `twitch_bot`
- `web`

Подробные команды и минимальные dev-сценарии описаны в [docs/local-development.md](docs/local-development.md).

## Быстрый production старт

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

Перед этим обязательно подготовьте `deploy/env/*.env`. Точное описание stack behavior, сетей, портов, bootstrap и caveats находится в [docs/production-deployment.md](docs/production-deployment.md).

## Критичные связи конфигурации

- В API переменная `SERVICE_TOKENS` должна быть задана строго в формате `discord_service:<token>,twitch_service:<token>`.
- `discord_bot` должен использовать тот же token, который указан как `discord_service`.
- `twitch_bot` должен использовать тот же token, который указан как `twitch_service`.
- `WEB_PANEL_URL` в API и `SITE_ADDRESS` в web/Caddy должны описывать один и тот же публичный адрес панели.

## Health и логи

Базовые runtime точки:

- API liveness: `GET /api/health`
- API readiness: `GET /api/health/ready`
- Runtime overview: `GET /api/services/overview`

Быстрые команды:

```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f api
docker compose -f docker-compose.prod.yml logs -f sanctions_worker
docker compose -f docker-compose.prod.yml logs -f discord_bot
docker compose -f docker-compose.prod.yml logs -f twitch_bot
docker compose -f docker-compose.prod.yml logs -f web
```

Локально логи пишутся в каталог `logs/`. В контейнерах сервисы пишут в `/opt/prmajestic/logs`.

## Что важно знать заранее

- Схема БД создаётся и обновляется кодом API на старте.
- Отдельного Alembic-контура в проекте нет.
- `sanctions_worker` это самостоятельный runtime-процесс, а не background task внутри API.
- RabbitMQ нужен для полноценного event-driven контура, even если часть HTTP-функций может отвечать в деградированном manual-run режиме.
- Единый источник версии проекта — файл `VERSION`.

## Лицензия

Private / Proprietary.
