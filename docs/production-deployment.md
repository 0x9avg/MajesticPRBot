# Продакшен-развертывание

Этот документ описывает только production stack ровно в том виде, в котором он определён в `docker-compose.prod.yml`.

Он отвечает на вопросы:

- какие сервисы входят в стек;
- какие порты и сети используются;
- какие env-файлы и связи критичны;
- как выполнить первый запуск и bootstrap.

## Состав стека

| Сервис | Роль |
| --- | --- |
| `web` | Caddy + раздача frontend и reverse proxy на API |
| `api` | Центральный backend |
| `sanctions_worker` | Отдельный worker для санкционного контура |
| `discord_bot` | Discord runtime |
| `twitch_bot` | Twitch runtime |
| `rabbitmq` | Broker интеграционных событий |
| `mysql` | Основная база данных |

## Что публикуется наружу по текущему compose

| Сервис | Публикация |
| --- | --- |
| `web` | `80:80`, `443:443` |
| `rabbitmq` management | `127.0.0.1:15672:15672` |
| `mysql` | `3306:3306` |
| `api` | не публикуется, только `expose: 8000` |
| `discord_bot` | порты не публикуются |
| `twitch_bot` | порты не публикуются |
| `sanctions_worker` | порты не публикуются |

Важно: MySQL по текущему compose опубликован как `3306:3306` без bind на `127.0.0.1`. Это означает публикацию на интерфейсы хоста. Если это не соответствует вашей production-модели, меняйте compose или ограничивайте доступ на уровне инфраструктуры.

## Сети

- `public`: внешняя сеть для опубликованных портов и сервисов, которым нужен outbound internet access
- `backend`: внутренняя `internal: true` сеть

Текущая схема подключения:

- `web` подключён к `public` и `backend`
- `api` подключён только к `backend`
- `sanctions_worker` подключён только к `backend`
- `discord_bot` подключён к `public` и `backend`
- `twitch_bot` подключён к `public` и `backend`
- `rabbitmq` подключён только к `backend`
- `mysql` подключён только к `backend`

## Подготовка env-файлов

```bash
cp deploy/env/api.env.example deploy/env/api.env
cp deploy/env/discord_bot.env.example deploy/env/discord_bot.env
cp deploy/env/twitch_bot.env.example deploy/env/twitch_bot.env
cp deploy/env/mysql.env.example deploy/env/mysql.env
cp deploy/env/rabbitmq.env.example deploy/env/rabbitmq.env
cp deploy/env/web.env.example deploy/env/web.env
```

## Критичные env-связи

- `deploy/env/api.env:SERVICE_TOKENS` должен содержать `discord_service:<token>` и `twitch_service:<token>`.
- `deploy/env/discord_bot.env:SERVICE_TOKEN` должен совпадать с token `discord_service`.
- `deploy/env/twitch_bot.env:SERVICE_TOKEN` должен совпадать с token `twitch_service`.
- `deploy/env/api.env:WEB_PANEL_URL` должен совпадать с публичным адресом панели.
- `deploy/env/web.env:SITE_ADDRESS` должен описывать тот же адрес, который обслуживает Caddy.
- `deploy/env/api.env:COOKIE_SECURE=true` обязателен для production.
- `deploy/env/api.env:JWT_SECRET_KEY` должен быть длинным и уникальным.

## Startup behavior по текущему compose

`depends_on` в production stack настроен так:

- `web` ждёт healthy `api`
- `api` ждёт healthy `mysql` и healthy `rabbitmq`
- `discord_bot` ждёт healthy `api` и healthy `rabbitmq`
- `twitch_bot` ждёт healthy `api` и healthy `rabbitmq`
- `sanctions_worker` ждёт только healthy `mysql`

Важно: по коду `sanctions_worker` подключается к RabbitMQ сразу при старте. Это значит, что RabbitMQ для него остается фактической runtime-зависимостью, даже несмотря на отсутствие `depends_on` на broker в compose.

## Запуск

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

## Проверка после старта

```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f api
docker compose -f docker-compose.prod.yml logs -f sanctions_worker
docker compose -f docker-compose.prod.yml logs -f discord_bot
docker compose -f docker-compose.prod.yml logs -f twitch_bot
docker compose -f docker-compose.prod.yml logs -f web
```

Базовые runtime endpoints:

- `GET /api/health`
- `GET /api/health/ready`

## Первый bootstrap

Создание первого администратора:

```bash
docker compose -f docker-compose.prod.yml exec -it api \
  python scripts/create_admin_user.py \
  --username admin \
  --nickname Admin \
  --role developer \
  --discord-id 123456789012345678
```

Пароль безопаснее вводить интерактивно. Скрипт также умеет брать его из `--password` или env-переменной.

## Volumes

Текущие named volumes:

- `api_logs`
- `discord_logs`
- `twitch_logs`
- `twitch_state`
- `mysql_data`
- `rabbitmq_data`
- `caddy_data`
- `caddy_config`

Минимум для резервного копирования:

- `mysql_data`
- `rabbitmq_data`
- `twitch_state`
- `caddy_data`
- контейнерные логи, если они используются для аудита

## Reverse proxy и web

Текущий `deploy/Caddyfile`:

- раздаёт static web;
- проксирует `/api/*` на `api:8000`;
- добавляет security headers;
- использует `SITE_ADDRESS`.

## Production caveats

- `api/health/ready` считает готовность только при доступных DB и broker.
- `services/overview` зависит от in-memory heartbeat registry API; после рестарта API другие сервисы будут выглядеть offline или stale до следующего heartbeat.
- schema bootstrap выполняется API на старте; первый запуск нельзя прерывать без необходимости.
- `sanctions_worker` должен быть запущен всегда, если используется санкционный контур.
