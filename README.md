# PRMajesticBot

Discord and Twitch integration bot for monitoring streamers and sending notifications to Discord channels.

## 🎯 Features

- **Stream Monitoring**: Automatically tracks when streamers go live or offline
- **Smart Notifications**: Sends Discord notifications when:
  - Streamer goes online
  - Streamer goes offline
  - Streamer changes category (special handling for GTA 5)
- **Multi-Server Support**: One bot can serve multiple Discord servers
- **Priority System**: Organize streamers by priority level
- **Database Persistence**: All data stored in MySQL database

## 📋 Requirements

- Python 3.10+
- MySQL 5.7+ or MariaDB 10.3+
- Discord Bot Token
- Twitch Application (Client ID, Client Secret)

## 🚀 Installation

### 1. Clone the repository

```bash
git clone <repository-url>
cd PRMajesticBot
```

### 2. Create virtual environment

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Create a `.env` file in the project root:

```env
# Twitch Configuration
CLIENT_ID=your_twitch_client_id
CLIENT_SECRET=your_twitch_client_secret
BOT_ID=your_twitch_bot_user_id

# Discord Configuration
DISCORD_TOKEN=your_discord_bot_token

# Database Configuration
DB_HOST=localhost
DB_USER=your_db_user
DB_PASSWORD=your_db_password
DB_NAME=prmajesticbot

# Logging Configuration (optional)
LOG_LEVEL=INFO  # Options: DEBUG, INFO, WARNING, ERROR
```

### 5. Setup MySQL Database

Create the database:

```sql
CREATE DATABASE prmajesticbot CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

The bot will automatically create required tables on first run.

### 6. Run the bot

```bash
python main.py
```

## 🎮 Discord Commands

All commands are slash commands (use `/` prefix):

### `/info`
Display bot version and developer information.

### `/add_streamer <url> [priority] [is_paid]`
Add a streamer to monitor.
- `url`: Twitch channel URL or username
- `priority` (optional): Priority level (default: 0)
- `is_paid` (optional): Whether streamer is paid/sponsored (default: false)

**Example:**
```
/add_streamer https://www.twitch.tv/shroud priority:5 is_paid:false
```

### `/remove_streamer <url>`
Remove a streamer from monitoring.
- `url`: Twitch channel URL or username

**Example:**
```
/remove_streamer shroud
```

### `/streamers`
Display all monitored streamers for this server with their current status, game, and stream title.

### `/settings`
Configure server settings (Admin only).
- Set notification channel for stream alerts

## 📊 Database Structure

### Tables

**streamers**
- Stores all unique streamers across all servers
- Tracks online status, game, title, priority, etc.

**subscriptions**
- Links servers to streamers (many-to-many relationship)
- Automatically cleaned up when last server unsubscribes

**settings**
- Server-specific configuration
- Notification channel ID

## 🔧 Configuration

### Logging Levels

Set `LOG_LEVEL` in `.env` to control logging verbosity:

- **DEBUG**: Detailed information for debugging (recommended for development)
  - Shows all database queries
  - Tracks all API calls
  - Logs every event
  
- **INFO**: General information (recommended for production)
  - Important events
  - User actions
  - Startup/shutdown messages
  
- **WARNING**: Warning messages only
  - Configuration issues
  - API errors
  
- **ERROR**: Error messages only
  - Critical failures

### Log Files

Logs are stored in the `logs/` directory:
- Filename: `bot.log`
- Rotation: Automatic at 10MB
- Backups: 5 files kept
- Encoding: UTF-8

### GTA 5 Monitoring

The bot has special handling for GTA 5 category changes. This is configurable in `config.py`:

```python
GTA5_GAME_ID = "32982"
```

## 🛠️ Development

### Running in DEBUG mode

Set in `.env`:
```env
LOG_LEVEL=DEBUG
```

This will provide verbose logging for development and troubleshooting.

### Project Structure

```
PRMajesticBot/
├── main.py              # Entry point
├── config.py            # Configuration and logging
├── database.py          # Database operations
├── twitch_bot.py        # Twitch integration
├── discord_bot.py       # Discord integration
├── cogs/                # Discord command modules
│   ├── info.py         # /info command
│   ├── manage_streamers.py  # Streamer management
│   └── settings.py     # Server settings
├── requirements.txt     # Dependencies
├── .env                # Environment variables (create this)
└── logs/               # Log files (auto-created)
```

## ❗ Troubleshooting

### Bot doesn't start

1. **Check environment variables**: Ensure all required variables in `.env` are set
2. **Check database connection**: Verify MySQL is running and credentials are correct
3. **Check logs**: Look at `logs/bot.log` for error details

### No notifications in Discord

1. **Check notification channel**: Use `/settings` to configure the channel
2. **Check bot permissions**: Bot needs permission to send messages in the channel
3. **Check streamer subscription**: Use `/streamers` to verify streamer is added

### Database errors

1. **Check character set**: Database should use `utf8mb4`
2. **Check user permissions**: DB user needs CREATE, INSERT, UPDATE, DELETE, SELECT
3. **Check connection**: Verify `DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`

### Twitch API errors

1. **Verify credentials**: Check `CLIENT_ID` and `CLIENT_SECRET`
2. **Check BOT_ID**: Must be a valid Twitch user ID (not username)
3. **Check rate limits**: Twitch API has rate limits

## 📝 License

This project is private/proprietary.

## 👨‍💻 Developer

Developed by 9avg

## 🔄 Version

Current version: TEST BUILD (in development)