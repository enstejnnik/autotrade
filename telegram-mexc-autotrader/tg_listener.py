"""
Telegram listener using Telethon.
Listens to channel messages and forwards signals to the trader.
"""

import asyncio
from typing import Optional, Callable
from telethon import TelegramClient
from telethon.events import NewMessage
from loguru import logger

from config import (
    API_ID, API_HASH, PHONE, CHANNEL, SESSION_FILE,
    CATCH_UP_ON_START
)
from parser import parse_message, OpenSignal, TargetSignal


class TelegramListener:
    """Async Telegram channel listener."""
    
    def __init__(
        self,
        open_callback: Callable[[OpenSignal], None],
        target_callback: Callable[[TargetSignal], None]
    ):
        self.client: Optional[TelegramClient] = None
        self.open_callback = open_callback
        self.target_callback = target_callback
        self._channel_id = None
    
    async def connect(self) -> bool:
        """Initialize and connect Telegram client."""
        try:
            self.client = TelegramClient(
                str(SESSION_FILE),
                API_ID,
                API_HASH
            )
            
            await self.client.start(phone=PHONE)
            
            # Resolve channel
            if CHANNEL.startswith("-100"):
                self._channel_id = int(CHANNEL)
            else:
                entity = await self.client.get_entity(CHANNEL)
                self._channel_id = entity.id
            
            logger.info(f"Telegram connected, channel ID: {self._channel_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect Telegram: {e}")
            return False
    
    async def start_listening(self) -> None:
        """Start listening for new messages."""
        if not self.client:
            raise RuntimeError("Telegram client not connected")
        
        # Catch up on recent messages if enabled
        if CATCH_UP_ON_START:
            await self._catch_up_messages()
        
        # Register event handler
        @self.client.on(NewMessage(chats=[self._channel_id]))
        async def handler(event):
            await self._handle_message(event.message)
        
        logger.info("Telegram listener started")
        
        # Run until disconnected
        await self.client.run_until_disconnected()
    
    async def _catch_up_messages(self) -> None:
        """Fetch and process last 10 messages from channel."""
        logger.info("Catching up on recent messages...")
        
        try:
            messages = await self.client.get_messages(self._channel_id, limit=10)
            
            # Process in reverse order (oldest first)
            for msg in reversed(messages):
                if msg.text:
                    await self._handle_message(msg, catch_up=True)
            
            logger.info(f"Processed {len(messages)} historical messages")
            
        except Exception as e:
            logger.warning(f"Failed to catch up messages: {e}")
    
    async def _handle_message(self, message, catch_up: bool = False) -> None:
        """Parse and route a message."""
        if not message.text:
            return
        
        text = message.text
        msg_id = message.id
        
        logger.debug(f"Processing message {msg_id}: {text[:50]}...")
        
        open_sig, target_sig = parse_message(text, msg_id)
        
        if open_sig:
            logger.info(f"Open signal: {open_sig.ticker} {open_sig.side}")
            if not catch_up:
                await self.open_callback(open_sig)
        elif target_sig:
            logger.info(f"Target signal: {target_sig.ticker} targets={target_sig.targets}")
            if not catch_up:
                await self.target_callback(target_sig)
        else:
            logger.debug(f"No signal parsed from message {msg_id}")
    
    async def send_message(self, chat_id: str, text: str) -> bool:
        """Send a message to a chat (e.g., 'me' for Saved Messages)."""
        if not self.client:
            return False
        
        try:
            await self.client.send_message(chat_id, text)
            return True
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            return False
    
    async def disconnect(self) -> None:
        """Disconnect Telegram client."""
        if self.client and not self.client.is_connected():
            await self.client.disconnect()
            logger.info("Telegram disconnected")
