"""
Telegram message parser for trading signals.
Parses two types of messages:
1. Open signal: "Открыл GRASS LONG"
2. Target signal: "🔘 GRASS LONG плечо x25" with targets and stop
"""

import re
from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class OpenSignal:
    """Signal to open a position."""
    ticker: str
    side: str  # "LONG" or "SHORT"
    message_id: int = 0


@dataclass
class TargetSignal:
    """Signal with entry, targets, and stop loss."""
    ticker: str
    side: str  # "LONG" or "SHORT"
    entry: float
    targets: List[float] = field(default_factory=list)
    stop: float = 0.0
    message_id: int = 0


def normalize_side(side_str: str) -> str:
    """Normalize side string to LONG/SHORT."""
    side_upper = side_str.upper()
    if side_upper in ("LONG", "ЛОНГ"):
        return "LONG"
    elif side_upper in ("SHORT", "ШОРТ"):
        return "SHORT"
    return side_upper


def parse_open_signal(text: str, message_id: int = 0) -> Optional[OpenSignal]:
    """
    Parse type 1 message: "Открыл GRASS LONG 🔘"
    Pattern: r"Открыл\s+([A-Z0-9_]+)\s+(LONG|SHORT)" (case insensitive)
    Also supports Russian ЛОНГ/ШОРТ.
    """
    # Case-insensitive pattern for "Открыл TICKER SIDE"
    pattern = r"Открыл\s+([A-Z0-9_]+)\s+(LONG|SHORT|ЛОНГ|ШОРТ)"
    match = re.search(pattern, text, re.IGNORECASE)
    
    if match:
        ticker = match.group(1).upper()
        side = normalize_side(match.group(2))
        return OpenSignal(ticker=ticker, side=side, message_id=message_id)
    
    return None


def parse_target_signal(text: str, message_id: int = 0) -> Optional[TargetSignal]:
    """
    Parse type 2 message with targets and stop.
    Format:
    🔘 GRASS LONG плечо x25
    Точка входа: рынок (0.3235)
    Таргет 1: 0.3268
    Таргет 2: 0.3314
    Таргет 3: 0.3457
    Стоп: 0.3058
    """
    # Pattern for ticker and side: "🔘 GRASS LONG плечо x25"
    ticker_pattern = r"🔘\s*([A-Z0-9_]+)\s+(LONG|SHORT|ЛОНГ|ШОРТ)"
    ticker_match = re.search(ticker_pattern, text, re.IGNORECASE)
    
    if not ticker_match:
        return None
    
    ticker = ticker_match.group(1).upper()
    side = normalize_side(ticker_match.group(2))
    
    # Parse entry price: "Точка входа: рынок (0.3235)" or "Точка входа: 0.3235"
    entry = 0.0
    entry_pattern = r"Точка\s+входа[:.]\s*(?:рынок\s*\()?([\d.]+)"
    entry_match = re.search(entry_pattern, text, re.IGNORECASE)
    if entry_match:
        try:
            entry = float(entry_match.group(1))
        except ValueError:
            pass
    
    # Parse targets: "Таргет N: price" (1-4 targets)
    targets = []
    # Pattern handles: "Таргет 1:", "Таргет 1 :", "Таргет1:", "Таргет 2:51000"
    target_pattern = r"Таргет\s*\d*\s*[:.]\s*([\d.]+)"
    for match in re.finditer(target_pattern, text, re.IGNORECASE):
        try:
            targets.append(float(match.group(1)))
        except ValueError:
            pass
    
    # Parse stop loss: "Стоп: price" or "Стоп : price"
    stop = 0.0
    stop_pattern = r"Стоп\s*[:.]\s*([\d.]+)"
    stop_match = re.search(stop_pattern, text, re.IGNORECASE)
    if stop_match:
        try:
            stop = float(stop_match.group(1))
        except ValueError:
            pass
    
    if not targets and stop == 0.0:
        # No useful data found
        return None
    
    return TargetSignal(
        ticker=ticker,
        side=side,
        entry=entry,
        targets=targets,
        stop=stop,
        message_id=message_id
    )


def parse_message(text: str, message_id: int = 0) -> tuple[Optional[OpenSignal], Optional[TargetSignal]]:
    """
    Try to parse message as either open signal or target signal.
    Returns (open_signal, target_signal) - one will be None.
    """
    open_sig = parse_open_signal(text, message_id)
    if open_sig:
        return (open_sig, None)
    
    target_sig = parse_target_signal(text, message_id)
    if target_sig:
        return (None, target_sig)
    
    return (None, None)
