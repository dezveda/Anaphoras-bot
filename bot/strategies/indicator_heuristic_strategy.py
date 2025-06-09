import logging
import pandas as pd
import numpy as np
from typing import Dict, Optional, Any, List
import asyncio

from .base_strategy import BaseStrategy
OrderManager = Any
MarketDataProvider = Any
BasicRiskManager = Any

class IndicatorHeuristicStrategy(BaseStrategy):
    strategy_type_name: str = "IndicatorHeuristicStrategy"

    def __init__(self, strategy_id: str, params: Dict[str, Any],
                 order_manager: OrderManager,
                 market_data_provider: MarketDataProvider,
                 risk_manager: BasicRiskManager,
                 logger: Optional[logging.Logger] = None):
        super().__init__(strategy_id, params, order_manager, market_data_provider, risk_manager, logger)

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
            'min_order_qty': {'type': 'float', 'default': 0.001, 'desc': 'Minimum order quantity for the symbol.'}
        }

    async def start(self):
        self.strategy_type_name = self.__class__.strategy_type_name
        await super().start()
        initial_klines_needed = max(self.klines_buffer_size, self.rsi_period, self.ema_long_period, self.atr_period_for_sl_tp) + 5
        if self.backtest_mode: self.logger.info(f"[{self.strategy_id}] Backtest mode: Initial klines from BacktestEngine.")
        else:
            self.logger.info(f"[{self.strategy_id}] Live mode: Fetching initial {initial_klines_needed} klines...")
            hist_data = await self.market_data_provider.get_historical_klines(self.symbol, self.trade_timeframe, limit=initial_klines_needed)
            if hist_data is not None and not hist_data.empty:
                self.recent_klines_df = hist_data[['open', 'high', 'low', 'close', 'volume']].copy()
                self._update_indicators()
            else: self.logger.warning(f"[{self.strategy_id}] Could not fetch initial klines.")
            await self.market_data_provider.subscribe_to_kline_stream(self.symbol, self.trade_timeframe, self._handle_kline_wrapper)
        self.logger.info(f"[{self.strategy_id}] {self.strategy_type_name} started.")

    async def _handle_kline_wrapper(self, raw_ws_message: dict):
        # ... (same as previous strategy)
        kline_payload = raw_ws_message.get('data', raw_ws_message).get('k')
        if kline_payload: await self.on_kline_update(kline_payload.get('s'), kline_payload.get('i'), kline_payload)
        else: self.logger.warning(f"[{self.strategy_id}] WS kline message missing 'k': {raw_ws_message}")


    async def stop(self): await super().stop(); self.logger.info(f"[{self.strategy_id}] {self.strategy_type_name} stopped.")

    async def on_kline_update(self, symbol: str, interval: str, kline_data: Dict):
        # ... (same as previous strategy, ensures buffer update, indicator calc, and signal logic)
        if not self.is_active or symbol != self.symbol or interval != self.trade_timeframe: return
        if not kline_data.get('x', False) and not self.backtest_mode : return

        ts = pd.to_datetime(kline_data['t'], unit='ms', utc=True)
        new_kline = pd.Series({'open':float(kline_data['o']),'high':float(kline_data['h']),'low':float(kline_data['l']),'close':float(kline_data['c']),'volume':float(kline_data['v'])}, name=ts)
        if ts not in self.recent_klines_df.index: self.recent_klines_df = pd.concat([self.recent_klines_df, new_kline.to_frame().T])
        else: self.recent_klines_df.loc[ts] = new_kline
        if len(self.recent_klines_df) > self.klines_buffer_size: self.recent_klines_df = self.recent_klines_df.iloc[-self.klines_buffer_size:]

        if self.backtest_mode and 'atr' in kline_data: self.atr_value = float(kline_data.get('atr',0.0))
        self._update_indicators()

        if self.current_position: await self._check_sl_tp(float(kline_data['c']))
        elif self.atr_value and self.atr_value > 1e-8: await self._apply_heuristic_logic(kline_data)
        else: self.logger.debug(f"[{self.strategy_id}] ATR not valid ({self.atr_value}), skipping signal logic.")


    def _update_indicators(self):
        # ... (same as previous strategy, ensure self.rsi_series, self.ema_short_series, self.ema_long_series, self.atr_value are updated)
        if len(self.recent_klines_df) < 2: return
        df = self.recent_klines_df.copy(); df['close']=df['close'].astype(float); df['high']=df['high'].astype(float); df['low']=df['low'].astype(float)
        if len(df) >= self.rsi_period:
            delta=df['close'].diff(); gain=(delta.where(delta > 0,0.0)).ewm(com=self.rsi_period-1,adjust=False).mean(); loss=(-delta.where(delta < 0,0.0)).ewm(com=self.rsi_period-1,adjust=False).mean()
            self.rsi_series = 100-(100/(1+(gain/(loss+1e-9))))
        else: self.rsi_series=pd.Series(dtype=float)
        if len(df) >= self.ema_short_period: self.ema_short_series = df['close'].ewm(span=self.ema_short_period,adjust=False).mean()
        else: self.ema_short_series=pd.Series(dtype=float)
        if len(df) >= self.ema_long_period: self.ema_long_series = df['close'].ewm(span=self.ema_long_period,adjust=False).mean()
        else: self.ema_long_series=pd.Series(dtype=float)
        if not self.backtest_mode or self.atr_value is None or self.atr_value <= 1e-8 :
            if len(df) >= self.atr_period_for_sl_tp+1:
                hl=df['high']-df['low']; hc=np.abs(df['high']-df['close'].shift(1)); lc=np.abs(df['low']-df['close'].shift(1))
                rdf=pd.DataFrame({'hl':hl,'hc':hc,'lc':lc}); tr=rdf.max(axis=1)
                atr_s = tr.ewm(span=self.atr_period_for_sl_tp,adjust=False,min_periods=self.atr_period_for_sl_tp).mean()
                if not atr_s.empty and not pd.isna(atr_s.iloc[-1]): self.atr_value = atr_s.iloc[-1]
                else: self.atr_value = None
            else: self.atr_value = None

    async def _apply_heuristic_logic(self, kline_data: Dict):
        # ... (same as previous strategy, ensure logging uses self.logger)
        score=0; price=float(kline_data['c'])
        if not self.rsi_series.empty and not pd.isna(self.rsi_series.iloc[-1]):
            rsi=self.rsi_series.iloc[-1]
            if rsi < self.rsi_oversold: score+=self.score_rsi_oversold
            if rsi > self.rsi_overbought: score+=self.score_rsi_overbought
        if len(self.ema_short_series)>1 and len(self.ema_long_series)>1 and not pd.isna(self.ema_short_series.iloc[-1]) and not pd.isna(self.ema_long_series.iloc[-1]) and not pd.isna(self.ema_short_series.iloc[-2]) and not pd.isna(self.ema_long_series.iloc[-2]):
            s_prev,s_curr=self.ema_short_series.iloc[-2:]; l_prev,l_curr=self.ema_long_series.iloc[-2:]
            if s_prev<l_prev and s_curr>l_curr: score+=self.score_ema_bullish_cross
            if s_prev>l_prev and s_curr<l_curr: score+=self.score_ema_bearish_cross
        self.logger.debug(f"[{self.strategy_id}] Score: {score}, Px: {price:.{self.asset_price_precision}f}")
        if self.current_position: return
        sl_px = price - self.atr_value*self.sl_atr_multiplier if self.atr_value else price*(1-0.02)
        if score >= self.buy_score_threshold: await self._enter_position('LONG', price, sl_px)
        elif score <= self.sell_score_threshold:
            sl_px = price + self.atr_value*self.sl_atr_multiplier if self.atr_value else price*(1+0.02)
            await self._enter_position('SHORT', price, sl_px)


    async def _enter_position(self, side: str, entry_price: float, sl_price: float):
        # ... (implementation from previous strategy, ensure use of self.default_risk_per_trade_perc etc.)
        if not self.is_active or self.current_position: return
        if not self.risk_manager or not self.atr_value or self.atr_value <=1e-8: self.logger.warning(f"[{self.strategy_id}] Enter rejected: RM/ATR invalid."); return
        pos_side = side
        tp_px = round(entry_price+(self.atr_value*self.tp_atr_multiplier) if side=="LONG" else entry_price-(self.atr_value*self.tp_atr_multiplier), self.asset_price_precision)
        sl_price = round(sl_price, self.asset_price_precision)
        risk_usd = await self.risk_manager.calculate_position_size_usd(self.default_risk_per_trade_perc)
        if not risk_usd or risk_usd <=0: self.logger.warning(f"[{self.strategy_id}] Invalid risk USD: {risk_usd}"); return
        qty = self.risk_manager.calculate_quantity_from_risk_usd(risk_usd,entry_price,sl_price,self.asset_quantity_precision,self.min_order_qty)
        if not qty or qty <=0: self.logger.warning(f"[{self.strategy_id}] Invalid qty: {qty} for risk USD {risk_usd}"); return

        self.logger.info(f"[{self.strategy_id}] Entering {side}: Qty={qty}, Entry~{entry_price}, SL={sl_price}, TP={tp_px}")
        order_resp = await self._place_market_order(self.symbol,side,qty,positionSide=pos_side)
        if order_resp and order_resp.get('status')=='FILLED':
            filled_px=float(order_resp['avgPrice'])
            self.current_position = {'side':side,'entry_price':filled_px,'quantity':qty,'sl':sl_price,'tp':tp_px,
                                     'entry_timestamp':pd.Timestamp.now(tz='UTC'),'order_id':order_resp.get('orderId'),
                                     'client_order_id':order_resp.get('clientOrderId')}
            self.logger.info(f"[{self.strategy_id}] Position Entered: {self.current_position}")
        else: self.logger.error(f"[{self.strategy_id}] Failed to enter: {order_resp}")


    async def _check_sl_tp(self, current_price: float):
        # ... (implementation from previous strategy)
        if not self.current_position or not self.is_active: return
        pos=self.current_position
        sl_hit=(pos['side']=='LONG' and current_price<=pos['sl']) or (pos['side']=='SHORT' and current_price>=pos['sl'])
        tp_hit=(pos['side']=='LONG' and current_price>=pos['tp']) or (pos['side']=='SHORT' and current_price<=pos['tp'])
        if sl_hit: await self._close_current_position(f"SL hit @{current_price}")
        elif tp_hit: await self._close_current_position(f"TP hit @{current_price}")

    async def _close_current_position(self, reason: str):
        # ... (implementation from previous strategy)
        if not self.current_position or not self.is_active: return
        pos=self.current_position; side_to_close="SELL" if pos['side']=="LONG" else "BUY"
        self.logger.info(f"[{self.strategy_id}] Closing {pos['side']} pos for {self.symbol} due to: {reason}. Qty: {pos['quantity']}")
        order_resp = await self._place_market_order(self.symbol,side_to_close,pos['quantity'],positionSide=pos['side'],reduceOnly=True)
        if order_resp and order_resp.get('status')=='FILLED': self.logger.info(f"[{self.strategy_id}] Position closed: {order_resp}")
        else: self.logger.error(f"[{self.strategy_id}] Failed to close: {order_resp}")
        self.current_position=None

    async def on_order_update(self, order_update: Dict):
        # ... (implementation from previous strategy)
        client_oid=order_update.get('c','')
        if not client_oid or not client_oid.startswith(self.strategy_id): return
        self.logger.info(f"[{self.strategy_id}] Own order update: ClientOID={client_oid}, Status={order_update.get('X')}")
        if self.current_position and self.current_position.get('client_order_id') == client_oid and order_update.get('X') == 'FILLED':
             if order_update.get('R') or (order_update.get('S') != self.current_position.get('side')): # If reduceOnly or opposite side
                self.logger.info(f"[{self.strategy_id}] Position closing order {client_oid} FILLED via WS. Clearing pos state.")
                self.current_position = None


    async def on_depth_update(self, symbol: str, depth_data: Dict): pass
    async def on_trade_update(self, symbol: str, trade_data: Dict): pass
    async def on_mark_price_update(self, symbol: str, mark_price_data: Dict):
        if self.current_position and self.is_active and mark_price_data.get('p'):
            await self._check_sl_tp(float(mark_price_data['p']))

```
