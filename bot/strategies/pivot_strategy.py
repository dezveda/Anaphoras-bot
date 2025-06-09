import logging
import pandas as pd
from typing import Dict, Optional, Any
import asyncio

from .base_strategy import BaseStrategy
# from bot.core.order_executor import OrderManager # Forward declared in BaseStrategy
# from bot.core.data_fetcher import MarketDataProvider # Forward declared in BaseStrategy
# from bot.core.risk_manager import BasicRiskManager # Forward declared in BaseStrategy

class PivotPointStrategy(BaseStrategy):
    def __init__(self, strategy_id: str, params: Dict[str, Any], order_manager: Any,
                 market_data_provider: Any, risk_manager: Any, logger: Optional[logging.Logger] = None):
        super().__init__(strategy_id, params, order_manager, market_data_provider, risk_manager, logger)

        self.pivot_period_tf = self.get_param('pivot_period_tf', '1D')
        self.pivot_points: Dict[str, float] = {}
        self.atr_value: Optional[float] = None

        self.pivot_formula = self.get_param('pivot_formula', 'classic')
        self.trade_type = self.get_param('trade_type', 'rebound') # 'rebound', 'breakout', 'both'

        self.stop_loss_atr_multiplier = float(self.get_param('stop_loss_atr_multiplier', 1.5)) # Adjusted default
        self.take_profit_atr_multiplier = float(self.get_param('take_profit_atr_multiplier', 2.0)) # Adjusted default

        # 'order_quantity_usd' is removed, quantity will be derived from risk_manager
        self.default_risk_per_trade_perc = float(self.get_param('default_risk_per_trade_perc', 0.01)) # 1% risk per trade
        self.asset_quantity_precision = int(self.get_param('asset_quantity_precision', 3))
        self.asset_price_precision = int(self.get_param('asset_price_precision', 2))

        self.last_kline_close_time_ms = 0 # Used for pivot recalculation timing
        self.symbol = self.get_param('symbol', "BTCUSDT")
        self.trade_interval = self.get_param('trade_interval', "1h")

        self.data_buffer_size = int(self.get_param('data_buffer_size_for_pivots', 2)) # Need at least 2 for prev HLC
        self.kline_data_buffer: pd.DataFrame = pd.DataFrame() # Simpler buffer for this strategy

        self.logger.info(f"[{self.strategy_id}] PivotPointStrategy initialized. Symbol: {self.symbol}, Trade Interval: {self.trade_interval}, Pivot TF: {self.pivot_period_tf}")

    async def start(self):
        await super().start()
        if not self.backtest_mode:
            await self.market_data_provider.subscribe_to_kline_stream(
                self.symbol, self.trade_interval,
                lambda data: asyncio.create_task(self.on_kline_update(self.symbol, self.trade_interval, data))
            )
        # Initial pivot calculation will happen on first kline update if needed

    async def stop(self):
        await super().stop()
        # Unsubscribe logic would go here if subscriptions were managed by strategy directly
        # For now, MarketDataProvider might handle global unsubscriptions or StrategyEngine does.

    def _add_to_buffer(self, kline_data: Dict):
        new_kline_series = pd.Series({
            'open': float(kline_data['o']), 'high': float(kline_data['h']),
            'low': float(kline_data['l']), 'close': float(kline_data['c']),
            'volume': float(kline_data['v']),
            'close_time': pd.to_datetime(kline_data['T'], unit='ms', utc=True)
        }, name=pd.to_datetime(kline_data['t'], unit='ms', utc=True))

        self.kline_data_buffer = pd.concat([self.kline_data_buffer, new_kline_series.to_frame().T])
        if len(self.kline_data_buffer) > self.data_buffer_size:
            self.kline_data_buffer = self.kline_data_buffer.iloc[-self.data_buffer_size:]

    async def on_kline_update(self, symbol: str, interval: str, kline_data: Dict):
        if not self.is_active or symbol != self.symbol or interval != self.trade_interval: return

        current_kline_open_time_ms = int(kline_data['t'])
        self.atr_value = float(kline_data.get('atr', 0.0))
        if self.atr_value <= 1e-8: # Check for zero or very small ATR
            self.logger.warning(f"[{self.strategy_id}] ATR value ({self.atr_value}) is zero or too small at {pd.to_datetime(current_kline_open_time_ms, unit='ms', utc=True)}. Using fallback or skipping logic.")
            # Fallback: 0.5% of close price, or skip. For now, let it be small, SL/TP logic will handle it.
            # self.atr_value = float(kline_data['c']) * 0.005

        self._add_to_buffer(kline_data)

        if not self.pivot_points or self._is_new_pivot_period(current_kline_open_time_ms):
            await self._calculate_pivot_points()

        if not self.pivot_points:
            self.logger.debug(f"[{self.strategy_id}] Pivot points not yet available. Kline time: {pd.to_datetime(current_kline_open_time_ms, unit='ms', utc=True)}")
            return

        await self._check_pivot_signals(kline_data)

    def _is_new_pivot_period(self, current_kline_open_time_ms: int) -> bool:
        # This needs robust logic depending on self.pivot_period_tf and current_kline_open_time_ms
        # For '1D' pivots, it's a new day (UTC).
        if self.last_kline_close_time_ms == 0: # First run
            return True

        prev_dt = pd.to_datetime(self.last_kline_close_time_ms, unit='ms', utc=True)
        curr_dt = pd.to_datetime(current_kline_open_time_ms, unit='ms', utc=True)

        if self.pivot_period_tf == '1D':
            if curr_dt.date() > prev_dt.date(): return True
        # Add more for '1W', '1M' if needed
        return False

    async def _calculate_pivot_points(self):
        self.logger.debug(f"[{self.strategy_id}] Attempting to calculate pivot points.")
        # Needs HLC of the *previous* pivot_period_tf.
        # This is tricky for live data without specific historical fetch for this.
        # In backtest, BacktestEngine could provide this, or strategy fetches.
        # For now, using the kline_data_buffer if it's populated enough (e.g. for daily pivots from hourly data)

        # This placeholder uses the second to last kline from the *trade_interval* buffer.
        # This is only a rough proxy and not standard for pivot points based on a larger TF.
        # A proper implementation would fetch, e.g., yesterday's daily HLC if pivot_period_tf='1D'.
        if len(self.kline_data_buffer) < 2:
            self.logger.warning(f"[{self.strategy_id}] Not enough data in buffer ({len(self.kline_data_buffer)}) to estimate prev period HLC for pivots.")
            self.pivot_points = {} # Clear existing if any
            return

        # Using the second to last kline in the buffer as a proxy for "previous period"
        # This is a simplification and would need to be made robust for live trading.
        prev_kline = self.kline_data_buffer.iloc[-2]
        high_prev, low_prev, close_prev = prev_kline['high'], prev_kline['low'], prev_kline['close']

        if self.pivot_formula == 'classic':
            pp = (high_prev + low_prev + close_prev) / 3
            self.pivot_points = {
                'PP': pp, 'R1': (2 * pp) - low_prev, 'S1': (2 * pp) - high_prev,
                'R2': pp + (high_prev - low_prev), 'S2': pp - (high_prev - low_prev),
                'R3': high_prev + 2 * (pp - low_prev), 'S3': low_prev - 2 * (high_prev - pp)
            }
            self.logger.info(f"[{self.strategy_id}] Calculated Classic Pivots for period ending ~{prev_kline.name}: { {k: round(v, self.asset_price_precision) for k,v in self.pivot_points.items()} }")
            self.last_kline_close_time_ms = int(prev_kline.name.timestamp() * 1000) # Update based on data used for pivot
        else:
            self.logger.warning(f"[{self.strategy_id}] Pivot formula '{self.pivot_formula}' not implemented yet.")
            self.pivot_points = {}


    async def _check_pivot_signals(self, kline: Dict):
        current_price = float(kline['c'])
        # Simplified example: only check PP for rebound
        pp = self.pivot_points.get('PP')
        if pp is None: return

        # Example: Long if price bounces off PP from below
        # This needs more sophisticated entry logic (e.g. confirmation, price action)
        if self.trade_type in ['rebound', 'both']:
            is_near_pp = abs(current_price - pp) < (self.atr_value or current_price * 0.001) * 0.25 # Price is "near" PP

            # This is a very basic signal, needs refinement.
            # Example: if price was below PP and now closes above PP (or near it after touching)
            # For now, let's assume a simple touch and potential entry logic
            if is_near_pp: # Placeholder for more robust signal logic
                self.logger.info(f"[{self.strategy_id}] Price {current_price} near PP {pp:.{self.asset_price_precision}f}. Evaluating trade.")
                # Example: if last kline low touched PP and closed higher -> Buy signal
                # For now, just a placeholder for entry, focusing on RiskManager integration
                # await self._enter_position(self.symbol, "BUY", current_price, pp, "pp_rebound_long")


    async def _enter_position(self, symbol: str, side: str, entry_price_estimate: float,
                              trigger_level_price: float, signal_type: str): # trigger_level_price is the pivot level
        if not self.risk_manager: self.logger.error(f"[{self.strategy_id}] RiskManager not available."); return
        if not self.is_active: self.logger.info(f"[{self.strategy_id}] Strategy not active, skipping trade."); return

        # Position side for hedge mode if applicable (not fully handled here yet)
        position_side = "LONG" if side == "BUY" else "SHORT"

        sl_atr_offset_val = 0.0
        if self.atr_value and self.atr_value > 1e-8: # Ensure ATR is positive and non-zero
            sl_atr_offset_val = self.atr_value * self.stop_loss_atr_multiplier
        else:
            self.logger.warning(f"[{self.strategy_id}] Invalid ATR ({self.atr_value}) for SL. Using fallback % of entry price.")
            sl_atr_offset_val = entry_price_estimate * (0.01 * self.stop_loss_atr_multiplier) # e.g. 1% * multiplier

        if side == "BUY":
            sl_price = round(entry_price_estimate - sl_atr_offset_val, self.asset_price_precision)
        else: # SELL
            sl_price = round(entry_price_estimate + sl_atr_offset_val, self.asset_price_precision)

        risk_capital_usd = await self.risk_manager.calculate_position_size_usd(risk_per_trade_perc=self.default_risk_per_trade_perc)
        if not risk_capital_usd or risk_capital_usd <= 0:
            self.logger.warning(f"[{self.strategy_id}] RiskManager: Zero or invalid risk capital USD ({risk_capital_usd}). Cannot place trade."); return

        quantity_asset = self.risk_manager.calculate_quantity_from_risk_usd(
            position_size_usd=risk_capital_usd, entry_price=entry_price_estimate, stop_loss_price=sl_price,
            quantity_precision=self.asset_quantity_precision,
            min_quantity=float(self.get_param('min_order_qty', 0.001)) # Get min_qty from params or default
        )

        if not quantity_asset or quantity_asset <= 0:
            self.logger.warning(f"[{self.strategy_id}] RiskManager: Zero or invalid quantity ({quantity_asset}) for USD risk {risk_capital_usd}. SL too close or risk too small. Entry: {entry_price_estimate}, SL: {sl_price}"); return

        self.logger.info(f"[{self.strategy_id} - {signal_type}] Attempting MARKET {side} order for {symbol}. Qty: {quantity_asset}, EntryEst: {entry_price_estimate:.{self.asset_price_precision}f}, SL: {sl_price:.{self.asset_price_precision}f}")

        order_response = await self._place_market_order(symbol, side, quantity_asset, positionSide=position_side)
        if order_response and order_response.get('status') == 'FILLED':
            self.logger.info(f"[{self.strategy_id}] Position entered via {signal_type}: {order_response}")
            # TODO: Manage SL/TP orders (e.g., place OCO or separate SL/TP limit orders)
        else:
            self.logger.error(f"[{self.strategy_id}] Failed to enter position via {signal_type}: {order_response}")

    async def on_depth_update(self, symbol: str, depth_data: Dict): pass
    async def on_trade_update(self, symbol: str, trade_data: Dict): pass
    async def on_mark_price_update(self, symbol: str, mark_price_data: Dict): pass # Relevant for SL/TP execution in live
    async def on_order_update(self, order_update: Dict):
        client_order_id = order_update.get('c', '')
        if client_order_id.startswith(self.strategy_id):
            self.logger.info(f"[{self.strategy_id}] Own order update: ClientOID={client_order_id}, Status={order_update.get('X')}, Symbol={order_update.get('s')}")
```
