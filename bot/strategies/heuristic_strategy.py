import logging
import pandas as pd
import numpy as np
from typing import Dict, Optional, Any, List, Callable
import asyncio

from .base_strategy import BaseStrategy
# Forward declared in BaseStrategy: OrderManager, MarketDataProvider, BasicRiskManager

class IndicatorHeuristicStrategy(BaseStrategy):
    def __init__(self, strategy_id: str, params: Dict[str, Any], order_manager: Any,
                 market_data_provider: Any, risk_manager: Any, logger: Optional[logging.Logger] = None):
        super().__init__(strategy_id, params, order_manager, market_data_provider, risk_manager, logger)

        self.symbol = self.get_param('symbol', 'BTCUSDT')
        self.trade_timeframe = self.get_param('trade_timeframe', '1h')

        self.indicator_configs: List[Dict[str, Any]] = self.get_param('indicator_configs', [])
        self.heuristic_logic: Dict[str, Any] = self.get_param('heuristic_logic',
                                                              {'type': 'score', 'buy_threshold': 2, 'sell_threshold': -2})

        self.historical_klines_df = pd.DataFrame(columns=['open', 'high', 'low', 'close', 'volume', 'atr'])
        self.indicator_values: Dict[str, Any] = {} # Stores latest values of all configured indicators
        self.current_score: float = 0.0

        self.current_position: Optional[Dict[str, Any]] = None # {'side': 'LONG'/'SHORT', 'entry_price': float, ...}
        self.atr_value: Optional[float] = None

        self.default_risk_per_trade_perc = float(self.get_param('default_risk_per_trade_perc', 0.01))
        self.sl_atr_multiplier = float(self.get_param('sl_atr_multiplier', 1.5))
        self.tp_rr_ratio = float(self.get_param('tp_rr_ratio', 2.0))
        self.asset_quantity_precision = int(self.get_param('asset_quantity_precision', 3))
        self.asset_price_precision = int(self.get_param('asset_price_precision', 2))
        self.min_trade_qty = float(self.get_param('min_trade_qty', 0.001))

        self.min_history_bars = self._calculate_min_history_needed()
        self.max_buffer_len = self.min_history_bars + int(self.get_param('buffer_extra_bars', 50))

        self.logger.info(f"[{self.strategy_id}] IndicatorHeuristicStrategy initialized. Min history: {self.min_history_bars}, Logic: {self.heuristic_logic['type']}")

    def _calculate_min_history_needed(self) -> int:
        max_period = 0
        for config in self.indicator_configs:
            if config['type'] in ["RSI", "SMA", "EMA"]:
                max_period = max(max_period, config.get('period', 0))
            elif config['type'] == "EMA_CROSS":
                max_period = max(max_period, config.get('short_period', 0), config.get('long_period', 0))
        return max_period if max_period > 0 else 20 # Default if no period found

    async def start(self):
        await super().start()
        if not self.indicator_configs:
            self.logger.warning(f"[{self.strategy_id}] No indicator_configs. Strategy will not be able to generate signals.")
            self.is_active = False
            return

        if self.backtest_mode:
            # Data is fed by BacktestEngine's on_kline_update. Initial calc will happen on first few klines.
            pass
        else: # Live mode
            # Fetch initial historical klines
            self.logger.info(f"[{self.strategy_id}] Fetching initial {self.max_buffer_len} klines for {self.symbol}@{self.trade_timeframe}...")
            initial_df = await self.market_data_provider.get_historical_klines(
                self.symbol, self.trade_timeframe, limit=self.max_buffer_len
            )
            if initial_df is not None and not initial_df.empty:
                self.historical_klines_df = pd.concat([self.historical_klines_df, initial_df])
                self.historical_klines_df = self.historical_klines_df[~self.historical_klines_df.index.duplicated(keep='last')]
                if len(self.historical_klines_df) >= self.min_history_bars:
                    await self._calculate_all_indicators()
                    await self._apply_heuristic_logic() # Apply initial logic
            else:
                self.logger.warning(f"[{self.strategy_id}] Could not fetch initial klines. Some indicators might not be available initially.")

            # Subscribe to live klines
            await self.market_data_provider.subscribe_to_kline_stream(
                self.symbol, self.trade_timeframe,
                lambda data: asyncio.create_task(self.on_kline_update(self.symbol, self.trade_timeframe, data))
            )
        self.logger.info(f"[{self.strategy_id}] IndicatorHeuristicStrategy started.")

    async def on_kline_update(self, symbol: str, interval: str, kline_data: Dict):
        if not self.is_active or symbol != self.symbol or interval != self.trade_timeframe or not kline_data.get('x'): # x = is_closed
            return

        new_kline_timestamp = pd.to_datetime(kline_data['t'], unit='ms', utc=True)
        new_kline_series = pd.Series({
            'open': float(kline_data['o']), 'high': float(kline_data['h']),
            'low': float(kline_data['l']), 'close': float(kline_data['c']),
            'volume': float(kline_data['v']),
            'atr': float(kline_data.get('atr', 0.0)) # Provided by BacktestEngine
        }, name=new_kline_timestamp)

        if new_kline_timestamp not in self.historical_klines_df.index:
            self.historical_klines_df = pd.concat([self.historical_klines_df, new_kline_series.to_frame().T])
            if len(self.historical_klines_df) > self.max_buffer_len:
                self.historical_klines_df = self.historical_klines_df.iloc[-self.max_buffer_len:]
        else: # Update the existing kline if it's not a new one (should not happen with 'x':True)
            self.historical_klines_df.loc[new_kline_timestamp] = new_kline_series

        self.atr_value = float(kline_data.get('atr', 0.0))
        if self.atr_value <= 1e-8 : self.logger.debug(f"[{self.strategy_id}] ATR is zero/unavailable.")

        await self._calculate_all_indicators()
        await self._apply_heuristic_logic()

        if self.current_position:
            await self._check_sl_tp(float(kline_data['c']))

    def _calculate_rsi(self, series: pd.Series, period: int) -> Optional[float]:
        if len(series) < period + 1: return None
        delta = series.diff(1)
        gain = delta.where(delta > 0, 0.0).fillna(0.0)
        loss = -delta.where(delta < 0, 0.0).fillna(0.0)
        avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
        avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
        if avg_loss.iloc[-1] == 0: return 100.0 if avg_gain.iloc[-1] > 0 else 50.0
        rs = avg_gain.iloc[-1] / avg_loss.iloc[-1]
        return 100.0 - (100.0 / (1.0 + rs))

    def _calculate_sma(self, series: pd.Series, period: int) -> Optional[float]:
        if len(series) < period: return None
        return series.rolling(window=period).mean().iloc[-1]

    def _calculate_ema(self, series: pd.Series, period: int) -> Optional[float]:
        if len(series) < period: return None # EWM can produce with less, but often better to wait for period
        return series.ewm(span=period, adjust=False, min_periods=period).mean().iloc[-1]

    async def _calculate_all_indicators(self):
        if self.historical_klines_df.empty: return

        for config in self.indicator_configs:
            name = config['name']
            indicator_type = config['type']

            if len(self.historical_klines_df) < self.min_history_bars: # Global check
                self.indicator_values[name] = None; continue

            series_close = self.historical_klines_df['close']
            value = None
            try:
                if indicator_type == "RSI":
                    value = self._calculate_rsi(series_close, config['period'])
                elif indicator_type == "SMA":
                    value = self._calculate_sma(series_close, config['period'])
                elif indicator_type == "EMA":
                    value = self._calculate_ema(series_close, config['period'])
                elif indicator_type == "EMA_CROSS":
                    ema_short = self._calculate_ema(series_close, config['short_period'])
                    ema_long = self._calculate_ema(series_close, config['long_period'])

                    # Need previous values for cross detection
                    if len(series_close) >= max(config['short_period'], config['long_period']) + 1 and ema_short is not None and ema_long is not None:
                        prev_short_ema = self._calculate_ema(series_close.iloc[:-1], config['short_period'])
                        prev_long_ema = self._calculate_ema(series_close.iloc[:-1], config['long_period'])

                        if prev_short_ema is not None and prev_long_ema is not None:
                            if ema_short > ema_long and prev_short_ema <= prev_long_ema: value = 1  # Bullish cross
                            elif ema_short < ema_long and prev_short_ema >= prev_long_ema: value = -1 # Bearish cross
                            else: value = 0 # No cross
                        else: value = 0 # Not enough data for prev EMAs
                    else: value = 0 # Not enough data

                self.indicator_values[name] = value
            except Exception as e:
                self.logger.error(f"Error calculating indicator {name}: {e}", exc_info=True)
                self.indicator_values[name] = None
        # self.logger.debug(f"[{self.strategy_id}] Indicator Values: {self.indicator_values}")


    async def _apply_heuristic_logic(self):
        if self.heuristic_logic['type'] == 'score':
            new_score = 0
            for config in self.indicator_configs:
                indicator_name = config['name']
                base_indicator_name = indicator_name.split('_')[0] # e.g. "RSI" from "RSI_oversold"

                value = self.indicator_values.get(indicator_name) # For EMA_CROSS, value is direct
                if config['type'] == "RSI": # For RSI conditions, get the base RSI value
                    value = self.indicator_values.get(base_indicator_name, self.indicator_values.get(indicator_name))


                if value is None: continue # Skip if indicator couldn't be calculated

                if config['type'] == "RSI":
                    if config['condition'] == '<' and value < config['level']: new_score += config['score']
                    elif config['condition'] == '>' and value > config['level']: new_score += config['score']
                elif config['type'] == "EMA_CROSS": # Value is 1 (bull), -1 (bear), 0 (none)
                    if value == 1: new_score += config.get('score_bullish', config.get('score', 0)) # Check for specific or generic score
                    elif value == -1: new_score += config.get('score_bearish', config.get('score', 0))

            self.current_score = new_score
            self.logger.debug(f"[{self.strategy_id}] New heuristic score: {self.current_score}")

            if self.current_position is None: # Only consider new entries if no active position
                entry_price = float(self.historical_klines_df.iloc[-1]['close'])
                sl_atr = self.atr_value if self.atr_value and self.atr_value > 1e-8 else entry_price * 0.01 # Fallback ATR

                if self.current_score >= self.heuristic_logic['buy_threshold']:
                    sl_price = entry_price - sl_atr * self.sl_atr_multiplier
                    await self._enter_position('LONG', entry_price, sl_price, "heuristic_buy")
                elif self.current_score <= self.heuristic_logic['sell_threshold']:
                    sl_price = entry_price + sl_atr * self.sl_atr_multiplier
                    await self._enter_position('SHORT', entry_price, sl_price, "heuristic_sell")
        else:
            self.logger.warning(f"[{self.strategy_id}] Heuristic logic type '{self.heuristic_logic['type']}' not implemented.")


    async def _enter_position(self, side: str, entry_price_estimate: float, sl_price: float, signal_type: str):
        if not self.is_active or self.current_position: return
        if not self.risk_manager: self.logger.error(f"[{self.strategy_id}] RiskManager N/A."); return

        pos_side = "LONG" if side == "BUY" else "SHORT"
        sl_price = round(sl_price, self.asset_price_precision)

        risk_capital_usd = await self.risk_manager.calculate_position_size_usd(self.default_risk_per_trade_perc)
        if not risk_capital_usd or risk_capital_usd <= 0:
            self.logger.warning(f"[{self.strategy_id}] Zero/invalid risk capital USD: {risk_capital_usd}."); return

        quantity = self.risk_manager.calculate_quantity_from_risk_usd(
            risk_capital_usd, entry_price_estimate, sl_price, self.asset_quantity_precision, self.min_trade_qty
        )
        if not quantity or quantity <= 0:
            self.logger.warning(f"[{self.strategy_id}] Zero/invalid quantity ({quantity}) from RM."); return

        order_resp = await self._place_market_order(self.symbol, side, quantity, positionSide=pos_side)
        if order_resp and order_resp.get('status') == 'FILLED':
            filled_price = float(order_resp['avgPrice'])
            tp_dist = abs(filled_price - sl_price) * self.tp_rr_ratio
            tp_price = round(filled_price + tp_dist if side == "BUY" else filled_price - tp_dist, self.asset_price_precision)
            self.current_position = {'side': side, 'entry_price': filled_price, 'quantity': quantity,
                                     'sl_price': sl_price, 'tp_price': tp_price,
                                     'client_order_id': order_resp.get('clientOrderId')}
            self.logger.info(f"[{self.strategy_id} - {signal_type}] Position OPENED: {side} {quantity} {self.symbol} @ {filled_price}. SL:{sl_price}, TP:{tp_price}")
        else:
            self.logger.error(f"[{self.strategy_id}] Failed to enter position for {signal_type}: {order_resp}")

    async def _check_sl_tp(self, current_price: float):
        if not self.current_position: return
        pos = self.current_position
        close_reason = None
        exit_price = current_price # For market exit

        if pos['side'] == 'LONG':
            if current_price <= pos['sl_price']: close_reason = "SL_LONG"
            elif current_price >= pos['tp_price']: close_reason = "TP_LONG"
        elif pos['side'] == 'SHORT':
            if current_price >= pos['sl_price']: close_reason = "SL_SHORT"
            elif current_price <= pos['tp_price']: close_reason = "TP_SHORT"

        if close_reason:
            self.logger.info(f"[{self.strategy_id}] {close_reason} triggered. PosEntry:{pos['entry_price']}, Qty:{pos['quantity']}, SL:{pos['sl_price']}, TP:{pos['tp_price']}, CurrentPx:{current_price}")
            exit_side = "SELL" if pos['side'] == "LONG" else "BUY"
            await self._place_market_order(self.symbol, exit_side, pos['quantity'], positionSide=pos['side'])
            # self.current_position will be cleared in on_order_update upon fill

    async def on_order_update(self, order_update: Dict):
        client_oid = order_update.get('c')
        if not client_oid or not client_oid.startswith(self.strategy_id): return

        status = order_update.get('X')
        self.logger.info(f"[{self.strategy_id}] Order Update: ClientOID={client_oid}, Status={status}, Symbol={order_update.get('s')}")
        if self.current_position and client_oid == self.current_position.get('client_order_id'):
            if status == 'FILLED': # Entry order filled
                # Update entry price if needed (though avgPrice from market order is usually accurate)
                self.current_position['entry_price'] = float(order_update.get('ap', self.current_position['entry_price']))
                self.logger.info(f"[{self.strategy_id}] Entry order {client_oid} confirmed FILLED. Position active: {self.current_position}")
            elif status in ['CANCELED', 'REJECTED', 'EXPIRED']:
                self.logger.warning(f"[{self.strategy_id}] Entry order {client_oid} failed ({status}). Clearing position.")
                self.current_position = None
        elif self.current_position and status == 'FILLED': # Could be an exit order
             # Check if it's closing current position
            if (order_update.get('S') == "SELL" and self.current_position['side'] == "LONG" and float(order_update.get('q')) == self.current_position['quantity']) or \
               (order_update.get('S') == "BUY" and self.current_position['side'] == "SHORT" and float(order_update.get('q')) == self.current_position['quantity']):
                self.logger.info(f"[{self.strategy_id}] Exit order {client_oid} FILLED. Position closed.")
                self.current_position = None


    async def stop(self):
        await super().stop()
        if self.current_position and not self.backtest_mode:
             self.logger.info(f"[{self.strategy_id}] Stopping: Closing open position: {self.current_position}")
             exit_side = "SELL" if self.current_position['side'] == "LONG" else "BUY"
             await self._place_market_order(self.symbol, exit_side, self.current_position['quantity'], positionSide=self.current_position['side'])
        self.logger.info(f"[{self.strategy_id}] IndicatorHeuristicStrategy stopped.")

    # Other abstract methods
    async def on_depth_update(self, symbol: str, depth_data: Dict): pass
    async def on_trade_update(self, symbol: str, trade_data: Dict): pass
    async def on_mark_price_update(self, symbol: str, mark_price_data: Dict): pass # Not used by this simple version

```
