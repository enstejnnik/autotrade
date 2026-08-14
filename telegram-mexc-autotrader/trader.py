"""
Core trading logic and state machine.
Handles position opening, target placement, stop loss management, and TP execution.
"""

import asyncio
from typing import Optional, List
from loguru import logger

from config import LEVERAGE, TP_SPLIT, TARGETS_TIMEOUT_SEC, DEFAULT_STOP_PCT, POLL_SEC
from parser import OpenSignal, TargetSignal
from mexc import MexcClient
from state import TradeState, ActiveTrade
from settings import Settings


class Trader:
    """Main trading engine with state machine."""
    
    def __init__(
        self,
        mexc_client: MexcClient,
        trade_state: TradeState,
        settings: Settings,
        notify_callback: callable
    ):
        self.client = mexc_client
        self.state = trade_state
        self.settings = settings
        self.notify = notify_callback
        self._watcher_task: Optional[asyncio.Task] = None
        self._running = False
    
    async def start(self) -> None:
        """Start the trader and recovery watcher."""
        self._running = True
        
        # Recovery: resume watcher for trades in MANAGING state
        managing_trades = await self.state.get_managing_trades()
        if managing_trades:
            logger.info(f"Recovering {len(managing_trades)} active trades")
            for trade in managing_trades:
                logger.info(f"Resuming watcher for {trade.symbol}")
        
        # Start the watcher task
        self._watcher_task = asyncio.create_task(self._run_watcher())
        logger.info("Trader started")
    
    async def stop(self) -> None:
        """Stop the trader gracefully."""
        self._running = False
        if self._watcher_task:
            self._watcher_task.cancel()
            try:
                await self._watcher_task
            except asyncio.CancelledError:
                pass
        await self.client.close()
        logger.info("Trader stopped")
    
    def _get_symbol(self, ticker: str) -> str:
        """Convert ticker to MEXC symbol format."""
        return f"{ticker.upper()}_USDT"
    
    def _calculate_volume(self, price: float, margin_usd: float, contract_size: float = 1.0) -> int:
        """
        Calculate contract volume from margin.
        qty_base = margin * leverage / price
        Then adjust for contract_size and round down.
        """
        if price <= 0:
            return 0
        
        # Total position value = margin * leverage
        position_value = margin_usd * LEVERAGE
        
        # Number of contracts = position_value / price
        # Adjusted for contract size
        raw_qty = position_value / price / contract_size
        
        # Round down to integer (MEXC uses integer volumes)
        return max(1, int(raw_qty))
    
    async def handle_open_signal(self, signal: OpenSignal) -> None:
        """Process an open signal message."""
        symbol = self._get_symbol(signal.ticker)
        
        # Check if already processed
        if await self.state.is_message_processed(signal.message_id):
            logger.debug(f"Message {signal.message_id} already processed")
            return
        
        # Check if we already have an open trade for this symbol
        existing_trade = await self.state.get_trade(symbol)
        if existing_trade and existing_trade.state != "DONE":
            logger.warning(f"Already have active trade for {symbol}, skipping")
            await self.notify(f"⚠️ Пропуск {signal.ticker}: уже есть открытая позиция")
            return
        
        # Verify contract exists
        detail = await self.client.get_detail(symbol)
        if not detail:
            logger.warning(f"Contract {symbol} not found on MEXC")
            await self.notify(f"❌ {signal.ticker} не найден на MEXC")
            await self.state.mark_message_processed(signal.message_id)
            return
        
        # Get price info for volume calculation
        ticker_info = await self.client.get_ticker(symbol)
        current_price = 0.0
        if ticker_info and "data" in ticker_info:
            data = ticker_info["data"]
            current_price = float(data.get("last", 0))
        
        if current_price <= 0:
            logger.warning(f"Could not get price for {symbol}")
            await self.notify(f"❌ Не удалось получить цену для {signal.ticker}")
            return
        
        # Calculate volume based on current margin setting
        margin = self.settings.margin_usd
        volume = self._calculate_volume(current_price, margin)
        
        logger.info(f"Opening {signal.side} position on {symbol}: vol={volume}, margin={margin}")
        
        # Set leverage
        if not await self.client.change_leverage(symbol, LEVERAGE):
            logger.error(f"Failed to set leverage for {symbol}")
            await self.notify(f"❌ Ошибка установки плеча для {signal.ticker}")
            return
        
        # Submit market order
        # Side: 1=Open Long, 3=Open Short
        side_code = 1 if signal.side == "LONG" else 3
        order_result = await self.client.submit_order(
            symbol=symbol,
            side=side_code,
            order_type=2,  # Market
            vol=volume
        )
        
        if not order_result:
            logger.error(f"Failed to open position for {symbol}")
            await self.notify(f"❌ Ошибка открытия позиции {signal.ticker}")
            return
        
        # Get actual fill info (in dry-run, use signal price or current price)
        entry_price = current_price
        filled_vol = volume
        
        if not self.settings.dry_run:
            # In real mode, fetch position to get actual entry
            await asyncio.sleep(1)  # Wait for fill
            pos_info = await self.client.get_position(symbol)
            if pos_info and "data" in pos_info:
                data = pos_info["data"]
                if isinstance(data, list) and len(data) > 0:
                    entry_price = float(data[0].get("openPrice", entry_price))
                    filled_vol = int(float(data[0].get("vol", volume)))
        
        # Create trade record
        trade = ActiveTrade(
            ticker=signal.ticker,
            symbol=symbol,
            side=signal.side,
            entry_price=entry_price,
            volume=filled_vol,
            margin_usd=margin,
            leverage=LEVERAGE,
            remaining_volume=filled_vol,
            state="WAIT_TARGETS",
            open_msg_id=signal.message_id
        )
        
        await self.state.add_trade(trade)
        
        await self.notify(
            f"✅ Открыл {signal.ticker} {signal.side}\n"
            f"Цена: {entry_price}\n"
            f"Объём: {filled_vol}\n"
            f"Маржа: ${margin} | Плечо: x{LEVERAGE}"
        )
        
        await self.state.mark_message_processed(signal.message_id)
        
        # Start waiting for targets
        asyncio.create_task(self._wait_for_targets(symbol, TARGETS_TIMEOUT_SEC))
    
    async def _wait_for_targets(self, symbol: str, timeout_sec: int) -> None:
        """Wait for target signal within timeout."""
        await asyncio.sleep(timeout_sec)
        
        trade = await self.state.get_trade(symbol)
        if not trade or trade.state != "WAIT_TARGETS":
            return
        
        logger.warning(f"Timeout waiting for targets on {symbol}")
        
        # If no targets came, optionally set default stop
        if DEFAULT_STOP_PCT > 0 and trade.entry_price > 0:
            if trade.side == "LONG":
                stop_price = trade.entry_price * (1 - DEFAULT_STOP_PCT / 100)
            else:
                stop_price = trade.entry_price * (1 + DEFAULT_STOP_PCT / 100)
            
            await self._place_stop_loss(trade, stop_price)
            await self.notify(f"⚠️ Цели не пришли для {trade.ticker}, стоп установлен на {stop_price}")
        
        # Continue in WAIT_TARGETS or transition based on config
        # For now, keep waiting indefinitely until targets arrive or trade is closed
    
    async def handle_target_signal(self, signal: TargetSignal) -> None:
        """Process a target signal message."""
        symbol = self._get_symbol(signal.ticker)
        
        # Check if already processed
        if await self.state.is_message_processed(signal.message_id):
            logger.debug(f"Message {signal.message_id} already processed")
            return
        
        trade = await self.state.get_trade(symbol)
        
        # Recovery: if no trade in state but position exists on exchange
        if not trade:
            # Check if there's an open position
            pos_info = await self.client.get_position(symbol)
            if pos_info and "data" in pos_info:
                data = pos_info["data"]
                if isinstance(data, list) and len(data) > 0:
                    pos = data[0]
                    entry_price = float(pos.get("openPrice", 0))
                    volume = int(float(pos.get("vol", 0)))
                    side = "LONG" if pos.get("positionType") == 1 else "SHORT"
                    
                    logger.info(f"Recovered trade from exchange: {symbol}")
                    trade = ActiveTrade(
                        ticker=signal.ticker,
                        symbol=symbol,
                        side=side,
                        entry_price=entry_price,
                        volume=volume,
                        margin_usd=self.settings.margin_usd,
                        leverage=LEVERAGE,
                        remaining_volume=volume,
                        state="WAIT_TARGETS"
                    )
                    await self.state.add_trade(trade)
        
        if not trade:
            logger.warning(f"No active trade for {symbol}, ignoring targets")
            await self.notify(f"⚠️ Цели для {signal.ticker} получены, но позиции нет")
            await self.state.mark_message_processed(signal.message_id)
            return
        
        if trade.state == "MANAGING":
            logger.info(f"Trade {symbol} already has targets set")
            await self.state.mark_message_processed(signal.message_id)
            return
        
        # Update trade with targets
        await self.state.update_trade(
            symbol,
            targets=signal.targets,
            stop_price=signal.stop,
            target_msg_id=signal.message_id,
            state="MANAGING"
        )
        
        logger.info(f"Setting targets for {symbol}: {signal.targets}, stop={signal.stop}")
        
        # Place TP orders (limit orders, reduce-only)
        # Side for closing: 2=Close Short, 4=Close Long
        close_side = 2 if trade.side == "SHORT" else 4
        
        tp_volumes = self._calculate_tp_volumes(trade.volume, len(signal.targets))
        
        for i, (target_price, tp_vol) in enumerate(zip(signal.targets, tp_volumes)):
            if tp_vol <= 0:
                continue
            
            order_result = await self.client.submit_order(
                symbol=symbol,
                side=close_side,
                order_type=1,  # Limit
                price=target_price,
                vol=tp_vol,
                reduce_only=True
            )
            
            if order_result:
                order_id = order_result.get("orderId", "")
                await self.state.update_trade(symbol, tp_orders={**trade.tp_orders, i: order_id})
                logger.info(f"TP{i+1} order placed: {tp_vol} @ {target_price}")
        
        # Place stop loss (trigger market order)
        if signal.stop > 0:
            await self._place_stop_loss(trade, signal.stop)
        
        await self.notify(
            f"🎯 Цели установлены для {trade.ticker}\n"
            f"TP: {', '.join(f'{p}' for p in signal.targets)}\n"
            f"SL: {signal.stop}"
        )
        
        await self.state.mark_message_processed(signal.message_id)
    
    def _calculate_tp_volumes(self, total_volume: int, num_targets: int) -> List[int]:
        """
        Calculate volume for each TP based on TP_SPLIT ratios.
        Last TP takes the remainder after rounding.
        For more than 3 targets, distributes remainder equally.
        Ensures sum of volumes equals total_volume.
        """
        if num_targets == 0:
            return []
        
        # Always use all 3 ratios from TP_SPLIT, or extend for more targets
        if num_targets <= len(TP_SPLIT):
            # Use first N ratios and renormalize
            ratios = list(TP_SPLIT[:num_targets])
            ratio_sum = sum(ratios)
            ratios = [r / ratio_sum for r in ratios]
        else:
            # More targets than ratios - use all ratios + equal distribution of remainder
            ratios = list(TP_SPLIT)
            used_ratio = sum(ratios)
            remainder_ratio = 1.0 - used_ratio
            extra_ratio = remainder_ratio / (num_targets - len(ratios))
            ratios.extend([extra_ratio] * (num_targets - len(ratios)))
        
        volumes = []
        remaining = total_volume
        
        for i, ratio in enumerate(ratios):
            if i == len(ratios) - 1:
                # Last target gets whatever is left to ensure sum equals total
                vol = max(1, remaining)
            else:
                vol = max(1, int(total_volume * ratio))
                remaining -= vol
            
            volumes.append(vol)
        
        # Final adjustment to ensure sum exactly equals total_volume
        vol_sum = sum(volumes)
        while vol_sum > total_volume and len(volumes) > 1:
            # Reduce from the largest non-final volume
            for i in range(len(volumes) - 2, -1, -1):
                if volumes[i] > 1:
                    volumes[i] -= 1
                    vol_sum -= 1
                    break
            else:
                # If all earlier volumes are at minimum, reduce the last one
                if volumes[-1] > 1:
                    volumes[-1] -= 1
                    vol_sum -= 1
                else:
                    break
        
        while vol_sum < total_volume:
            # Add to the last volume
            volumes[-1] += 1
            vol_sum += 1
        
        return volumes
    
    async def _place_stop_loss(self, trade: ActiveTrade, stop_price: float) -> None:
        """Place or replace stop loss order."""
        # Cancel existing stop
        if trade.stop_order_id:
            await self.client.cancel_order(trade.symbol, trade.stop_order_id)
        
        # Side for closing: 2=Close Short, 4=Close Long
        close_side = 2 if trade.side == "SHORT" else 4
        
        # Place trigger stop-market order for remaining volume
        order_result = await self.client.submit_trigger_order(
            symbol=trade.symbol,
            side=close_side,
            trigger_price=stop_price,
            vol=trade.remaining_volume,
            reduce_only=True
        )
        
        if order_result:
            order_id = order_result.get("orderId", "")
            await self.state.update_trade(trade.symbol, stop_order_id=order_id)
            logger.info(f"Stop loss placed: {trade.remaining_volume} @ {stop_price}")
    
    async def _run_watcher(self) -> None:
        """Watch for TP/SL executions and manage orders."""
        while self._running:
            try:
                await asyncio.sleep(POLL_SEC)
                
                # Get all managing trades
                trades = await self.state.get_managing_trades()
                
                for trade in trades:
                    await self._check_trade_status(trade)
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Watcher error: {e}")
                await asyncio.sleep(5)
    
    async def _check_trade_status(self, trade: ActiveTrade) -> None:
        """Check status of a single trade and update accordingly."""
        symbol = trade.symbol
        
        # Get open orders
        open_orders = await self.client.get_open_orders(symbol)
        
        # Get current position
        pos_info = await self.client.get_position(symbol)
        current_vol = 0
        if pos_info and "data" in pos_info:
            data = pos_info["data"]
            if isinstance(data, list) and len(data) > 0:
                current_vol = int(float(data[0].get("vol", 0)))
        
        # Check which TPs have been filled
        filled_tps = []
        for i, order in enumerate(open_orders):
            order_id = order.get("orderId", "")
            # Check if this was one of our TP orders
            for tp_idx, tp_order_id in trade.tp_orders.items():
                if tp_order_id == order_id:
                    # Order still open
                    break
            else:
                # Order not in open orders, might be filled
                # We need to track filled TPs differently
                pass
        
        # Simpler approach: compare remaining volume
        if current_vol < trade.remaining_volume and current_vol > 0:
            # Some volume was closed
            closed_vol = trade.remaining_volume - current_vol
            logger.info(f"{symbol}: {closed_vol} closed, remaining={current_vol}")
            
            # Find which TP this corresponds to
            tp_volumes = self._calculate_tp_volumes(trade.volume, len(trade.targets))
            cumulative = 0
            for i, tp_vol in enumerate(tp_volumes):
                cumulative += tp_vol
                if i not in trade.filled_targets and cumulative >= (trade.volume - current_vol):
                    trade.filled_targets.append(i)
                    logger.info(f"TP{i+1} filled: {tp_vol} @ {trade.targets[i]}")
                    
                    await self.notify(
                        f"✅ TP{i+1} сработал для {trade.ticker}\n"
                        f"Цена: {trade.targets[i]}\n"
                        f"Закрыто: {tp_vol}\n"
                        f"Остаток: {current_vol}"
                    )
                    break
            
            # Update remaining volume
            await self.state.update_trade(symbol, remaining_volume=current_vol, filled_targets=trade.filled_targets)
            
            # Replace stop loss with new remaining volume
            if trade.stop_price > 0 and current_vol > 0:
                await self._place_stop_loss(trade, trade.stop_price)
        
        # Check if fully closed
        if current_vol == 0 and trade.volume > 0:
            logger.info(f"{symbol}: position fully closed")
            
            # Determine if closed by SL or all TPs
            if len(trade.filled_targets) >= len(trade.targets):
                reason = "все цели достигнуты"
            else:
                reason = "стоп-лосс или ручное закрытие"
            
            await self.notify(
                f"🏁 Позиция {trade.ticker} закрыта\n"
                f"Причина: {reason}\n"
                f"Вход: {trade.entry_price}\n"
                f"Заполнено ТП: {len(trade.filled_targets)}/{len(trade.targets)}"
            )
            
            await self.state.remove_trade(symbol)
