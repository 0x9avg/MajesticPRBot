"""
Main entry point for PRMajesticBot.
Initializes and runs Discord and Twitch bots with database connection.
"""

import asyncio
import logging
import os
import sys
from dotenv import load_dotenv

from config import Config
from database import Database
from twitch_bot import TwitchBot
from discord_bot import DiscordBot

# Load environment variables
load_dotenv()


def main():
    """Main function to initialize and run the bot."""
    
    # Setup logging first
    logger = Config.setup_logging(__name__)
    
    logger.info("=" * 60)
    logger.info("Starting PRMajesticBot...")
    logger.info("=" * 60)
    
    # Validate environment variables
    logger.debug("Validating environment variables...")
    missing_vars = Config.validate_env_vars()
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        logger.error("Please check your .env file and ensure all required variables are set.")
        sys.exit(1)
    logger.info("✓ All environment variables validated")
    
    # Log current configuration
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logger.debug(f"Log level: {log_level}")
    logger.debug(f"Logs directory: {Config.LOG_DIR}")
    logger.debug(f"Database host: {os.getenv('DB_HOST')}")
    
    try:
        # Initialize database
        logger.debug("Initializing database connection...")
        database = Database(
            db_host=os.getenv("DB_HOST"),
            db_user=os.getenv("DB_USER"),
            db_password=os.getenv("DB_PASSWORD"),
            db_name=os.getenv("DB_NAME"),
            logger=Config.setup_logging("Database"),
        )
        logger.debug("✓ Database initialized")
        
        # Initialize Twitch bot
        logger.debug("Initializing Twitch bot...")
        twitch_bot = TwitchBot(
            client_id=os.getenv("CLIENT_ID"),
            client_secret=os.getenv("CLIENT_SECRET"),
            bot_id=os.getenv("BOT_ID"),
            logger=Config.setup_logging("TwitchBot"),
            database=database,
        )
        logger.debug("✓ Twitch bot initialized")
        
        # Initialize Discord bot
        logger.debug("Initializing Discord bot...")
        discord_bot = DiscordBot(
            DiscordToken=os.getenv("DISCORD_TOKEN"),
            database=database,
            logger=Config.setup_logging("DiscordBot"),
        )
        logger.debug("✓ Discord bot initialized")
        
        # Cross-reference bots
        twitch_bot.discord_bot = discord_bot
        discord_bot.twitch_bot = twitch_bot
        logger.debug("Bots cross-referenced successfully")
        
        # Load cogs AFTER cross-referencing (cogs need twitch_bot reference)
        discord_bot.setup_cogs()
        
        # Setup event loop
        logger.debug("Starting event loop...")
        loop = asyncio.get_event_loop()
        asyncio.set_event_loop(loop)
        
        # Create tasks
        task_database = loop.create_task(database.start())
        task_twitch = loop.create_task(twitch_bot.start())
        task_discord = loop.create_task(discord_bot.start())
        gathered = asyncio.gather(task_database, task_twitch, task_discord)
        
        logger.info("=" * 60)
        logger.info("All components started successfully!")
        logger.info("Bot is now running. Press Ctrl+C to stop.")
        logger.info("=" * 60)
        
        # Run until interrupted
        loop.run_until_complete(gathered)
        
    except KeyboardInterrupt:
        logger.warning("\n" + "=" * 60)
        logger.warning("Keyboard interrupt detected. Shutting down gracefully...")
        logger.warning("=" * 60)
    except Exception as e:
        logger.error("=" * 60)
        logger.error(f"Fatal error during initialization: {e}", exc_info=True)
        logger.error("=" * 60)
        sys.exit(1)
    finally:
        # Cleanup
        logger.debug("Cleaning up resources...")
        try:
            if 'database' in locals() and database.pool:
                logger.debug("Closing database connection pool...")
                # CRITICAL FIX: Properly await async close method
                loop.run_until_complete(database.close())
                logger.debug("✓ Database connection closed")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}", exc_info=True)
        
        logger.info("=" * 60)
        logger.info("Bot stopped. Goodbye!")
        logger.info("=" * 60)


if __name__ == "__main__":
    main()

