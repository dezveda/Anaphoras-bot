import logging
import pandas as pd
import numpy as np
from typing import Dict, Optional, Any, List # Added List for type hints
import asyncio

from .base_strategy import BaseStrategy
OrderManager = Any
MarketDataProvider = Any
BasicRiskManager = Any
# Forward declaration for type hinting if StrategyEngine is imported here
# StrategyEngine = Any

class IndicatorHeuristicStrategy(BaseStrategy):
    strategy_type_name: str = "IndicatorHeuristicStrategy"

    def __init__(self, strategy_id: str, params: Dict[str, Any],
                 order_manager: OrderManager,
                 market_data_provider: MarketDataProvider,
                 risk_manager: BasicRiskManager,
                 logger: Optional[logging.Logger] = None,
                 strategy_engine_ref: Optional[Any] = None): # Added strategy_engine_ref
        super().__init__(strategy_id, params, order_manager, market_data_provider, risk_manager, logger, strategy_engine_ref=strategy_engine_ref)
        self.strategy_engine_ref = strategy_engine_ref # Store it

        self.symbol: str = self.get_param('symbol', 'BTCUSDT')
        self.trade_timeframe: str = self.get_param('trade_timeframe', '1h')
        self.klines_buffer_size: int = int(self.get_param('klines_buffer_size', 100))

        # Indicator Parameters
        self.rsi_period: int = int(self.get_param('rsi_period', 14))
        self.rsi_oversold: float = float(self.get_param('rsi_oversold', 30))
        self.rsi_overbought: float = float(self.get_param('rsi_overbought', 70))
        self.ema_short_period: int = int(self.get_param('ema_short_period', 9))
        self.ema_long_period: int = int(self.get_param('ema_long_period', 21))

        # Scoring and Thresholds
        self.score_rsi_oversold: int = int(self.get_param('score_rsi_oversold', 1))
        self.score_rsi_overbought: int = int(self.get_param('score_rsi_overbought', -1))
        self.score_ema_bullish_cross: int = int(self.get_param('score_ema_bullish_cross', 1))
        self.score_ema_bearish_cross: int = int(self.get_param('score_ema_bearish_cross', -1))
        self.buy_score_threshold: int = int(self.get_param('buy_score_threshold', 2))
        self.sell_score_threshold: int = int(self.get_param('sell_score_threshold', -2))

        # Trade Parameters
        self.default_risk_per_trade_perc: float = float(self.get_param('default_risk_per_trade_perc', 0.01))
        self.sl_atr_multiplier: float = float(self.get_param('sl_atr_multiplier', 1.5))
        self.tp_atr_multiplier: float = float(self.get_param('tp_atr_multiplier', 2.0))
        self.atr_period_for_sl_tp: int = int(self.get_param('atr_period_for_sl_tp', 14))
        self.min_order_qty: float = float(self.get_param('min_order_qty', 0.001))
        self.asset_quantity_precision: int = int(self.get_param('asset_quantity_precision', 3))
        self.asset_price_precision: int = int(self.get_param('asset_price_precision', 2))

        # Trend Adaptation Parameters
        self.filter_by_macro_trend: bool = bool(self.get_param('filter_by_macro_trend', True))
        self.strict_macro_filter: bool = bool(self.get_param('strict_macro_filter', True))
        self.score_adjust_macro_bull: float = float(self.get_param('score_adjust_macro_bull', 1.0))
        self.score_adjust_macro_bear: float = float(self.get_param('score_adjust_macro_bear', -1.0)) # Should be negative
        self.threshold_boost_with_macro: float = float(self.get_param('threshold_boost_with_macro', 0.0))
        self.threshold_penalty_counter_macro: float = float(self.get_param('threshold_penalty_counter_macro', 1.0))

        self.current_position: Optional[Dict[str, Any]] = None
        self.recent_klines_df = pd.DataFrame(columns=['open', 'high', 'low', 'close', 'volume'])
        self.atr_value: Optional[float] = None
        self.rsi_series = pd.Series(dtype=float)
        self.ema_short_series = pd.Series(dtype=float)
        self.ema_long_series = pd.Series(dtype=float)

        self.logger.info(f"[{self.strategy_id}] {self.strategy_type_name} initialized.")

    @staticmethod
    def get_default_params() -> dict:
        return {
            'symbol': {'type': 'str', 'default': 'BTCUSDT', 'desc': 'Trading symbol.'},
            'trade_timeframe': {'type': 'str', 'default': '1h', 'options': ['1m','5m','15m','1h','4h'], 'desc': 'Kline timeframe for signal generation.'},
            'klines_buffer_size': {'type': 'int', 'default': 100, 'min': 50, 'max': 500, 'desc': 'Number of klines to keep in buffer for indicator calculation.'},
            'rsi_period': {'type': 'int', 'default': 14, 'min': 5, 'max': 50, 'desc': 'RSI calculation period.'},
            'rsi_oversold': {'type': 'float', 'default': 30, 'min': 10, 'max': 40, 'step': 1, 'desc': 'RSI oversold threshold.'},
            'rsi_overbought': {'type': 'float', 'default': 70, 'min': 60, 'max': 90, 'step': 1, 'desc': 'RSI overbought threshold.'},
            'ema_short_period': {'type': 'int', 'default': 9, 'min': 3, 'max': 50, 'desc': 'Short EMA period.'},
            'ema_long_period': {'type': 'int', 'default': 21, 'min': 10, 'max': 200, 'desc': 'Long EMA period.'},
            'score_rsi_oversold': {'type': 'int', 'default': 1, 'desc': 'Score for RSI oversold condition.'},
            'score_rsi_overbought': {'type': 'int', 'default': -1, 'desc': 'Score for RSI overbought condition.'},
            'score_ema_bullish_cross': {'type': 'int', 'default': 1, 'desc': 'Score for EMA bullish crossover.'},
            'score_ema_bearish_cross': {'type': 'int', 'default': -1, 'desc': 'Score for EMA bearish crossover.'},
            'buy_score_threshold': {'type': 'int', 'default': 2, 'min': 1, 'max': 5, 'desc': 'Minimum score to trigger a buy signal.'},
            'sell_score_threshold': {'type': 'int', 'default': -2, 'min': -5, 'max': -1, 'desc': 'Maximum score to trigger a sell signal.'},
            'default_risk_per_trade_perc': {'type': 'float', 'default': 0.01, 'min': 0.001, 'max': 0.05, 'step':0.001, 'desc': 'Percentage of balance to risk per trade.'},
            'sl_atr_multiplier': {'type': 'float', 'default': 1.5, 'min': 0.5, 'max': 5.0, 'step':0.1, 'desc': 'ATR multiplier for stop loss calculation.'},
            'tp_atr_multiplier': {'type': 'float', 'default': 2.0, 'min': 0.5, 'max': 10.0, 'step':0.1, 'desc': 'ATR multiplier for take profit (Risk/Reward based on ATR).'},
            'atr_period_for_sl_tp': {'type': 'int', 'default': 14, 'min': 5, 'max': 50, 'desc': 'ATR period for SL/TP volatility adjustment.'},
            'asset_quantity_precision': {'type': 'int', 'default': 3, 'desc': 'Decimal precision for asset quantity.'},
            'asset_price_precision': {'type': 'int', 'default': 2, 'desc': 'Decimal precision for asset price.'},
            'min_order_qty': {'type': 'float', 'default': 0.001, 'desc': 'Minimum order quantity for the symbol.'},

            # Trend Adaptation Params
            'filter_by_macro_trend': {'type': 'bool', 'default': True, 'desc': 'Enable filtering/adjustment by macro trend.'},
            'strict_macro_filter': {'type': 'bool', 'default': True, 'desc': 'If true, strictly no counter-macro trend trades. If false, adjust scores/thresholds.'},
            'score_adjust_macro_bull': {'type': 'float', 'default': 1.0, 'step': 0.1, 'desc': 'Additive score adjustment for buy signals in macro bull trend.'},
            'score_adjust_macro_bear': {'type': 'float', 'default': -1.0, 'step': 0.1, 'desc': 'Additive score adjustment for sell signals in macro bear trend (e.g. makes score more negative).'},
            'threshold_boost_with_macro': {'type': 'float', 'default': 0.0, 'step': 0.1, 'desc': 'Value to reduce buy/sell threshold if aligned with macro trend (making it easier to trigger).'},
            'threshold_penalty_counter_macro': {'type': 'float', 'default': 1.0, 'step': 0.1, 'desc': 'Value to increase buy/sell threshold if counter macro trend (making it harder to trigger).'}
        }

    async def start(self):
        self.strategy_type_name = self.__class__.strategy_type_name # Ensure this is set
        await super().start()
        initial_klines_needed = max(self.klines_buffer_size, self.rsi_period, self.ema_long_period, self.atr_period_for_sl_tp) + 5
        if self.backtest_mode:
            self.logger.info(f"[{self.strategy_id}] Backtest mode: Initial klines expected from BacktestEngine.")
            # In backtest, klines are usually pushed via on_kline_update directly by the engine
        else:
            self.logger.info(f"[{self.strategy_id}] Live mode: Fetching initial {initial_klines_needed} klines for {self.symbol} {self.trade_timeframe}...")
            hist_data = await self.market_data_provider.get_historical_klines(self.symbol, self.trade_timeframe, limit=initial_klines_needed)
            if hist_data is not None and not hist_data.empty:
                self.recent_klines_df = hist_data[['open', 'high', 'low', 'close', 'volume']].copy()
                self._update_indicators() # Calculate initial indicators
            else:
                self.logger.warning(f"[{self.strategy_id}] Could not fetch initial klines for {self.symbol} {self.trade_timeframe}.")
            # Subscribe to live klines
            await self.market_data_provider.subscribe_to_kline_stream(self.symbol, self.trade_timeframe, self._handle_kline_wrapper)
        self.logger.info(f"[{self.strategy_id}] {self.strategy_type_name} started.")

    async def _handle_kline_wrapper(self, raw_ws_message: dict):
        kline_payload = raw_ws_message.get('data', {}).get('k') # Adjusted path for typical Binance stream
        if not kline_payload: # If 'data' is not present, assume raw_ws_message is the kline_payload itself (e.g. from backtester)
             kline_payload = raw_ws_message.get('k')

        if kline_payload:
            await self.on_kline_update(kline_payload.get('s'), kline_payload.get('i'), kline_payload)
        else:
            self.logger.warning(f"[{self.strategy_id}] WS kline message missing 'k' or not in expected format: {raw_ws_message}")


    async def stop(self):
        await super().stop()
        # Unsubscribe if needed, though MarketDataProvider might handle this globally on shutdown
        self.logger.info(f"[{self.strategy_id}] {self.strategy_type_name} stopped.")

    async def on_kline_update(self, symbol: str, interval: str, kline_data: Dict):
        if not self.is_active or symbol != self.symbol or interval != self.trade_timeframe:
            return

        # For live trading, only process closed candles. For backtesting, process every kline pushed.
        if not kline_data.get('x', False) and not self.backtest_mode :
            # self.logger.debug(f"[{self.strategy_id}] Skipping unclosed live kline.")
            return

        ts = pd.to_datetime(kline_data['t'], unit='ms', utc=True)
        new_kline_data = {
            'open': float(kline_data['o']),
            'high': float(kline_data['h']),
            'low': float(kline_data['l']),
            'close': float(kline_data['c']),
            'volume': float(kline_data['v'])
        }

        # Update recent_klines_df
        if ts not in self.recent_klines_df.index:
            new_kline_series = pd.Series(new_kline_data, name=ts)
            self.recent_klines_df = pd.concat([self.recent_klines_df, new_kline_series.to_frame().T])
        else:
            self.recent_klines_df.loc[ts] = new_kline_data

        # Keep buffer size
        if len(self.recent_klines_df) > self.klines_buffer_size:
            self.recent_klines_df = self.recent_klines_df.iloc[-self.klines_buffer_size:]

        # Special handling for ATR in backtest if provided directly in kline_data
        if self.backtest_mode and 'atr' in kline_data and kline_data['atr'] is not None:
            self.atr_value = float(kline_data['atr'])

        self._update_indicators() # This will calculate RSI, EMAs, and ATR (if not from backtest kline)

        # Trading Logic
        if self.current_position:
            await self._check_sl_tp(float(kline_data['c'])) # Check SL/TP based on close price
        elif self.atr_value is not None and self.atr_value > 1e-9: # Ensure ATR is valid before applying logic
            await self._apply_heuristic_logic(kline_data)
        else:
            self.logger.debug(f"[{self.strategy_id}] ATR not valid ({self.atr_value}), skipping signal logic for kline @ {ts}.")


    def _update_indicators(self):
        if len(self.recent_klines_df) < 2:
            return

        df = self.recent_klines_df.copy()
        df['close'] = df['close'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)

        # RSI
        if len(df) >= self.rsi_period:
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0.0)).ewm(com=max(1, self.rsi_period - 1), adjust=False, min_periods=max(1,self.rsi_period-1)).mean()
            loss = (-delta.where(delta < 0, 0.0)).ewm(com=max(1, self.rsi_period - 1), adjust=False, min_periods=max(1,self.rsi_period-1)).mean()
            rs = gain / (loss + 1e-9) # Avoid division by zero
            self.rsi_series = 100 - (100 / (1 + rs))
        else:
            self.rsi_series = pd.Series(dtype=float) # Ensure it's a Series

        # EMAs
        if len(df) >= self.ema_short_period:
            self.ema_short_series = df['close'].ewm(span=self.ema_short_period, adjust=False, min_periods=self.ema_short_period).mean()
        else:
            self.ema_short_series = pd.Series(dtype=float)

        if len(df) >= self.ema_long_period:
            self.ema_long_series = df['close'].ewm(span=self.ema_long_period, adjust=False, min_periods=self.ema_long_period).mean()
        else:
            self.ema_long_series = pd.Series(dtype=float)

        # ATR (only if not in backtest mode where ATR might be provided, or if ATR is currently None/invalid)
        if not self.backtest_mode or self.atr_value is None or self.atr_value <= 1e-9 :
            if len(df) >= self.atr_period_for_sl_tp + 1: # Need +1 for shift(1)
                high_low = df['high'] - df['low']
                high_close_prev = np.abs(df['high'] - df['close'].shift(1))
                low_close_prev = np.abs(df['low'] - df['close'].shift(1))
                tr_df = pd.DataFrame({'hl': high_low, 'hc': high_close_prev, 'lc': low_close_prev})
                true_range = tr_df.max(axis=1)
                atr_series = true_range.ewm(span=self.atr_period_for_sl_tp, adjust=False, min_periods=self.atr_period_for_sl_tp).mean()
                if not atr_series.empty and not pd.isna(atr_series.iloc[-1]):
                    self.atr_value = atr_series.iloc[-1]
                else:
                    self.atr_value = None # Keep as None if calculation fails
            else:
                self.atr_value = None


    async def _apply_heuristic_logic(self, kline_data: Dict):
        current_price = float(kline_data['c'])
        original_score = 0

        if not self.rsi_series.empty and not pd.isna(self.rsi_series.iloc[-1]):
            rsi = self.rsi_series.iloc[-1]
            if rsi < self.rsi_oversold: original_score += self.score_rsi_oversold
            if rsi > self.rsi_overbought: original_score += self.score_rsi_overbought

        if len(self.ema_short_series) > 1 and len(self.ema_long_series) > 1 and \
           not pd.isna(self.ema_short_series.iloc[-1]) and not pd.isna(self.ema_long_series.iloc[-1]) and \
           not pd.isna(self.ema_short_series.iloc[-2]) and not pd.isna(self.ema_long_series.iloc[-2]):
            s_prev, s_curr = self.ema_short_series.iloc[-2:]
            l_prev, l_curr = self.ema_long_series.iloc[-2:]
            if s_prev < l_prev and s_curr > l_curr: original_score += self.score_ema_bullish_cross
            if s_prev > l_prev and s_curr < l_curr: original_score += self.score_ema_bearish_cross

        self.logger.debug(f"[{self.strategy_id}] Original Score: {original_score}, Price: {current_price:.{self.asset_price_precision}f}")

        if self.current_position: return # Already in a position

        # --- Trend Adaptation Logic ---
        market_regime = "UNDEFINED"
        if self.strategy_engine_ref:
            trend_adapter = self.strategy_engine_ref.get_trend_adapter()
            if trend_adapter and hasattr(trend_adapter, 'get_current_market_regime'):
                market_regime = trend_adapter.get_current_market_regime()
                self.logger.debug(f"[{self.strategy_id}] Fetched market regime: {market_regime} from TrendAdaptationStrategy.")
            else:
                self.logger.debug(f"[{self.strategy_id}] TrendAdaptationStrategy instance not found or "
                                  f"lacks get_current_market_regime method in StrategyEngine.")
        else:
            self.logger.debug(f"[{self.strategy_id}] StrategyEngine reference not available. Cannot get market regime.")

        adjusted_score = original_score
        current_buy_threshold = self.buy_score_threshold
        current_sell_threshold = self.sell_score_threshold

        if self.filter_by_macro_trend and market_regime != "UNDEFINED":
            is_macro_bull = "MACRO_BULL" in market_regime
            is_macro_bear = "MACRO_BEAR" in market_regime

            if is_macro_bull:
                if original_score > 0: # Potential buy signal
                    adjusted_score += self.score_adjust_macro_bull
                current_buy_threshold -= self.threshold_boost_with_macro
                current_sell_threshold += self.threshold_penalty_counter_macro # Make selling harder
                if self.strict_macro_filter and original_score <= 0: # Original score was bearish or neutral
                    self.logger.info(f"[{self.strategy_id}] Strict MACRO_BULL filter: Original score {original_score} not bullish. Sell threshold set to infinity.")
                    current_sell_threshold = float('inf')
            elif is_macro_bear:
                if original_score < 0: # Potential sell signal
                    adjusted_score += self.score_adjust_macro_bear # score_adjust_macro_bear is negative
                current_sell_threshold += self.threshold_boost_with_macro # Makes sell threshold more negative (easier to reach if already negative)
                current_buy_threshold += self.threshold_penalty_counter_macro # Make buying harder
                if self.strict_macro_filter and original_score >= 0: # Original score was bullish or neutral
                    self.logger.info(f"[{self.strategy_id}] Strict MACRO_BEAR filter: Original score {original_score} not bearish. Buy threshold set to infinity.")
                    current_buy_threshold = float('inf')

            self.logger.debug(f"[{self.strategy_id}] Regime: {market_regime} -> Adjusted Score: {adjusted_score}, BuyTh: {current_buy_threshold}, SellTh: {current_sell_threshold}")
        else:
            self.logger.debug(f"[{self.strategy_id}] No trend filtering applied. Score: {adjusted_score}, BuyTh: {current_buy_threshold}, SellTh: {current_sell_threshold}")

        # --- Trade Decision Logic ---
        if self.atr_value is None or self.atr_value <= 1e-9: # Check for valid ATR
            self.logger.warning(f"[{self.strategy_id}] ATR value ({self.atr_value}) is not valid. Cannot determine SL and enter position.")
            return

        if adjusted_score >= current_buy_threshold:
            sl_price = current_price - self.atr_value * self.sl_atr_multiplier
            await self._enter_position('LONG', current_price, sl_price)
        elif adjusted_score <= current_sell_threshold:
            sl_price = current_price + self.atr_value * self.sl_atr_multiplier
            await self._enter_position('SHORT', current_price, sl_price)


    async def _enter_position(self, side: str, entry_price: float, sl_price: float):
        if not self.is_active or self.current_position:
            return
        if not self.risk_manager or self.atr_value is None or self.atr_value <= 1e-9: # Ensure ATR is valid
            self.logger.warning(f"[{self.strategy_id}] Entry rejected: RiskManager unavailable or ATR invalid ({self.atr_value}).")
            return

        pos_side = side # For futures, LONG or SHORT

        # Calculate Take Profit price
        if side == "LONG":
            tp_price = entry_price + (self.atr_value * self.tp_atr_multiplier)
        else: # SHORT
            tp_price = entry_price - (self.atr_value * self.tp_atr_multiplier)

        tp_price = round(tp_price, self.asset_price_precision)
        sl_price = round(sl_price, self.asset_price_precision)

        # Calculate quantity
        risk_usd_per_trade = await self.risk_manager.calculate_position_size_usd(percentage_of_balance=self.default_risk_per_trade_perc)
        if risk_usd_per_trade is None or risk_usd_per_trade <= 0:
            self.logger.warning(f"[{self.strategy_id}] Invalid risk USD per trade: {risk_usd_per_trade}. Cannot calculate quantity.")
            return

        quantity = self.risk_manager.calculate_quantity_from_risk_usd(
            risk_usd=risk_usd_per_trade,
            entry_price=entry_price,
            stop_loss_price=sl_price,
            asset_precision=self.asset_quantity_precision,
            min_order_qty_asset=self.min_order_qty
        )

        if quantity is None or quantity <= 0:
            self.logger.warning(f"[{self.strategy_id}] Invalid quantity calculated: {quantity} for risk USD {risk_usd_per_trade}. "
                                f"Entry: {entry_price}, SL: {sl_price}")
            return

        self.logger.info(f"[{self.strategy_id}] Attempting to enter {side} position: "
                         f"Qty={quantity}, EntryPrice~{entry_price}, SL={sl_price}, TP={tp_price}")

        order_response = await self._place_market_order(
            symbol=self.symbol,
            side=side, # 'BUY' for LONG, 'SELL' for SHORT
            quantity=quantity,
            positionSide=pos_side # 'LONG' or 'SHORT' for hedging mode
        )

        if order_response and order_response.get('status') == 'FILLED':
            filled_price = float(order_response['avgPrice'])
            # Update SL and TP based on actual filled price if significantly different (optional, for now use initial calculation)
            self.current_position = {
                'side': side, # 'LONG' or 'SHORT' (conceptual position side)
                'entry_price': filled_price,
                'quantity': float(order_response['executedQty']), # Use executedQty
                'sl': sl_price,
                'tp': tp_price,
                'entry_timestamp': pd.Timestamp.now(tz='UTC'), # Use current time for entry
                'order_id': order_response.get('orderId'),
                'client_order_id': order_response.get('clientOrderId')
            }
            self.logger.info(f"[{self.strategy_id}] Position Entered Successfully: {self.current_position}")
        else:
            self.logger.error(f"[{self.strategy_id}] Failed to enter position. Order response: {order_response}")


    async def _check_sl_tp(self, current_price: float):
        if not self.current_position or not self.is_active:
            return

        pos = self.current_position
        sl_hit = False
        tp_hit = False

        if pos['side'] == 'LONG':
            if current_price <= pos['sl']: sl_hit = True
            if current_price >= pos['tp']: tp_hit = True
        elif pos['side'] == 'SHORT':
            if current_price >= pos['sl']: sl_hit = True
            if current_price <= pos['tp']: tp_hit = True

        if sl_hit:
            await self._close_current_position(f"Stop-Loss hit @ {current_price:.{self.asset_price_precision}f}")
        elif tp_hit:
            await self._close_current_position(f"Take-Profit hit @ {current_price:.{self.asset_price_precision}f}")

    async def _close_current_position(self, reason: str):
        if not self.current_position or not self.is_active:
            return

        pos = self.current_position
        side_to_close = "SELL" if pos['side'] == "LONG" else "BUY" # Opposite action to close

        self.logger.info(f"[{self.strategy_id}] Closing {pos['side']} position for {self.symbol} due to: {reason}. "
                         f"Qty: {pos['quantity']}")

        order_response = await self._place_market_order(
            symbol=self.symbol,
            side=side_to_close,
            quantity=pos['quantity'],
            positionSide=pos['side'], # Pass the original position side (LONG/SHORT) for reduceOnly logic if applicable
            reduceOnly=True
        )

        if order_response and order_response.get('status') == 'FILLED':
            self.logger.info(f"[{self.strategy_id}] Position closed successfully. Reason: {reason}. Response: {order_response}")
        else:
            self.logger.error(f"[{self.strategy_id}] Failed to close position. Reason: {reason}. Response: {order_response}")

        self.current_position = None # Clear position state

    async def on_order_update(self, order_update: Dict):
        client_oid = order_update.get('c', '') # clientOrderId
        # Filter out irrelevant order updates
        if not client_oid or not client_oid.startswith(self.strategy_id):
            return

        self.logger.info(f"[{self.strategy_id}] Received own order update via WebSocket: ClientOID={client_oid}, "
                         f"Symbol={order_update.get('s')}, Side={order_update.get('S')}, Status={order_update.get('X')}, "
                         f"Type={order_update.get('o')}, Qty={order_update.get('q')}, FilledQty={order_update.get('z')}, "
                         f"Price={order_update.get('p')}, AvgPrice={order_update.get('ap')}")

        # Check if this update corresponds to the current open position's entry order
        if self.current_position and self.current_position.get('client_order_id') == client_oid:
            if order_update.get('X') == 'FILLED': # Order is filled
                # If it's a reduceOnly order (our close order), then the position is closed.
                if order_update.get('R') is True or str(order_update.get('R')).lower() == 'true' or \
                   (order_update.get('S') != self.current_position.get('side')): # Side of order is opposite to position
                    self.logger.info(f"[{self.strategy_id}] Position closing order {client_oid} confirmed FILLED via WebSocket. "
                                     f"Clearing position state for {self.symbol}.")
                    self.current_position = None
            elif order_update.get('X') in ['CANCELED', 'EXPIRED', 'REJECTED']:
                # If the entry order itself failed or was canceled before fill.
                self.logger.warning(f"[{self.strategy_id}] Entry order {client_oid} for {self.symbol} is {order_update.get('X')}. "
                                    f"Clearing potential position state.")
                self.current_position = None
        # Potentially handle SL/TP order updates if they were placed as separate limit orders (not current design)


    async def on_depth_update(self, symbol: str, depth_data: Dict):
        pass # Not used by this strategy

    async def on_trade_update(self, symbol: str, trade_data: Dict):
        pass # Not used by this strategy

    async def on_mark_price_update(self, symbol: str, mark_price_data: Dict):
        if self.current_position and self.is_active and symbol == self.symbol and mark_price_data.get('p'):
            # self.logger.debug(f"[{self.strategy_id}] Mark price update for {symbol}: {mark_price_data['p']}")
            await self._check_sl_tp(float(mark_price_data['p']))
