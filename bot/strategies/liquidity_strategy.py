import logging
import pandas as pd
import numpy as np
from typing import Dict, Optional, Any, List
import asyncio

from .base_strategy import BaseStrategy
OrderManager = Any
MarketDataProvider = Any
BasicRiskManager = Any

class LiquidityPointsStrategy(BaseStrategy):
    strategy_type_name: str = "LiquidityPointsStrategy"

    def __init__(self, strategy_id: str, params: Dict[str, Any],
                 order_manager: OrderManager,
                 market_data_provider: MarketDataProvider,
                 risk_manager: BasicRiskManager,
                 logger: Optional[logging.Logger] = None):
        super().__init__(strategy_id, params, order_manager, market_data_provider, risk_manager, logger)

        self.symbol: str = self.get_param('symbol', 'BTCUSDT')
        self.trade_timeframe: str = self.get_param('trade_timeframe', '15m')

        self.swing_point_lookback: int = int(self.get_param('swing_point_lookback', 20))
        self.stop_run_reversal_confirmation_bars: int = int(self.get_param('stop_run_reversal_confirmation_bars', 1))

        self.default_risk_per_trade_perc: float = float(self.get_param('default_risk_per_trade_perc', 0.01))
        self.sl_atr_multiplier: float = float(self.get_param('sl_atr_multiplier', 1.5))
        self.tp_atr_multiplier: float = float(self.get_param('tp_atr_multiplier', 2.0))
        self.atr_period_for_sl_tp: int = int(self.get_param('atr_period_for_sl_tp', 14))

        self.asset_quantity_precision: int = int(self.get_param('asset_quantity_precision', 3))
        self.asset_price_precision: int = int(self.get_param('asset_price_precision', 2))
        self.min_order_qty: float = float(self.get_param('min_order_qty', 0.001))

        self.current_position: Optional[Dict[str, Any]] = None
        self.recent_klines_df = pd.DataFrame(columns=['open', 'high', 'low', 'close', 'volume'])
        self.atr_value: Optional[float] = None
        self.last_swing_high: Optional[float] = None
        self.last_swing_low: Optional[float] = None
        self.potential_stop_run: Optional[Dict[str, Any]] = None

        self.kline_buffer_size = max(self.swing_point_lookback, self.atr_period_for_sl_tp) + 50

        self.logger.info(f"[{self.strategy_id}] {self.strategy_type_name} initialized. Symbol: {self.symbol}, TF: {self.trade_timeframe}, SwingLookback: {self.swing_point_lookback}")

    @staticmethod
    def get_default_params() -> dict:
        return {
            'symbol': {'type': 'str', 'default': 'BTCUSDT', 'desc': 'Trading symbol.'},
            'trade_timeframe': {'type': 'str', 'default': '15m', 'options': ['1m','5m','15m','1h','4h'], 'desc': 'Timeframe for kline data and trading signals.'},
            'swing_point_lookback': {'type': 'int', 'default': 20, 'min': 5, 'max': 100, 'desc': 'Lookback period for identifying recent swing highs/lows.'},
            'stop_run_reversal_confirmation_bars': {'type': 'int', 'default': 1, 'min': 0, 'max': 5, 'desc': 'Number of bars to confirm reversal after a potential stop run.'},
            'default_risk_per_trade_perc': {'type': 'float', 'default': 0.01, 'min': 0.001, 'max': 0.05, 'step': 0.001, 'desc': 'Default risk percentage per trade.'},
            'sl_atr_multiplier': {'type': 'float', 'default': 1.5, 'min': 0.5, 'max': 5.0, 'step': 0.1, 'desc': 'ATR multiplier for stop loss calculation.'},
            'tp_atr_multiplier': {'type': 'float', 'default': 2.0, 'min': 0.5, 'max': 10.0, 'step': 0.1, 'desc': 'ATR multiplier for take profit calculation.'},
            'atr_period_for_sl_tp': {'type': 'int', 'default': 14, 'min': 5, 'max': 50, 'desc': 'ATR period for stop loss/take profit volatility adjustment.'},
            'asset_quantity_precision': {'type': 'int', 'default': 3, 'desc': 'Decimal precision for asset quantity (e.g., BTC).'},
            'asset_price_precision': {'type': 'int', 'default': 2, 'desc': 'Decimal precision for asset price (e.g., USDT).'},
            'min_order_qty': {'type': 'float', 'default': 0.001, 'desc': 'Minimum order quantity for the symbol.'}
        }

    async def start(self):
        await super().start()
        if not self.backtest_mode:
            await self.market_data_provider.subscribe_to_kline_stream(
                self.symbol, self.trade_timeframe,
                callback=self._handle_kline_wrapper
            )
            # Also subscribe to mark price for SL/TP checks in live mode
            await self.market_data_provider.subscribe_to_mark_price_stream(
                self.symbol,
                callback=lambda data: asyncio.create_task(self.on_mark_price_update(self.symbol, data))
            )
        else:
            self.logger.info(f"[{self.strategy_id}] Backtest mode: Initial data will be fed by BacktestEngine.")
        self.logger.info(f"[{self.strategy_id}] {self.strategy_type_name} started.")

    async def _handle_kline_wrapper(self, raw_ws_message: dict):
        kline_payload_dict = raw_ws_message.get('data', raw_ws_message).get('k')
        if kline_payload_dict:
            await self.on_kline_update(
                kline_payload_dict.get('s'),
                kline_payload_dict.get('i'),
                kline_payload_dict
            )
        else:
            self.logger.warning(f"[{self.strategy_id}] WS kline message missing 'k' field: {raw_ws_message}")

    async def stop(self):
        await super().stop()
        self.logger.info(f"[{self.strategy_id}] {self.strategy_type_name} stopped.")

    async def on_kline_update(self, symbol: str, interval: str, kline_data: Dict):
        if not self.is_active or symbol != self.symbol or interval != self.trade_timeframe: return
        if not kline_data.get('x', False) and not self.backtest_mode : return

        new_kline_timestamp = pd.to_datetime(kline_data['t'], unit='ms', utc=True)
        new_kline_series = pd.Series({
            'open': float(kline_data['o']), 'high': float(kline_data['h']),
            'low': float(kline_data['l']), 'close': float(kline_data['c']),
            'volume': float(kline_data['v'])
        }, name=new_kline_timestamp)

        if new_kline_timestamp not in self.recent_klines_df.index:
            self.recent_klines_df = pd.concat([self.recent_klines_df, new_kline_series.to_frame().T])
        else: self.recent_klines_df.loc[new_kline_timestamp] = new_kline_series

        if len(self.recent_klines_df) > self.kline_buffer_size:
            self.recent_klines_df = self.recent_klines_df.iloc[-self.kline_buffer_size:]

        if self.backtest_mode and 'atr' in kline_data:
            self.atr_value = float(kline_data.get('atr', 0.0))

        self._update_indicators_and_liquidity_points()

        if self.current_position: # If in position, only check for SL/TP based on kline close
            await self._check_sl_tp(float(kline_data['c']))
        elif self.atr_value and self.atr_value > 1e-8 :
            await self._check_liquidity_signals(kline_data)
        else: self.logger.debug(f"[{self.strategy_id}] ATR not valid ({self.atr_value}), skipping signal checks.")

    def _update_indicators_and_liquidity_points(self):
        # ... (implementation from previous step, ensure self.atr_value is updated if not in backtest providing it) ...
        if self.recent_klines_df.empty or len(self.recent_klines_df) < 2: return

        if not self.backtest_mode or self.atr_value is None or self.atr_value <= 1e-8:
            if len(self.recent_klines_df) >= self.atr_period_for_sl_tp +1 : # +1 for shift
                df_atr = self.recent_klines_df.copy()
                df_atr['high']=df_atr['high'].astype(float); df_atr['low']=df_atr['low'].astype(float); df_atr['close']=df_atr['close'].astype(float)
                high_low = df_atr['high'] - df_atr['low']
                high_close = np.abs(df_atr['high'] - df_atr['close'].shift(1))
                low_close = np.abs(df_atr['low'] - df_atr['close'].shift(1))
                ranges_df = pd.DataFrame({'hl': high_low, 'hc': high_close, 'lc': low_close})
                true_range = ranges_df.max(axis=1)
                atr_series = true_range.ewm(span=self.atr_period_for_sl_tp, adjust=False, min_periods=self.atr_period_for_sl_tp).mean()
                if not atr_series.empty and not pd.isna(atr_series.iloc[-1]): self.atr_value = atr_series.iloc[-1]
                else: self.atr_value = None
            else: self.atr_value = None

        if len(self.recent_klines_df) > 1 :
            df_for_swings = self.recent_klines_df.iloc[:-1]
            if len(df_for_swings) >= self.swing_point_lookback:
                self.last_swing_high = df_for_swings['high'].tail(self.swing_point_lookback).max()
                self.last_swing_low = df_for_swings['low'].tail(self.swing_point_lookback).min()
            elif not df_for_swings.empty:
                self.last_swing_high = df_for_swings['high'].max()
                self.last_swing_low = df_for_swings['low'].min()
            else: self.last_swing_high = None; self.last_swing_low = None
        else: self.last_swing_high = None; self.last_swing_low = None


    async def _check_liquidity_signals(self, kline_data: Dict):
        # ... (implementation from previous step)
        current_high=float(kline_data['h']); current_low=float(kline_data['l']); current_close=float(kline_data['c'])
        if self.last_swing_high:
            if self.potential_stop_run and self.potential_stop_run['type'] == 'high':
                self.potential_stop_run['bars_since_pierce'] += 1
                if current_close < self.potential_stop_run['price'] and self.potential_stop_run['bars_since_pierce'] >= self.stop_run_reversal_confirmation_bars:
                    await self._enter_position('SHORT', current_close, self.potential_stop_run['pierce_high'])
                    self.potential_stop_run = None
                elif self.potential_stop_run['bars_since_pierce'] > self.stop_run_reversal_confirmation_bars + 3: self.potential_stop_run = None
            elif current_high > self.last_swing_high:
                self.potential_stop_run = {'price': self.last_swing_high, 'type': 'high', 'pierce_high': current_high, 'bars_since_pierce': 0}
        if self.last_swing_low:
            if self.potential_stop_run and self.potential_stop_run['type'] == 'low':
                self.potential_stop_run['bars_since_pierce'] += 1
                if current_close > self.potential_stop_run['price'] and self.potential_stop_run['bars_since_pierce'] >= self.stop_run_reversal_confirmation_bars:
                    await self._enter_position('LONG', current_close, self.potential_stop_run['pierce_low'])
                    self.potential_stop_run = None
                elif self.potential_stop_run['bars_since_pierce'] > self.stop_run_reversal_confirmation_bars + 3: self.potential_stop_run = None
            elif current_low < self.last_swing_low:
                self.potential_stop_run = {'price': self.last_swing_low, 'type': 'low', 'pierce_low': current_low, 'bars_since_pierce': 0}


    async def _enter_position(self, side: str, entry_price_estimate: float, stop_trigger_price: float):
        # ... (implementation from previous step, ensure use of self.asset_price_precision for rounding SL/TP)
        if not self.is_active or self.current_position: return
        if not self.risk_manager or not self.atr_value or self.atr_value <= 1e-8:
            self.logger.warning(f"[{self.strategy_id}] Enter rejected: RM/ATR invalid. RM: {bool(self.risk_manager)}, ATR: {self.atr_value}"); return

        sl_price = round(stop_trigger_price - (self.atr_value * self.sl_atr_multiplier) if side == "LONG" else stop_trigger_price + (self.atr_value * self.sl_atr_multiplier), self.asset_price_precision)
        tp_price = round(entry_price_estimate + (self.atr_value * self.tp_atr_multiplier) if side == "LONG" else entry_price_estimate - (self.atr_value * self.tp_atr_multiplier), self.asset_price_precision)

        risk_capital_usd = await self.risk_manager.calculate_position_size_usd(risk_per_trade_perc=self.default_risk_per_trade_perc)
        if not risk_capital_usd or risk_capital_usd <=0: self.logger.warning(f"[{self.strategy_id}] Invalid risk cap USD: {risk_capital_usd}"); return
        quantity = self.risk_manager.calculate_quantity_from_risk_usd(risk_capital_usd, entry_price_estimate, sl_price, self.asset_quantity_precision, self.min_order_qty)
        if not quantity or quantity <= 0: self.logger.warning(f"[{self.strategy_id}] Invalid quantity: {quantity}"); return

        order_resp = await self._place_market_order(self.symbol, side, quantity, positionSide=side)
        if order_resp and order_resp.get('status') == 'FILLED':
            filled_px = float(order_resp['avgPrice'])
            self.current_position = {'side': side, 'entry_price': filled_px, 'quantity': quantity, 'sl': sl_price, 'tp': tp_price,
                                     'entry_timestamp': pd.Timestamp.now(tz='UTC'), 'order_id': order_resp.get('orderId'), 'client_order_id': order_resp.get('clientOrderId')}
            self.logger.info(f"[{self.strategy_id}] Position Entered: {self.current_position}")
        else: self.logger.error(f"[{self.strategy_id}] Failed to enter position: {order_resp}")


    async def _check_sl_tp(self, current_price: float):
        # ... (implementation from previous step)
        if not self.current_position or not self.is_active: return
        pos=self.current_position
        sl_hit=(pos['side']=='LONG' and current_price<=pos['sl']) or (pos['side']=='SHORT' and current_price>=pos['sl'])
        tp_hit=(pos['side']=='LONG' and current_price>=pos['tp']) or (pos['side']=='SHORT' and current_price<=pos['tp'])
        if sl_hit: await self._close_current_position(f"SL hit @{current_price}")
        elif tp_hit: await self._close_current_position(f"TP hit @{current_price}")


    async def _close_current_position(self, reason: str):
        # ... (implementation from previous step)
        if not self.current_position or not self.is_active: return
        pos=self.current_position; side_to_close="SELL" if pos['side']=="LONG" else "BUY"
        self.logger.info(f"[{self.strategy_id}] Closing {pos['side']} position for {self.symbol} due to: {reason}. Qty: {pos['quantity']}")
        order_resp = await self._place_market_order(self.symbol, side_to_close, pos['quantity'], positionSide=pos['side'], reduceOnly=True)
        if order_resp and order_resp.get('status') == 'FILLED': self.logger.info(f"[{self.strategy_id}] Position closed: {order_resp}")
        else: self.logger.error(f"[{self.strategy_id}] Failed to close position: {order_resp}")
        self.current_position = None


    async def on_order_update(self, order_update: Dict):
        # ... (implementation from previous step)
        client_oid = order_update.get('c','')
        if not client_oid or not client_oid.startswith(self.strategy_id): return
        self.logger.info(f"[{self.strategy_id}] Own order update: ClientOID={client_oid}, Status={order_update.get('X')}")
        # More detailed logic can be added here if strategy needs to react to partial fills, cancellations etc.
        # For now, current_position state is mainly managed by _enter_position and _close_current_position
        # upon their own market order fills.
        if self.current_position and order_update.get('X') == 'FILLED':
            # If the filled order was the one that established current_position
            if order_update.get('i') == self.current_position.get('order_id'):
                 # If it was a closing trade (reduceOnly is true, or opposite side of current position)
                 if order_update.get('R') or (order_update.get('S') != self.current_position.get('side')):
                      self.logger.info(f"[{self.strategy_id}] Position closing order {client_oid} FILLED. Position should be cleared.")
                      # self.current_position = None # This is handled by _close_current_position
            # If it was a SL/TP limit order that got filled (not used in current _enter_position)
            # elif client_oid == self.current_position.get('sl_order_id') or client_oid == self.current_position.get('tp_order_id'):
            #    self.current_position = None # Position closed by SL/TP limit order
        pass

    async def on_depth_update(self, symbol: str, depth_data: Dict): pass
    async def on_trade_update(self, symbol: str, trade_data: Dict): pass
    async def on_mark_price_update(self, symbol: str, mark_price_data: Dict):
        if self.current_position and self.is_active and mark_price_data.get('p'):
            await self._check_sl_tp(float(mark_price_data['p']))
```
