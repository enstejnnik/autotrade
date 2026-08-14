"""
State management for active trades.
Persists trade state to state.json for recovery after restarts.
"""

import json
import asyncio
from pathlib import Path
from typing import Dict, Optional, List
from dataclasses import dataclass, field, asdict
from loguru import logger


@dataclass
class ActiveTrade:
    """Represents an active trade being managed."""
    ticker: str
    symbol: str
    side: str  # "LONG" or "SHORT"
    entry_price: float
    volume: int  # Contract units
    margin_usd: float
    leverage: int
    targets: List[float] = field(default_factory=list)
    stop_price: float = 0.0
    tp_orders: Dict[int, str] = field(default_factory=dict)  # {target_idx: order_id}
    stop_order_id: Optional[str] = None
    remaining_volume: int = 0
    filled_targets: List[int] = field(default_factory=list)
    state: str = "WAIT_TARGETS"  # WAIT_TARGETS, MANAGING, DONE
    open_msg_id: int = 0
    target_msg_id: int = 0
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> "ActiveTrade":
        return cls(**data)


class TradeState:
    """Manages persistent state of active trades."""
    
    def __init__(self, state_file: Path):
        self.state_file = state_file
        self._trades: Dict[str, ActiveTrade] = {}  # keyed by symbol
        self._processed_msg_ids: set = set()
        self._lock = asyncio.Lock()
        self._load()
    
    def _load(self) -> None:
        """Load state from file."""
        if self.state_file.exists():
            try:
                with open(self.state_file, "r") as f:
                    data = json.load(f)
                
                trades_data = data.get("trades", {})
                for symbol, trade_data in trades_data.items():
                    self._trades[symbol] = ActiveTrade.from_dict(trade_data)
                
                self._processed_msg_ids = set(data.get("processed_msg_ids", []))
                
                logger.info(f"Loaded state: {len(self._trades)} active trades")
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Failed to load state: {e}")
        else:
            logger.info("No state file found, starting fresh")
    
    def _save(self) -> None:
        """Save state to file atomically."""
        data = {
            "trades": {symbol: trade.to_dict() for symbol, trade in self._trades.items()},
            "processed_msg_ids": list(self._processed_msg_ids)
        }
        temp_file = self.state_file.with_suffix(".tmp")
        with open(temp_file, "w") as f:
            json.dump(data, f, indent=2)
        temp_file.replace(self.state_file)
    
    async def add_trade(self, trade: ActiveTrade) -> None:
        """Add a new active trade."""
        async with self._lock:
            self._trades[trade.symbol] = trade
            self._save()
            logger.info(f"Added trade: {trade.symbol} {trade.side}")
    
    async def update_trade(self, symbol: str, **kwargs) -> Optional[ActiveTrade]:
        """Update fields of an existing trade."""
        async with self._lock:
            if symbol not in self._trades:
                return None
            trade = self._trades[symbol]
            for key, value in kwargs.items():
                if hasattr(trade, key):
                    setattr(trade, key, value)
            self._save()
            return trade
    
    async def get_trade(self, symbol: str) -> Optional[ActiveTrade]:
        """Get trade by symbol."""
        return self._trades.get(symbol)
    
    async def remove_trade(self, symbol: str) -> None:
        """Remove a completed trade."""
        async with self._lock:
            if symbol in self._trades:
                del self._trades[symbol]
                self._save()
                logger.info(f"Removed trade: {symbol}")
    
    async def get_all_trades(self) -> List[ActiveTrade]:
        """Get all active trades."""
        return list(self._trades.values())
    
    async def mark_message_processed(self, msg_id: int) -> bool:
        """Mark a message as processed to avoid duplicates."""
        async with self._lock:
            if msg_id in self._processed_msg_ids:
                return False
            self._processed_msg_ids.add(msg_id)
            # Keep only last 1000 IDs to prevent unbounded growth
            if len(self._processed_msg_ids) > 1000:
                self._processed_msg_ids = set(list(self._processed_msg_ids)[-1000:])
            self._save()
            return True
    
    async def is_message_processed(self, msg_id: int) -> bool:
        """Check if message was already processed."""
        return msg_id in self._processed_msg_ids
    
    async def get_managing_trades(self) -> List[ActiveTrade]:
        """Get all trades in MANAGING state."""
        return [t for t in self._trades.values() if t.state == "MANAGING"]
    
    async def get_waiting_trades(self) -> List[ActiveTrade]:
        """Get all trades in WAIT_TARGETS state."""
        return [t for t in self._trades.values() if t.state == "WAIT_TARGETS"]
