# PRMajesticBot

Интеграционный бот Discord и Twitch для мониторинга стримеров и отправки уведомлений в каналы Discord.

## 🎯 Возможности

- **Мониторинг стримов**: Автоматическое отслеживание запуска и окончания трансляций, а также смену категории.
- **Умные уведомления**: Отправка сообщений в Discord, когда:
  - Стример выходит в эфир
  - Стример заканчивает трансляцию
  - Стример меняет категорию (специальная обработка для GTA 5)
- **Система приоритетов**: Организация стримеров по уровням приоритета
- **База данных**: Все данные хранятся в базе данных MySQL

## 📋 Требования

Перед запуском проекта убедитесь, что у вас установлено следующее:

- **Python 3.10+**: Основной язык для бэкенд-сервисов
- **RabbitMQ**: Брокер сообщений для межсервисного взаимодействия
- **MySQL 5.7+ / MariaDB 10.3+**: База данных для постоянного хранения
- **Node.js 18+ & npm**: Для сборки веб-панели (Dashboard)

### Обзор архитектуры

Для детального понимания архитектуры системы и взаимодействия микросервисов, пожалуйста, прочитайте [ARCHITECTURE.md](ARCHITECTURE.md).

## 🚀 Установка и настройка

### 1. Клонирование репозитория

```bash
git clone <repository-url>
cd PRMajesticBot
```

### 2. Настройка переменных окружения

Каждый сервис требует собственной конфигурации. Скопируйте файлы примеров и заполните свои данные:

**API Service:**
```bash
cp services/api/example.env services/api/.env
nano services/api/.env
```

**Discord Bot Service:**
```bash
cp services/discord_bot/example.env services/discord_bot/.env
nano services/discord_bot/.env
```

**Twitch Bot Service:**
```bash
cp services/twitch_bot/example.env services/twitch_bot/.env
nano services/twitch_bot/.env
```

### 3. Запуск сервисов

Вам нужно запустить каждый сервис в отдельном окне терминала/screen.

**Терминал 1: API Service**
```bash
cd services/api
pip3 install -r requirements.txt
uvicorn api.main:app --reload
```

**Терминал 2: Discord Bot**
```bash
cd services/discord_bot
pip3 install -r requirements.txt
python3 main.py
```

**Терминал 3: Twitch Bot**
```bash
cd services/twitch_bot
pip3 install -r requirements.txt
python3 main.py
```

**Терминал 4: Web Panel (Разработка)**
```bash
cd web
npm install
npm run dev
# В настоящее время в разработке. Будущие версии будут использовать контейнеры.
```

## 🏗️ Структура проекта

Проект разделен на микросервисы:

```
PRMajesticBot/
├── services/
│   ├── api/            # Центральный REST API и База данных
│   ├── discord_bot/    # Взаимодействие с Discord и UI
│   └── twitch_bot/     # Мониторинг Twitch и брокер событий
├── web/                # Веб-панель (React/Vite)
└── README.md
```

## 🔧 Устранение неполадок

### Сервисы не подключаются
Убедитесь, что RabbitMQ запущен и правильно настроен во всех файлах `.env`. Сервисы полагаются на RabbitMQ для общения.

### Ошибки базы данных
Убедитесь, что в `services/api/.env` указаны правильные учетные данные базы данных. Сервис API автоматически обрабатывает миграции базы данных при запуске.

## 📝 Лицензия

Этот проект является частным/проприетарным.