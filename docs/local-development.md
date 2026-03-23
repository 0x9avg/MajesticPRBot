# Локальная разработка

Этот документ описывает только локальную работу с проектом:

- какие `.env` нужны;
- как поднять инфраструктуру;
- какие процессы запускать вручную;
- какие команды использовать для тестов и быстрой диагностики.

Он не описывает production deploy. Для него используется `production-deployment.md`.

## Что понадобится

- Python 3.12+
- Node.js 20+
- Docker Engine + Docker Compose plugin
- Доступ к Discord/Twitch токенам, если нужен полный контур с ботами

## Какие `.env` используются

Проект использует два разных набора env-файлов:

| Где лежат | Для чего нужны |
| --- | --- |
| `services/api/.env`, `services/discord_bot/.env`, `services/twitch_bot/.env` | Ручной локальный запуск сервисов |
| `deploy/env/*.env` | Docker Compose production stack |

Если вы настраиваете проект с нуля:

1. Создайте `deploy/env/*.env` из `*.example`.
2. На основе этих же значений создайте сервисные `.env` в `services/*/`.

Минимальный набор файлов:

- `services/api/.env`
- `services/discord_bot/.env`
- `services/twitch_bot/.env`
- `deploy/env/api.env`
- `deploy/env/discord_bot.env`
- `deploy/env/twitch_bot.env`
- `deploy/env/mysql.env`
- `deploy/env/rabbitmq.env`
- `deploy/env/web.env`

## Критичные связи env

- `SERVICE_TOKENS` в API должен быть строго в формате:
  - `discord_service:<token>`
  - `twitch_service:<token>`
- `services/discord_bot/.env:SERVICE_TOKEN` должен совпадать с токеном `discord_service`.
- `services/twitch_bot/.env:SERVICE_TOKEN` должен совпадать с токеном `twitch_service`.
- Для production compose те же связи должны быть отражены в `deploy/env/*.env`.

## Рекомендуемый локальный режим

Лучший рабочий вариант для разработки:

1. Поднять инфраструктуру через Docker.
2. Запустить прикладные сервисы локально из исходников.

### Шаг 1. Поднять MySQL и RabbitMQ

```bash
docker compose -f docker-compose.prod.yml up -d mysql rabbitmq
```

Этот режим использует текущие `deploy/env/mysql.env` и `deploy/env/rabbitmq.env`.

### Шаг 2. Запустить API

```bash
cd services/api
pip install -r requirements.txt
python3 main.py
```

### Шаг 3. Запустить sanctions worker

```bash
cd services/api
python3 sanctions_worker.py
```

### Шаг 4. Запустить Discord Bot

```bash
cd services/discord_bot
pip install -r requirements.txt
python3 main.py
```

### Шаг 5. Запустить Twitch Bot

```bash
cd services/twitch_bot
pip install -r requirements.txt
python3 main.py
```

### Шаг 6. Запустить web

```bash
cd web
npm install
npm run dev
```

После поднятия инфраструктуры для полного локального контура потребуется 5 пользовательских процессов:

- `api`
- `sanctions_worker`
- `discord_bot`
- `twitch_bot`
- `web`

## Минимальный dev subset

Если вам не нужен полный live-контур, можно ограничиться:

- `mysql`
- `rabbitmq`
- `api`
- `web`

Или даже только:

- `mysql`
- `api`
- `web`

Но важно понимать последствия:

- без RabbitMQ не будет нормальной event-driven интеграции;
- без `discord_bot` не будет Discord UI и heartbeat этого сервиса;
- без `twitch_bot` не будет Twitch sync, streamer verification и live-state updates;
- без `sanctions_worker` не будет отдельного процессинга санкционных queued jobs.

## Что происходит при старте API

На первом успешном запуске API:

- валидирует env;
- валидирует production security policy, если `ENV=production`;
- поднимает пул соединений;
- создаёт/обновляет таблицы и SQL views;
- инициализирует built-in permissions и service principals;
- запускает outbox relay loop.

Это значит, что схема БД приводится к нужному состоянию именно кодом API.

## Тесты

### Backend

```bash
services/api/venv/bin/pytest services/api/tests -q
```

### Frontend

```bash
cd web
npm test -- --run
```

### Полезные дополнительные проверки

```bash
cd web
npm run build
npm run lint
```

## Базовая проверка после старта

- API liveness: `GET /api/health`
- API readiness: `GET /api/health/ready`
- Service overview: `GET /api/services/overview`
- Web UI: откройте `http://localhost:5173`

## Частые проблемы в локальной среде

### API не стартует

Проверить:

- `DB_*`
- `JWT_SECRET_KEY`
- `RABBITMQ_*`
- `SERVICE_TOKENS`

### Twitch bot не синхронизирует стримеров

Проверить:

- `TWITCH_CLIENT_ID`
- `TWITCH_CLIENT_SECRET`
- `TWITCH_BOT_ID`
- корректность `SERVICE_TOKEN`
- доступность RabbitMQ и API

### Discord bot запускается, но команды не работают

Проверить:

- `DISCORD_TOKEN`
- `GUILD_ID`
- наличие пользователя в assistants
- permission map роли через API

### Web логин не работает

Проверить:

- доступность `POST /api/auth/login`
- корректность `WEB_PANEL_URL`
- что API и web используют согласованную origin/cookie схему
