"""
Settings management module.
Handles margin and dry_run settings via settings.json.
Provides console menu for user interaction.
"""

import json
import asyncio
from pathlib import Path
from typing import Optional
from loguru import logger


class Settings:
    """Manages trading settings persisted in settings.json."""
    
    def __init__(self, settings_file: Path):
        self.settings_file = settings_file
        self._margin_usd: float = 10.0
        self._dry_run: bool = True
        self._lock = asyncio.Lock()
        self._load()
    
    def _load(self) -> None:
        """Load settings from file."""
        if self.settings_file.exists():
            try:
                with open(self.settings_file, "r") as f:
                    data = json.load(f)
                self._margin_usd = float(data.get("margin_usd", 10.0))
                self._dry_run = bool(data.get("dry_run", True))
                logger.info(f"Settings loaded: margin={self._margin_usd}, dry_run={self._dry_run}")
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"Failed to load settings: {e}, using defaults")
                self._margin_usd = 10.0
                self._dry_run = True
        else:
            logger.info("No settings file found, using defaults")
            self._save()
    
    def _save(self) -> None:
        """Save settings to file atomically."""
        data = {
            "margin_usd": self._margin_usd,
            "dry_run": self._dry_run
        }
        temp_file = self.settings_file.with_suffix(".tmp")
        with open(temp_file, "w") as f:
            json.dump(data, f, indent=2)
        temp_file.replace(self.settings_file)
        logger.info(f"Settings saved: margin={self._margin_usd}, dry_run={self._dry_run}")
    
    @property
    def margin_usd(self) -> float:
        return self._margin_usd
    
    @property
    def dry_run(self) -> bool:
        return self._dry_run
    
    async def set_margin(self, value: float) -> bool:
        """Set margin value. Returns True if successful."""
        if value <= 0:
            logger.error(f"Invalid margin value: {value}")
            return False
        async with self._lock:
            self._margin_usd = value
            self._save()
            logger.success(f"Margin updated to {value} USD")
        return True
    
    async def toggle_dry_run(self) -> bool:
        """Toggle dry_run mode. Returns new value."""
        async with self._lock:
            self._dry_run = not self._dry_run
            self._save()
            logger.success(f"Dry-run mode {'enabled' if self._dry_run else 'disabled'}")
        return self._dry_run
    
    def get_status(self) -> str:
        """Return human-readable status string."""
        return f"Margin: {self._margin_usd} USD | Leverage: x25 | Dry-run: {self._dry_run}"


async def run_menu(settings: Settings) -> None:
    """Run interactive console menu."""
    loop = asyncio.get_event_loop()
    
    print("\n" + "="*50)
    print("TELEGRAM MEXC AUTOTRADER")
    print("="*50)
    
    while True:
        print("\n[1] Start trading")
        print(f"    Current: {settings.get_status()}")
        print("[2] Change margin")
        print("[3] Toggle DRY-RUN")
        print("[4] Exit")
        
        # Read input asynchronously without blocking
        choice = await loop.run_in_executor(None, input, "\nSelect option [1-4]: ")
        
        if choice == "1":
            print("\nStarting trading mode...")
            print("Use commands: margin <value>, status, help, stop")
            break
        elif choice == "2":
            margin_str = await loop.run_in_executor(None, input, "Enter margin value (USD): ")
            try:
                margin_val = float(margin_str.strip())
                if margin_val > 0:
                    await settings.set_margin(margin_val)
                else:
                    print("Margin must be > 0")
            except ValueError:
                print("Invalid number")
        elif choice == "3":
            new_val = await settings.toggle_dry_run()
            print(f"DRY-RUN is now: {'ON' if new_val else 'OFF'}")
        elif choice == "4":
            print("Exiting...")
            exit(0)
        else:
            print("Invalid option")


async def run_live_commands(settings: Settings, stop_event: asyncio.Event) -> None:
    """Run live command interpreter during trading."""
    loop = asyncio.get_event_loop()
    
    print("\n--- Live Command Mode (type 'help' for commands) ---")
    
    while not stop_event.is_set():
        try:
            cmd_line = await asyncio.wait_for(
                loop.run_in_executor(None, input, ""),
                timeout=1.0
            )
        except asyncio.TimeoutError:
            continue
        except EOFError:
            break
        
        parts = cmd_line.strip().split()
        if not parts:
            continue
        
        cmd = parts[0].lower()
        
        if cmd == "stop":
            print("Stopping trading...")
            stop_event.set()
            break
        elif cmd == "margin":
            if len(parts) < 2:
                print("Usage: margin <value>")
                continue
            try:
                val = float(parts[1])
                if val > 0:
                    await settings.set_margin(val)
                else:
                    print("Margin must be > 0")
            except ValueError:
                print("Invalid number")
        elif cmd == "status":
            print(f"\n{settings.get_status()}")
            # Will be extended by trader to show active positions
        elif cmd == "help":
            print("\nCommands:")
            print("  margin <value> - Change margin for future trades")
            print("  status         - Show current settings")
            print("  help           - Show this help")
            print("  stop           - Stop trading gracefully")
        else:
            print(f"Unknown command: {cmd}")
