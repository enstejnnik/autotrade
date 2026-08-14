"""
Main entry point for telegram-mexc-autotrader.
Orchestrates all components: settings menu, Telegram listener, MEXC client, trader.
"""

import asyncio
import sys
from pathlib import Path
from loguru import logger

from config import LOG_FILE, STATE_FILE, SETTINGS_FILE
from settings import Settings, run_menu, run_live_commands
from mexc import MexcClient
from state import TradeState
from trader import Trader
from tg_listener import TelegramListener
from parser import OpenSignal, TargetSignal


def setup_logging():
    """Configure loguru logging."""
    # Remove default handler
    logger.remove()
    
    # Console handler
    logger.add(
        sys.stdout,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level="INFO"
    )
    
    # File handler with rotation
    logger.add(
        str(LOG_FILE),
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        level="DEBUG",
        rotation="10 MB",
        retention="7 days"
    )
    
    logger.info("Logging initialized")


async def main():
    """Main application entry point."""
    setup_logging()
    
    # Ensure logs directory exists
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    # Initialize settings
    settings = Settings(SETTINGS_FILE)
    
    # Run initial menu
    await run_menu(settings)
    
    # Initialize components
    mexc_client = MexcClient(dry_run=settings.dry_run)
    trade_state = TradeState(STATE_FILE)
    
    # Notification callback (sends to Telegram Saved Messages)
    async def notify(text: str):
        logger.info(f"Notification: {text}")
        if tg_listener:
            await tg_listener.send_message("me", text)
    
    # Initialize trader
    trader = Trader(
        mexc_client=mexc_client,
        trade_state=trade_state,
        settings=settings,
        notify_callback=notify
    )
    
    # Initialize Telegram listener
    tg_listener = TelegramListener(
        open_callback=trader.handle_open_signal,
        target_callback=trader.handle_target_signal
    )
    
    # Connect to Telegram
    logger.info("Connecting to Telegram...")
    if not await tg_listener.connect():
        logger.error("Failed to connect to Telegram. Check your API credentials.")
        return
    
    # Start trader
    await trader.start()
    
    # Create stop event for live commands
    stop_event = asyncio.Event()
    
    # Run Telegram listener and live commands concurrently
    listen_task = asyncio.create_task(tg_listener.start_listening())
    cmd_task = asyncio.create_task(run_live_commands(settings, stop_event))
    
    # Wait for stop signal
    try:
        await stop_event.wait()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    
    # Cleanup
    logger.info("Shutting down...")
    stop_event.set()
    
    await trader.stop()
    await tg_listener.disconnect()
    
    # Cancel tasks
    listen_task.cancel()
    cmd_task.cancel()
    
    try:
        await listen_task
    except asyncio.CancelledError:
        pass
    
    try:
        await cmd_task
    except asyncio.CancelledError:
        pass
    
    logger.info("Goodbye!")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped by user")
