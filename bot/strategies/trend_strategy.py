import logging
import pandas as pd
import numpy as np
from typing import Dict, Optional, Any, List, Callable
import asyncio

from .base_strategy import BaseStrategy
# from bot.core.order_executor import OrderManager # Forward declared
# from bot.core.data_fetcher import MarketDataProvider # Forward declared
# from bot.core.risk_manager import BasicRiskManager # Forward declared

class TrendAdaptationStrategy(BaseStrategy):
    def __init__(self, strategy_id: str, params: Dict[str, Any], order_manager: Any,
                 market_data_provider: Any, risk_manager: Any, logger: Optional[logging.Logger] = None):
        super().__init__(strategy_id, params, order_manager, market_data_provider, risk_manager, logger)

        self.symbol = self.get_param('symbol', 'BTCUSDT')
        self.trend_configs: List[Dict[str, Any]] = self.get_param('trend_configs', [])

        self.market_regime: Dict[str, str] = {} # e.g., {'MA_1D': 'BULLISH', 'RSI_4H': 'NEUTRAL'}
        self.overall_market_regime: str = "INITIALIZING"

        # Store klines for each timeframe: {'1D': pd.DataFrame, '4h': pd.DataFrame}
        self.historical_data_dfs: Dict[str, pd.DataFrame] = {}
        # Min bars needed for each tf for indicators, e.g. {'1D': 50}
        self.min_history_needed: Dict[str, int] = {}
        # Max buffer length to keep for klines, e.g. {'1D': 200}
        self.max_buffer_length: Dict[str, int] = {}

        self._active_stream_handlers: List[Any] = [] # To keep references if needed for unsub

        if not self.trend_configs:
            self.logger.warning(f"[{self.strategy_id}] No trend_configs provided. Strategy will not operate.")
            self.is_active = False # Mark as inactive if no configs

        self.logger.info(f"[{self.strategy_id}] TrendAdaptationStrategy initialized with {len(self.trend_configs)} trend configs.")

    async def start(self):
        if not self.trend_configs: # Already checked in init, but double check
            self.logger.warning(f"[{self.strategy_id}] Cannot start: No trend_configs defined.")
            return

        await super().start() # Sets self.is_active = True
        self.logger.info(f"[{self.strategy_id}] TrendAdaptationStrategy starting...")

        for config in self.trend_configs:
            tf = config['timeframe']
            max_period = 0
            if config['type'] == "MA":
                max_period = max(config.get('short_period', 0), config.get('long_period', 0))
            elif config['type'] == "RSI":
                max_period = config.get('period', 0)

            if max_period == 0:
                self.logger.warning(f"[{self.strategy_id}] Max period is 0 for config {config['name']}. Min history cannot be determined accurately.")

            self.min_history_needed[tf] = max_period + 5 # Add buffer
            self.max_buffer_length[tf] = max_period * 3 + 10 # Keep more data for stability, e.g. 3x period + buffer

            if self.backtest_mode:
                # In backtest, data is pre-loaded by BacktestEngine. We need to initialize historical_data_dfs
                # with the relevant slice from the main historical_data of the BacktestEngine.
                # This strategy assumes BacktestEngine's timeframe matches one of its important TFs
                # or that it can access other TFs via market_data_provider.get_historical_klines.
                # For now, assume strategy will receive klines for all its configured TFs via on_kline_update.
                # The BacktestEngine currently only iterates one timeframe. This is a limitation.
                # For a multi-timeframe strategy in backtest, BacktestEngine would need to manage multiple data feeds
                # or this strategy would need to fetch other TFs itself using MDP on first relevant kline.
                self.historical_data_dfs[tf] = pd.DataFrame(columns=['open', 'high', 'low', 'close', 'volume']) # Init empty
                self.logger.info(f"[{self.strategy_id}] Backtest mode: Initialized empty DataFrame for {tf}. Will populate via on_kline_update.")

            else: # Live mode
                try:
                    self.logger.info(f"[{self.strategy_id}] Fetching initial historical klines for {config['name']} ({tf}), limit {self.max_buffer_length[tf]}...")
                    # Fetch enough data to calculate initial trend
                    initial_df = await self.market_data_provider.get_historical_klines(
                        symbol=self.symbol, interval=tf, limit=self.max_buffer_length[tf]
                    )
                    if initial_df is not None and not initial_df.empty:
                        self.historical_data_dfs[tf] = initial_df
                        await self._update_trend_for_config(config)
                    else:
                        self.logger.warning(f"[{self.strategy_id}] Could not fetch initial klines for {tf}. Trend for {config['name']} will be NEUTRAL.")
                        self.historical_data_dfs[tf] = pd.DataFrame(columns=['open', 'high', 'low', 'close', 'volume']) # Init empty
                        self.market_regime[config['name']] = "NEUTRAL"

                    # Subscribe to live klines for this timeframe
                    handler = self._create_kline_handler_for_config(config)
                    self._active_stream_handlers.append(handler) # Keep reference if needed for unsub
                    await self.market_data_provider.subscribe_to_kline_stream(
                        self.symbol, tf, handler
                    )
                    self.logger.info(f"[{self.strategy_id}] Subscribed to kline stream for {config['name']} ({tf}).")

                except Exception as e:
                    self.logger.error(f"[{self.strategy_id}] Error during start for config {config['name']}: {e}", exc_info=True)
                    self.historical_data_dfs[tf] = pd.DataFrame(columns=['open', 'high', 'low', 'close', 'volume'])
                    self.market_regime[config['name']] = "NEUTRAL_ERROR"


        await self._determine_overall_regime()
        self.logger.info(f"[{self.strategy_id}] TrendAdaptationStrategy started. Initial Overall Regime: {self.overall_market_regime}, Individual: {self.market_regime}")

    def _create_kline_handler_for_config(self, config: Dict) -> Callable[[Dict], asyncio.Task]:
        async def specific_kline_handler(kline_ws_data: Dict): # kline_ws_data is the raw message from WebSocket
            # self.logger.debug(f"Specific handler for {config['name']} received: {kline_ws_data}")
            # Extract actual kline data (usually in 'k' field if it's a kline event)
            # WebSocket kline data: {'e': 'kline', 'E': ..., 's': ..., 'k': {...kline_fields...}}
            if kline_ws_data.get('e') == 'kline':
                k_data = kline_ws_data.get('k')
                if k_data:
                    symbol = k_data['s']
                    interval = k_data['i']
                    if k_data.get('x'): # Process only closed candles
                        await self.on_kline_update(symbol, interval, k_data, source_config_name=config['name'])
            # In backtest, BacktestEngine passes the 'k' field directly as kline_data
            elif 't' in kline_ws_data and 'c' in kline_ws_data : # It's already a kline_data dict from backtester
                 if kline_ws_data.get('x'): # Process only closed candles
                    await self.on_kline_update(config.get('symbol', self.symbol), config['timeframe'], kline_ws_data, source_config_name=config['name'])


        return specific_kline_handler

    async def on_kline_update(self, symbol: str, interval: str, kline_data: Dict, source_config_name: Optional[str] = None):
        if not self.is_active or not source_config_name: return

        config_to_update = next((c for c in self.trend_configs if c['name'] == source_config_name and c['timeframe'] == interval), None)
        if not config_to_update:
            # self.logger.debug(f"[{self.strategy_id}] Kline update for {symbol}@{interval} doesn't match any config via source_config_name {source_config_name}.")
            return

        tf = config_to_update['timeframe']
        # self.logger.debug(f"[{self.strategy_id}] Processing kline for {source_config_name} ({tf}): C={kline_data['c']}")

        # Append new kline to the correct DataFrame
        new_kline_timestamp = pd.to_datetime(kline_data['t'], unit='ms', utc=True)
        new_kline_series = pd.Series({
            'open': float(kline_data['o']), 'high': float(kline_data['h']),
            'low': float(kline_data['l']), 'close': float(kline_data['c']),
            'volume': float(kline_data['v'])
            # ATR might be passed by backtester, or calculated here if needed
        }, name=new_kline_timestamp)

        if tf not in self.historical_data_dfs: # Should have been initialized in start()
            self.historical_data_dfs[tf] = pd.DataFrame(columns=['open', 'high', 'low', 'close', 'volume'])

        current_df = self.historical_data_dfs[tf]
        if new_kline_timestamp not in current_df.index: # Avoid duplicates
            current_df = pd.concat([current_df, new_kline_series.to_frame().T])
            if len(current_df) > self.max_buffer_length.get(tf, 200): # Manage buffer length
                current_df = current_df.iloc[-self.max_buffer_length.get(tf, 200):]
            self.historical_data_dfs[tf] = current_df

        await self._update_trend_for_config(config_to_update)
        await self._determine_overall_regime()


    async def _update_trend_for_config(self, config: Dict):
        tf = config['timeframe']
        df = self.historical_data_dfs.get(tf)
        config_name = config['name']

        min_hist = self.min_history_needed.get(tf, 2)
        if df is None or len(df) < min_hist:
            self.logger.debug(f"[{self.strategy_id}] Not enough data for {config_name} on {tf} (need {min_hist}, have {len(df) if df is not None else 0}). Trend set to NEUTRAL.")
            if self.market_regime.get(config_name) != "NEUTRAL_DATA_MISSING":
                 self.market_regime[config_name] = "NEUTRAL_DATA_MISSING" # Specific neutral state
            return

        trend = "NEUTRAL" # Default
        try:
            if config['type'] == "MA":
                short_ma = df['close'].rolling(window=config['short_period']).mean().iloc[-1]
                long_ma = df['close'].rolling(window=config['long_period']).mean().iloc[-1]
                if not np.isnan(short_ma) and not np.isnan(long_ma):
                    trend = "BULLISH" if short_ma > long_ma else "BEARISH"

            elif config['type'] == "RSI":
                period = config['period']
                delta = df['close'].diff(1)
                gain = delta.where(delta > 0, 0.0).fillna(0.0)
                loss = -delta.where(delta < 0, 0.0).fillna(0.0)

                avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
                avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()

                if not avg_gain.empty and not avg_loss.empty and not np.isnan(avg_gain.iloc[-1]) and not np.isnan(avg_loss.iloc[-1]):
                    if avg_loss.iloc[-1] == 0:
                        current_rsi = 100.0 if avg_gain.iloc[-1] > 0 else 50.0
                    else:
                        rs = avg_gain.iloc[-1] / avg_loss.iloc[-1]
                        current_rsi = 100.0 - (100.0 / (1.0 + rs))

                    if not np.isnan(current_rsi):
                        if current_rsi > config['bull_level']: trend = "BULLISH"
                        elif current_rsi < config['bear_level']: trend = "BEARISH"
                else:
                    trend = "NEUTRAL_CALC_ERROR" # Indicate data was there but calc failed (e.g. all NaNs)
        except Exception as e:
            self.logger.error(f"[{self.strategy_id}] Error calculating trend for {config_name}: {e}", exc_info=True)
            trend = "NEUTRAL_ERROR"

        if self.market_regime.get(config_name) != trend:
            self.logger.info(f"[{self.strategy_id}] Trend update for {config_name} ({tf}): From {self.market_regime.get(config_name, 'N/A')} To {trend}")
            self.market_regime[config_name] = trend


    async def _determine_overall_regime(self):
        old_overall_regime = self.overall_market_regime

        # Example simplified logic:
        # Prioritize longer timeframes. If mixed, can be neutral or based on shorter TFs.
        # This logic can be made much more sophisticated.
        daily_trends = [v for k, v in self.market_regime.items() if "1D" in k and isinstance(v, str)]
        h4_trends = [v for k, v in self.market_regime.items() if "4h" in k and isinstance(v, str)]
        h1_trends = [v for k, v in self.market_regime.items() if "1h" in k and isinstance(v, str)]

        if any("BULLISH" in t for t in daily_trends): self.overall_market_regime = "MACRO_BULL"
        elif any("BEARISH" in t for t in daily_trends): self.overall_market_regime = "MACRO_BEAR"
        elif any("BULLISH" in t for t in h4_trends): self.overall_market_regime = "MID_BULL"
        elif any("BEARISH" in t for t in h4_trends): self.overall_market_regime = "MID_BEAR"
        elif any("BULLISH" in t for t in h1_trends): self.overall_market_regime = "SHORT_BULL"
        elif any("BEARISH" in t for t in h1_trends): self.overall_market_regime = "SHORT_BEAR"
        else: self.overall_market_regime = "NEUTRAL_MIXED"

        # More nuanced:
        # if daily_bull and (h4_bull or h1_bull or h4_neutral or h1_neutral): regime = "STRONG_BULL_TREND"
        # if daily_bull and h4_bear and h1_bear: regime = "BULL_MACRO_CORRECTION_BEAR_MICRO"
        # etc.

        if old_overall_regime != self.overall_market_regime:
             self.logger.info(f"[{self.strategy_id}] Overall Market Regime changed from {old_overall_regime} to: {self.overall_market_regime} (Based on: {self.market_regime})")
             # Here, this strategy could potentially call methods on StrategyEngine
             # to influence other strategies, or other strategies could query this one.

    # This strategy does not place orders directly
    async def on_depth_update(self, symbol: str, depth_data: Dict): pass
    async def on_trade_update(self, symbol: str, trade_data: Dict): pass
    async def on_mark_price_update(self, symbol: str, mark_price_data: Dict): pass
    async def on_order_update(self, order_update: Dict): pass # Not managing its own orders

```
