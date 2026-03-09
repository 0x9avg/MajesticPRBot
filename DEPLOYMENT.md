# Production Deployment

Этот проект можно поднять как единый Docker Compose стек с контейнерами:

- `web` (Caddy + собранный React frontend)
- `api`
- `discord_bot`
- `twitch_bot`
- `rabbitmq`
- `mysql`

## 1. Подготовка сервера

Минимум:

- Docker Engine 24+
- Docker Compose plugin
- Открытые порты `80` и `443`
- Домен, указывающий на сервер, если нужен HTTPS через встроенный Caddy

## 2. Подготовка env-файлов

Скопируйте шаблоны:

```bash
cp deploy/env/api.env.example deploy/env/api.env
cp deploy/env/discord_bot.env.example deploy/env/discord_bot.env
cp deploy/env/twitch_bot.env.example deploy/env/twitch_bot.env
cp deploy/env/mysql.env.example deploy/env/mysql.env
cp deploy/env/rabbitmq.env.example deploy/env/rabbitmq.env
cp deploy/env/web.env.example deploy/env/web.env
```

Секреты удобно генерировать так:

```bash
openssl rand -hex 32
openssl rand -base64 48 | tr -d '\n'
```

## 3. Критичные env-связи

- `deploy/env/api.env:SERVICE_TOKENS` должен содержать два разных токена:
  - `discord_service:<token>`
  - `twitch_service:<token>`
- `deploy/env/discord_bot.env:SERVICE_TOKEN` должен совпасть с токеном `discord_service`.
- `deploy/env/twitch_bot.env:SERVICE_TOKEN` должен совпасть с токеном `twitch_service`.
- `deploy/env/api.env:WEB_PANEL_URL` должен быть равен публичному адресу панели, например `https://panel.example.com`.
- `deploy/env/web.env:SITE_ADDRESS` для HTTPS должен быть доменом без схемы, например `panel.example.com`.
- `deploy/env/api.env:COOKIE_DOMAIN` безопаснее оставить пустым, если панель работает на одном домене.
- `deploy/env/twitch_bot.env:TWITCH_TOKENS_FILE` уже вынесен в volume и не должен указывать на временную директорию.
- `deploy/env/rabbitmq.env:RABBITMQ_ERLANG_COOKIE` тоже должен быть случайным и не совпадать с другими секретами.

## 4. Запуск

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

Проверка:

```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f api
docker compose -f docker-compose.prod.yml logs -f web
```

Примечание по сетям:

- `backend` помечена как `internal: true`, поэтому через неё сервисы общаются между собой, но не получают выход в интернет.
- `discord_bot` и `twitch_bot` дополнительно подключены к `public`, чтобы иметь исходящий доступ к `discord.com`, Twitch API и EventSub.
- Это не публикует порты ботов наружу. Внешний доступ по-прежнему открывается только через `ports`.

Полезные ручки API:

- `GET /api/health` — liveness, только факт что API-процесс поднят и отвечает
- `GET /api/health/ready` — readiness, показывает состояние БД и RabbitMQ

## 5. Первый bootstrap

После первого старта можно создать админа:

```bash
docker compose -f docker-compose.prod.yml exec -it api \
  python scripts/create_admin_user.py \
  --username admin \
  --nickname Admin \
  --role developer \
  --discord-id 123456789012345678
```

Пароль безопаснее вводить интерактивно:

- скрипт запросит его через `getpass`, без отображения на экране
- пароль больше не захардкожен в коде и не пишется в лог
- не передавайте пароль через `--password`, если не нужна автоматизация, потому что он может остаться в history/process list

## 6. Что опубликовано наружу

- `web`: `80/tcp`, `443/tcp`
- `rabbitmq` management UI: только `127.0.0.1:15672`
- `mysql`: только `127.0.0.1:3306` для доступа через SSH tunnel

MySQL, API и AMQP наружу не публикуются.

## 7. Подключение к MySQL извне

Рекомендуемый и уже настроенный вариант:

- MySQL опубликован только на `127.0.0.1:3306` сервера
- внешний доступ выполняется через SSH tunnel

Поднять туннель с локальной машины:

```bash
ssh -L 3306:127.0.0.1:3306 your_user@your_server
```

После этого можно подключаться локальным клиентом как будто база запущена у вас на машине:

- host: `127.0.0.1`
- port: `3306`
- database: `prmajesticbot`
- user: `prmajesticbot`
- password: значение `MYSQL_PASSWORD` из `deploy/env/mysql.env`

Подключение через CLI:

```bash
mysql -h 127.0.0.1 -P 3306 -u prmajesticbot -p prmajesticbot
```

Подключение из контейнера без туннеля:

```bash
docker compose -f docker-compose.prod.yml exec mysql \
  mysql -u prmajesticbot -p prmajesticbot
```

## 8. Рекомендации по безопасности

- Не используйте одинаковые значения для `JWT_SECRET_KEY`, паролей MySQL, RabbitMQ и service tokens.
- В production держите `COOKIE_SECURE=true`.
- Открывайте наружу только `80/443` и SSH.
- Не включайте `COOKIE_DOMAIN`, если у вас нет явной задачи шарить cookie между поддоменами.
- Храните `deploy/env/*.env` только на сервере или в секрет-хранилище, не в Git.
- Регулярно бэкапьте volumes: `mysql_data`, `rabbitmq_data`, `twitch_state`, `caddy_data`.

## 9. Частые проблемы

- `SITE_ADDRESS=:80` и `COOKIE_SECURE=true` несовместимы для обычного HTTP.
  Используйте это только для закрытого staging, либо дайте реальный домен и HTTPS.
- Если `WEB_PANEL_URL` не совпадает с публичным адресом панели, получите CORS/refresh-cookie проблемы.
- Если `RABBITMQ_VHOST` в API и ботах отличается от `RABBITMQ_DEFAULT_VHOST` у RabbitMQ, сервисы не подключатся.
- Если Twitch после рестарта заново переинициализирует подписки, проверьте volume `twitch_state` и путь `TWITCH_TOKENS_FILE`.
- Если Caddy не выпускает сертификат, проверьте DNS, открытые `80/443` и отсутствие другого reverse proxy на этих портах.
- Если `api` помечается как `unhealthy`, сначала смотрите `docker compose logs api`: чаще всего это не `/api/health`, а падение API на старте из-за env или MySQL.
