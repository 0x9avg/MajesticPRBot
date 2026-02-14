# PRMajesticBot

Интеграционный бот Discord и Twitch для мониторинга стримеров и управления PR-активностью (Majestic RP).

## 🎯 Возможности

- **Мониторинг стримов**: Отслеживание статуса (Online/Offline), смены категории (GTA 5 <-> Other) и заголовков.
- **Управление персоналом (PR)**:
  - Система ролей (Junior, Senior, Manager).
  - Учет рабочего времени (Spec Sessions).
  - Автоматический расчет баллов и статистика.
- **Ивенты**: Создание и управление событиями с отслеживанием участия.
- **Умные уведомления**: Гибкая настройка каналов для анонсов и отчетов.
- **Веб-панель**: Полноценный Dashboard для управления системой без команд Discord.

## 📋 Требования

- **Python 3.12+**: Бэкенд-сервисы (API, Bots).
- **Node.js 20+**: Фронтенд (React 19).
- **MySQL 8.0+ / MariaDB 10.5+**: Основная база данных.
- **RabbitMQ**: Брокер сообщений для событий.

## 🚀 Установка и Запуск

> [!WARNING]
> Проект использует микросервисную архитектуру. Все компоненты должны быть запущены одновременно.
> Автоматический лаунчер `start_project.bat` временно не поддерживается/требует доработки. Рекомендуется ручной запуск.

### 1. Подготовка
Клонируйте репозиторий и настройте переменные окружения для каждого сервиса, скопировав `example.env` в `.env`:
- `services/api/.env`
- `services/discord_bot/.env`
- `services/twitch_bot/.env`

### 2. Запуск Сервисов (Ручной режим)

Вам потребуется открыть 4 терминала.

**Терминал 1: API Service** (Ядро системы)
```bash
cd services/api
# Создание venv (рекомендуется)
python -m venv venv
source venv/bin/activate  # на Windows: venv\Scripts\activate
# Установка зависимостей
pip install -r requirements.txt
# Запуск
python main.py
```

**Терминал 2: Discord Bot**
```bash
cd services/discord_bot
# Используйте тот же venv или создайте новый
source ../api/venv/bin/activate 
pip install -r requirements.txt
python main.py
```

**Терминал 3: Twitch Bot**
```bash
cd services/twitch_bot
source ../api/venv/bin/activate
pip install -r requirements.txt
python main.py
```

**Терминал 4: Frontend (Web Panel)**
```bash
cd web
npm install
npm run dev
```

## 🏗️ Структура

Подробное описание архитектуры см. в [ARCHITECTURE.md](ARCHITECTURE.md).

```
PRMajesticBot/
├── services/
│   ├── api/            # FastAPI, Database, Auth
│   ├── discord_bot/    # Disnake, UI, Interaction
│   └── twitch_bot/     # TwitchIO, EventSub
├── web/                # React 19, Vite, Tailwind v4
└── ...
```

## 📌 API Контракт (кратко)

- `POST /api/auth/login` выдает access token с `sid` (ID сессии).
- `POST /api/auth/logout` отзывает сессии пользователя; старые access token после этого невалидны.
- Количество активных спек-сессий для клиентов берется из `GET /api/stats/dashboard` (`assigned_pr_count`).

## 🔧 Устранение неполадок

- **Ошибка подключения к БД**: Проверьте `DB_HOST`, `DB_USER` и `DB_PASSWORD` в `services/api/.env`. API автоматически создаст таблицы при первом успешном подключении.
- **RabbitMQ**: Если брокер недоступен, сервисы будут работать в ограниченном режиме (без уведомлений в реальном времени), но API и БД продолжат функционировать.
- **Frontend**: Если не работает логин, убедитесь, что API запущен на порту, указанном в конфигурации фронтенда (обычно 8000).

## 📝 Лицензия
Private / Proprietary.
