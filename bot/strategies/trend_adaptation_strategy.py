import logging
import pandas as pd
import numpy as np
from typing import Dict, Optional, Any, List
import asyncio

from .base_strategy import BaseStrategy
OrderManager = Any
MarketDataProvider = Any
BasicRiskManager = Any

class TrendAdaptationStrategy(BaseStrategy):
    strategy_type_name: str = "TrendAdaptationStrategy"

    def __init__(self, strategy_id: str, params: Dict[str, Any],
                 order_manager: OrderManager,
                 market_data_provider: MarketDataProvider,
                 risk_manager: BasicRiskManager,
                 logger: Optional[logging.Logger] = None):
        super().__init__(strategy_id, params, order_manager, market_data_provider, risk_manager, logger)

        self.symbol: str = self.get_param('symbol', 'BTCUSDT')
        self.macro_tf: str = self.get_param('macro_timeframe', '1D')
        self.macro_sma_period: int = int(self.get_param('macro_sma_period', 50))
        self.micro_tf: str = self.get_param('micro_timeframe', '4h')
        self.micro_ema_short_period: int = int(self.get_param('micro_ema_short_period', 12))
        self.micro_ema_long_period: int = int(self.get_param('micro_ema_long_period', 26))

        self.market_regime: str = "UNDEFINED"
        self.macro_klines_df = pd.DataFrame(columns=['open', 'high', 'low', 'close', 'volume'])
        self.micro_klines_df = pd.DataFrame(columns=['open', 'high', 'low', 'close', 'volume'])
        self.last_macro_sma: Optional[float] = None
        self.last_micro_ema_short: Optional[float] = None
        self.last_micro_ema_long: Optional[float] = None

        self.min_klines_for_macro: int = self.macro_sma_period + 50
        self.min_klines_for_micro: int = self.micro_ema_long_period + 50

        self.logger.info(f"[{self.strategy_id}] {self.strategy_type_name} initialized. Macro: {self.macro_tf} SMA({self.macro_sma_period}), Micro: {self.micro_tf} EMA({self.micro_ema_short_period}/{self.micro_ema_long_period})")

    @staticmethod
    def get_default_params() -> dict:
        return {
            'symbol': {'type': 'str', 'default': 'BTCUSDT', 'desc': 'Trading symbol for trend analysis.'},
            'macro_timeframe': {'type': 'str', 'default': '1D', 'options': ['6h', '12h', '1D', '3D', '1W'], 'desc': 'Timeframe for macro trend analysis.'},
            'macro_sma_period': {'type': 'int', 'default': 50, 'min': 10, 'max': 200, 'desc': 'SMA period for macro trend.'},
            'micro_timeframe': {'type': 'str', 'default': '4h', 'options': ['1h', '2h', '4h', '6h'], 'desc': 'Timeframe for micro trend/correction analysis.'},
            'micro_ema_short_period': {'type': 'int', 'default': 12, 'min': 5, 'max': 50, 'desc': 'Short EMA period for micro trend.'},
            'micro_ema_long_period': {'type': 'int', 'default': 26, 'min': 10, 'max': 100, 'desc': 'Long EMA period for micro trend.'},
            # This strategy doesn't trade, so no trade-specific params like risk, precision etc.
        }

    async def start(self):
        await super().start()
        self.strategy_type_name = self.__class__.strategy_type_name # Set instance type name

        if self.backtest_mode:
            self.logger.info(f"[{self.strategy_id}] Backtest mode: Initial klines will be fed by BacktestEngine.")
        else:
            self.logger.info(f"[{self.strategy_id}] Live mode: Fetching initial klines...")
            try:
                macro_data = await self.market_data_provider.get_historical_klines(self.symbol, self.macro_tf, limit=self.min_klines_for_macro)
                if not macro_data.empty: self.macro_klines_df = macro_data[['open', 'high', 'low', 'close', 'volume']].copy()

                micro_data = await self.market_data_provider.get_historical_klines(self.symbol, self.micro_tf, limit=self.min_klines_for_micro)
                if not micro_data.empty: self.micro_klines_df = micro_data[['open', 'high', 'low', 'close', 'volume']].copy()

                self._update_macro_trend_indicators()
                self._update_micro_trend_indicators()
                self._determine_market_regime()

                await self.market_data_provider.subscribe_to_kline_stream(self.symbol, self.macro_tf, self._handle_macro_kline_wrapper)
                await self.market_data_provider.subscribe_to_kline_stream(self.symbol, self.micro_tf, self._handle_micro_kline_wrapper)
            except Exception as e:
                 self.logger.error(f"[{self.strategy_id}] Error during live mode start sequence: {e}", exc_info=True)
                 self.is_active = False # Prevent further processing if setup fails
                 return # Do not proceed if initial data fetch or subscription fails

        self.logger.info(f"[{self.strategy_id}] {self.strategy_type_name} started. Initial regime: {self.market_regime}")

    async def _handle_kline_wrapper(self, raw_ws_message: dict, tf_type: str):
        # ... (implementation from previous step, ensure kline_payload is correctly extracted)
        kline_payload = raw_ws_message.get('data', raw_ws_message).get('k')
        if not kline_payload: self.logger.warning(f"[{self.strategy_id}] WS {tf_type} kline message missing 'k': {raw_ws_message}"); return
        if not kline_payload.get('x'): return # Process only closed klines

        df_to_update_attr = "macro_klines_df" if tf_type == "macro" else "micro_klines_df"
        current_df = getattr(self, df_to_update_attr)
        min_len_for_indicator = self.macro_sma_period if tf_type == "macro" else self.micro_ema_long_period
        buffer_limit = self.min_klines_for_macro if tf_type == "macro" else self.min_klines_for_micro

        new_kline_timestamp = pd.to_datetime(kline_payload['t'], unit='ms', utc=True)
        new_kline_series = pd.Series({
            'open': float(kline_payload['o']), 'high': float(kline_payload['h']),
            'low': float(kline_payload['l']), 'close': float(kline_payload['c']),
            'volume': float(kline_payload['v'])}, name=new_kline_timestamp)

        if new_kline_timestamp not in current_df.index:
            updated_df = pd.concat([current_df, new_kline_series.to_frame().T])
        else: # Update existing row (can happen if messages overlap or in some backtest scenarios)
            updated_df = current_df.copy()
            updated_df.loc[new_kline_timestamp] = new_kline_series

        if len(updated_df) > buffer_limit: updated_df = updated_df.iloc[-buffer_limit:]
        setattr(self, df_to_update_attr, updated_df)

        if len(updated_df) >= min_len_for_indicator:
            if tf_type == "macro": self._update_macro_trend_indicators()
            else: self._update_micro_trend_indicators()
        self._determine_market_regime()


    async def _handle_macro_kline_wrapper(self, raw_ws_message: dict): await self._handle_kline_wrapper(raw_ws_message, "macro")
    async def _handle_micro_kline_wrapper(self, raw_ws_message: dict): await self._handle_kline_wrapper(raw_ws_message, "micro")

    def _update_macro_trend_indicators(self):
        # ... (implementation from previous step)
        if len(self.macro_klines_df) >= self.macro_sma_period:
            self.last_macro_sma = self.macro_klines_df['close'].rolling(window=self.macro_sma_period).mean().iloc[-1]
        else: self.last_macro_sma = None


    def _update_micro_trend_indicators(self):
        # ... (implementation from previous step)
        if len(self.micro_klines_df) >= self.micro_ema_long_period:
            self.last_micro_ema_short = self.micro_klines_df['close'].ewm(span=self.micro_ema_short_period, adjust=False).mean().iloc[-1]
            self.last_micro_ema_long = self.micro_klines_df['close'].ewm(span=self.micro_ema_long_period, adjust=False).mean().iloc[-1]
        else: self.last_micro_ema_short = None; self.last_micro_ema_long = None


    def _determine_market_regime(self):
        # ... (implementation from previous step, ensure logging uses self.logger)
        new_regime = "UNDEFINED"
        current_macro_price = self.macro_klines_df['close'].iloc[-1] if not self.macro_klines_df.empty and 'close' in self.macro_klines_df.columns else None
        current_micro_price = self.micro_klines_df['close'].iloc[-1] if not self.micro_klines_df.empty and 'close' in self.micro_klines_df.columns else None
        macro_is_bull, macro_is_bear, macro_is_neutral = None, None, None

        if self.last_macro_sma and current_macro_price:
            if abs(current_macro_price - self.last_macro_sma) < (self.last_macro_sma * 0.005): macro_is_neutral = True
            else: macro_is_bull = current_macro_price > self.last_macro_sma; macro_is_bear = current_macro_price < self.last_macro_sma

        if macro_is_bull is None and macro_is_bear is None and macro_is_neutral is None: new_regime = "AWAITING_MACRO_DATA"; # Guard
        elif self.last_micro_ema_short is None or self.last_micro_ema_long is None or current_micro_price is None:
            if macro_is_bull: new_regime = "MACRO_BULL/MICRO_DATA_PENDING"
            elif macro_is_bear: new_regime = "MACRO_BEAR/MICRO_DATA_PENDING"
            else: new_regime = "MACRO_CONSOLIDATION/MICRO_DATA_PENDING"
        else: # Both macro and micro indicators are available
            micro_is_bull_trend = self.last_micro_ema_short > self.last_micro_ema_long
            micro_is_bear_trend = self.last_micro_ema_short < self.last_micro_ema_long
            micro_price_above_short_ema = current_micro_price > self.last_micro_ema_short
            micro_price_below_short_ema = current_micro_price < self.last_micro_ema_short

            if macro_is_bull:
                if micro_is_bull_trend and micro_price_above_short_ema : new_regime = "MACRO_BULL/MICRO_BULL_TREND"
                elif micro_is_bear_trend and micro_price_below_short_ema: new_regime = "MACRO_BULL/MICRO_BEAR_CORRECTION"
                else: new_regime = "MACRO_BULL/MICRO_CONSOLIDATION"
            elif macro_is_bear:
                if micro_is_bear_trend and micro_price_below_short_ema: new_regime = "MACRO_BEAR/MICRO_BEAR_TREND"
                elif micro_is_bull_trend and micro_price_above_short_ema: new_regime = "MACRO_BEAR/MICRO_BULL_CORRECTION"
                else: new_regime = "MACRO_BEAR/MICRO_CONSOLIDATION"
            elif macro_is_neutral:
                 new_regime = "MACRO_CONSOLIDATION"
                 if micro_is_bull_trend: new_regime += "/MICRO_BULL_ATTEMPT"
                 elif micro_is_bear_trend: new_regime += "/MICRO_BEAR_ATTEMPT"
                 else: new_regime += "/MICRO_CONSOLIDATION"

        if new_regime != self.market_regime:
            self.market_regime = new_regime
            self.logger.info(f"[{self.strategy_id}] Market regime changed to: {self.market_regime}")
        return self.market_regime


    def get_current_market_regime(self) -> str: return self.market_regime
    async def on_kline_update(self, symbol: str, interval: str, kline_data: Dict): # Called by BacktestEngine
        if not self.is_active: return
        tf_type = None
        if symbol == self.symbol and interval == self.macro_tf: tf_type = "macro"
        elif symbol == self.symbol and interval == self.micro_tf: tf_type = "micro"
        if tf_type: await self._handle_kline_wrapper({'data': {'k': kline_data}}, tf_type) # Simulate WS message structure

    async def on_depth_update(self, symbol: str, depth_data: Dict): pass
    async def on_trade_update(self, symbol: str, trade_data: Dict): pass
    async def on_mark_price_update(self, symbol: str, mark_price_data: Dict): pass
    async def on_order_update(self, order_update: Dict): pass
```
