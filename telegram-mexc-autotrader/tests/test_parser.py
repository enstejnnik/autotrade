"""
Tests for the message parser module.
Validates parsing of both signal types with real message examples.
"""

import pytest
from parser import parse_message, parse_open_signal, parse_target_signal, OpenSignal, TargetSignal


class TestOpenSignal:
    """Tests for open signal parsing (Type 1)."""
    
    def test_parse_open_signal_grass_example(self):
        """Test parsing the GRASS example message."""
        text = """МАРАФОН СО 100$ by ARKADIY
Открыл GRASS LONG 🔘

Моя маржа 10$ плечо x25

➦ Ссылка на монету"""
        
        result = parse_open_signal(text, message_id=123)
        
        assert result is not None
        assert result.ticker == "GRASS"
        assert result.side == "LONG"
        assert result.message_id == 123
    
    def test_parse_open_signal_lowercase(self):
        """Test case-insensitive parsing."""
        text = "Открыл bitcoin long"
        result = parse_open_signal(text)
        
        assert result is not None
        assert result.ticker == "BITCOIN"
        assert result.side == "LONG"
    
    def test_parse_open_signal_short(self):
        """Test SHORT side parsing."""
        text = "Открыл ETH SHORT 📉"
        result = parse_open_signal(text)
        
        assert result is not None
        assert result.ticker == "ETH"
        assert result.side == "SHORT"
    
    def test_parse_open_signal_russian_long(self):
        """Test Russian ЛОНГ variant."""
        text = "Открыл BTC ЛОНГ"
        result = parse_open_signal(text)
        
        assert result is not None
        assert result.ticker == "BTC"
        assert result.side == "LONG"
    
    def test_parse_open_signal_russian_short(self):
        """Test Russian ШОРТ variant."""
        text = "Открыл SOL ШОРТ"
        result = parse_open_signal(text)
        
        assert result is not None
        assert result.ticker == "SOL"
        assert result.side == "SHORT"
    
    def test_no_open_signal(self):
        """Test that non-matching text returns None."""
        text = "Просто какое-то сообщение без сигнала"
        result = parse_open_signal(text)
        
        assert result is None


class TestTargetSignal:
    """Tests for target signal parsing (Type 2)."""
    
    def test_parse_target_signal_grass_example(self):
        """Test parsing the GRASS targets example message."""
        text = """🔘 GRASS LONG плечо x25

Точка входа: рынок (0.3235)

Таргет 1: 0.3268
Таргет 2: 0.3314
Таргет 3: 0.3457

Стоп: 0.3058

Моя маржа: 10$
Банк марафона: 114.92$

➦ Открыть сделку"""
        
        result = parse_target_signal(text, message_id=456)
        
        assert result is not None
        assert result.ticker == "GRASS"
        assert result.side == "LONG"
        assert result.entry == 0.3235
        assert len(result.targets) == 3
        assert result.targets[0] == 0.3268
        assert result.targets[1] == 0.3314
        assert result.targets[2] == 0.3457
        assert result.stop == 0.3058
        assert result.message_id == 456
    
    def test_parse_target_signal_4_targets(self):
        """Test parsing message with 4 targets."""
        text = """🔘 BTC LONG плечо x25

Точка входа: рынок (45000)

Таргет 1: 45500
Таргет 2: 46000
Таргет 3: 47000
Таргет 4: 48000

Стоп: 44000"""
        
        result = parse_target_signal(text)
        
        assert result is not None
        assert len(result.targets) == 4
        assert result.targets == [45500, 46000, 47000, 48000]
        assert result.stop == 44000
    
    def test_parse_target_signal_1_target(self):
        """Test parsing message with single target."""
        text = """🔘 ETH SHORT

Точка входа: 2500

Таргет 1: 2400

Стоп: 2600"""
        
        result = parse_target_signal(text)
        
        assert result is not None
        assert len(result.targets) == 1
        assert result.targets[0] == 2400
        assert result.stop == 2600
    
    def test_parse_target_signal_russian_short(self):
        """Test Russian ШОРТ in target signal."""
        text = """🔘 SOL ШОРТ плечо x25

Точка входа: 100

Таргет 1: 95

Стоп: 105"""
        
        result = parse_target_signal(text)
        
        assert result is not None
        assert result.ticker == "SOL"
        assert result.side == "SHORT"
    
    def test_parse_target_signal_entry_without_parentheses(self):
        """Test entry price without parentheses format."""
        text = """🔘 BTC LONG

Точка входа: 50000

Таргет 1: 51000
Стоп: 49000"""
        
        result = parse_target_signal(text)
        
        assert result is not None
        assert result.entry == 50000


class TestParseMessage:
    """Tests for the unified parse_message function."""
    
    def test_parse_open_message(self):
        """Test that open signal is correctly identified."""
        text = "Открыл GRASS LONG 🔘"
        open_sig, target_sig = parse_message(text)
        
        assert open_sig is not None
        assert target_sig is None
        assert open_sig.ticker == "GRASS"
    
    def test_parse_target_message(self):
        """Test that target signal is correctly identified."""
        text = """🔘 GRASS LONG плечо x25
Точка входа: 0.3235
Таргет 1: 0.3268
Стоп: 0.3058"""
        open_sig, target_sig = parse_message(text)
        
        assert open_sig is None
        assert target_sig is not None
        assert target_sig.ticker == "GRASS"
    
    def test_parse_unknown_message(self):
        """Test that unknown messages return None for both."""
        text = "Просто текст без сигналов"
        open_sig, target_sig = parse_message(text)
        
        assert open_sig is None
        assert target_sig is None


class TestEdgeCases:
    """Tests for edge cases and variations."""
    
    def test_ticker_with_numbers(self):
        """Test ticker containing numbers."""
        text = "Открыл BTC3S LONG"
        result = parse_open_signal(text)
        
        assert result is not None
        assert result.ticker == "BTC3S"
    
    def test_ticker_with_underscore(self):
        """Test ticker with underscore."""
        text = "Открыл USDT_DOM LONG"
        result = parse_open_signal(text)
        
        assert result is not None
        assert result.ticker == "USDT_DOM"
    
    def test_multiple_spaces(self):
        """Test message with multiple spaces."""
        text = "Открыл    BTC    LONG"
        result = parse_open_signal(text)
        
        assert result is not None
        assert result.ticker == "BTC"
    
    def test_target_variations(self):
        """Test various target line formats."""
        text = """🔘 BTC LONG
Таргет 1 : 50000
Таргет 2:51000
Таргет 3: 52000
Стоп : 49000"""
        
        result = parse_target_signal(text)
        
        assert result is not None
        assert len(result.targets) == 3
        assert result.stop == 49000
