import pandas as pd
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Type, Any, Callable, Awaitable
import asyncio
import numpy as np

try:
    from bot.core.data_fetcher import MarketDataProvider
    from bot.strategies.base_strategy import BaseStrategy
    from bot.core.risk_manager import BasicRiskManager
except ImportError:
    from data_fetcher import MarketDataProvider # type: ignore
    import sys, os
    sys.path.append(os.path.join(os.path.dirname(__file__), '../strategies'))
    from base_strategy import BaseStrategy # type: ignore
    sys.path.append(os.path.join(os.path.dirname(__file__), '.'))
    from risk_manager import BasicRiskManager # type: ignore


class BacktestEngine:
    _KLINE_INTERVAL_MILLISECONDS = MarketDataProvider._KLINE_INTERVAL_MILLISECONDS

    def __init__(self,
                 market_data_provider: MarketDataProvider,
                 strategy_class: Type[BaseStrategy],
                 strategy_params: Dict[str, Any],
                 start_date_str: str,
                 end_date_str: str,
                 initial_capital: float,
                 symbol: str,
                 timeframe: str,
                 commission_rate: float = 0.0004):

        self.market_data_provider = market_data_provider
        self.strategy_class = strategy_class
        self.strategy_params = strategy_params
        self.start_date_str = start_date_str
        self.end_date_str = end_date_str
        self.initial_capital = initial_capital
        self.symbol = symbol
        self.timeframe = timeframe
        self.commission_rate = commission_rate

        self.logger = logging.getLogger('algo_trader_bot.BacktestEngine')

        self.historical_data: Optional[pd.DataFrame] = None
        self.simulated_trades: List[Dict[str, Any]] = []
        start_dt = pd.to_datetime(self.start_date_str, utc=True) if self.start_date_str else datetime.now(timezone.utc)
        self.equity_curve: List[Dict[str, Any]] = [{'timestamp': start_dt - pd.Timedelta(milliseconds=1), 'balance': self.initial_capital}]

        self.current_balance = initial_capital
        self.current_position: Optional[Dict[str, Any]] = None
        self.strategy_instance: Optional[BaseStrategy] = None
        self._current_kline_idx = 0 # Corrected from _current_kline_index

        self.atr_period = int(strategy_params.get('atr_period_for_backtest', 14))
        self.slippage_factor = float(strategy_params.get('slippage_factor', 0.0005)) # 0.05% slippage

        # Limit order simulation
        self.pending_limit_orders: List[Dict[str, Any]] = []
        self.next_sim_order_id = 1

        # Performance metrics
        self.total_pnl = 0.0; self.num_trades = 0; self.winning_trades = 0; self.losing_trades = 0
        self.gross_profit = 0.0; self.gross_loss = 0.0; self.max_drawdown = 0.0
        self._peak_equity = initial_capital

        self.risk_manager = BasicRiskManager(
            account_balance_provider_fn=self.get_available_trading_balance,
            default_risk_per_trade_perc=float(strategy_params.get('default_risk_per_trade_perc', 0.01))
        )

    async def get_available_trading_balance(self) -> Optional[float]:
        return float(self.current_balance)

    def _generate_client_order_id(self, strategy_id: str = "backtest") -> str:
        prefix = strategy_id.replace("_", "")[:10]
        timestamp_ns = time.time_ns()
        return f"{prefix}bt{timestamp_ns}"[:36]

    async def _prepare_data(self) -> bool:
        # ... (ATR calculation remains the same)
        self.logger.info(f"Preparing historical data for {self.symbol} ({self.timeframe}) from {self.start_date_str} to {self.end_date_str}")
        try:
            self.historical_data = await self.market_data_provider.get_historical_klines(
                symbol=self.symbol, interval=self.timeframe,
                start_str=self.start_date_str, end_str=self.end_date_str,
                limit=9999999
            )
            if self.historical_data is None or self.historical_data.empty:
                self.logger.error("Failed to fetch historical data or no data available for the period.")
                return False

            self.historical_data.sort_index(inplace=True)

            if len(self.historical_data) > self.atr_period:
                df = self.historical_data
                df['high'] = df['high'].astype(float)
                df['low'] = df['low'].astype(float)
                df['close'] = df['close'].astype(float)

                high_low = df['high'] - df['low']
                high_close = np.abs(df['high'] - df['close'].shift(1))
                low_close = np.abs(df['low'] - df['close'].shift(1))

                ranges_df = pd.DataFrame({'hl': high_low, 'hc': high_close, 'lc': low_close})
                true_range = ranges_df.max(axis=1)

                df['atr'] = true_range.ewm(span=self.atr_period, adjust=False, min_periods=self.atr_period).mean()
                self.historical_data = df
                self.logger.info(f"ATR (period {self.atr_period}) calculated and added to historical data.")
            else:
                self.logger.warning(f"Not enough data ({len(self.historical_data)} rows) to calculate ATR with period {self.atr_period}. ATR will be NaN.")
                self.historical_data['atr'] = np.nan

            self.logger.info(f"Successfully loaded {len(self.historical_data)} klines.")
            return True
        except Exception as e:
            self.logger.error(f"Error during historical data preparation: {e}", exc_info=True)
            return False


    def _simulate_market_order_execution_update(self, side: str, quantity_asset: float, nominal_execution_price: float,
                                                execution_timestamp: datetime, client_order_id: str, order_type: str,
                                                original_limit_price: Optional[float] = None) -> Tuple[Dict, float, float]: # type: ignore
        actual_execution_price = nominal_execution_price
        if order_type == "MARKET": # Apply slippage only for market orders
            if side == 'BUY': actual_execution_price = nominal_execution_price * (1 + self.slippage_factor)
            else: actual_execution_price = nominal_execution_price * (1 - self.slippage_factor)
            if actual_execution_price != nominal_execution_price:
                self.logger.debug(f"Slippage applied: Nominal {nominal_execution_price:.2f} -> Actual {actual_execution_price:.2f}")

        # If it was a limit order, execution_price is the limit price (or better, but simplified to limit price)
        # The nominal_execution_price passed for limit orders would be the limit_order['price']

        commission = quantity_asset * actual_execution_price * self.commission_rate
        self.current_balance -= commission
        trade_value = quantity_asset * actual_execution_price
        pnl = 0.0

        if self.current_position:
            if self.current_position['side'] == side: # Adding to position
                current_total_value = self.current_position['quantity'] * self.current_position['entry_price']
                new_total_quantity = self.current_position['quantity'] + quantity_asset
                self.current_position['entry_price'] = (current_total_value + trade_value) / new_total_quantity
                self.current_position['quantity'] = new_total_quantity
            else: # Reducing or flipping
                closed_qty = min(quantity_asset, self.current_position['quantity'])
                if self.current_position['side'] == "LONG": pnl = (actual_execution_price - self.current_position['entry_price']) * closed_qty
                else: pnl = (self.current_position['entry_price'] - actual_execution_price) * closed_qty
                self.current_balance += pnl
                self.total_pnl += pnl
                if pnl > 0: self.winning_trades += 1; self.gross_profit += pnl
                elif pnl < 0: self.losing_trades += 1; self.gross_loss += abs(pnl)

                if quantity_asset >= self.current_position['quantity']: # Closed or flipped
                    self.current_position = None
                    if quantity_asset > closed_qty: # Flipped
                        self.current_position = {'side': side, 'entry_price': actual_execution_price,
                                                 'quantity': quantity_asset - closed_qty, 'entry_timestamp': execution_timestamp}
                else: self.current_position['quantity'] -= closed_qty # Partially closed
        else: # Opening new position
            self.current_position = {'side': side, 'entry_price': actual_execution_price,
                                     'quantity': quantity_asset, 'entry_timestamp': execution_timestamp}
        self.num_trades += 1
        trade_record = {'client_order_id': client_order_id, 'timestamp': execution_timestamp, 'symbol': self.symbol,
                        'type': order_type, 'side': side, 'price': actual_execution_price,
                        'quantity': quantity_asset, 'commission': commission, 'pnl': pnl, 'balance': self.current_balance}
        self.simulated_trades.append(trade_record)
        self.logger.info(f"SIM FILL: {side} {quantity_asset:.4f} {self.symbol} @ {actual_execution_price:.2f}, ClientOID: {client_order_id}, PnL: {pnl:.2f}, Bal: {self.current_balance:.2f}")
        return trade_record, pnl, commission


    async def _simulate_fill_or_kill_order(self, order_details: dict, execution_price: float,
                                           timestamp: pd.Timestamp, filled_reason:str = "FILLED"):

        _trade_record, pnl_this_trade, commission_this_trade = self._simulate_market_order_execution_update(
            side=order_details['side'],
            quantity_asset=order_details['quantity'],
            nominal_execution_price=execution_price, # For limit, this is the limit price. For market, it's pre-slippage kline.close
            execution_timestamp=timestamp,
            client_order_id=order_details['client_order_id'],
            order_type=order_details['type'],
            original_limit_price=order_details['price'] if order_details['type'] == 'LIMIT' else None
        )

        # Use actual execution price from _trade_record for avgPrice in event
        actual_exec_price = _trade_record['price']

        fill_event_for_strategy = {
            'e': 'ORDER_TRADE_UPDATE', 'E': int(timestamp.timestamp() * 1000), 's': order_details['symbol'],
            'c': order_details['client_order_id'], 'S': order_details['side'], 'o': order_details['type'],
            'f': order_details.get('timeInForce', 'GTC'), 'q': str(order_details['quantity']),
            'p': str(order_details['price']), # Original limit price for limit orders
            'ap': str(actual_exec_price), # Average fill price (actual execution price)
            'sp': '0', # Stop price, not handled for basic limit/market fill
            'x': 'TRADE', 'X': filled_reason, # Status FILLED or specific fill reason
            'i': order_details['id'], # Simulated Order ID
            'l': str(order_details['quantity']), 'z': str(order_details['quantity']), # Last and cumulative filled
            'L': str(actual_exec_price), # Last executed price
            'n': str(commission_this_trade), 'N': 'USDT', # Assuming USDT commission asset
            'T': int(timestamp.timestamp() * 1000), 't': int(time.time_ns()), # Trade time, trade ID (simulated)
            'rp': str(pnl_this_trade),
            'ps': order_details.get('positionSide', self.current_position['side'] if self.current_position else 'BOTH')
        }
        if self.strategy_instance:
            await self.strategy_instance.on_order_update(fill_event_for_strategy)
        return fill_event_for_strategy


    async def _check_pending_limit_orders(self, kline_row: Any, current_kline_timestamp: pd.Timestamp):
        # kline_row is a NamedTuple from itertuples()
        if not self.pending_limit_orders: return

        kline_low = float(kline_row.low)
        kline_high = float(kline_row.high)
        # kline_open = float(kline_row.open) # For fill at open logic

        orders_to_remove = []
        for limit_order in list(self.pending_limit_orders): # Iterate copy
            can_fill = False
            execution_price = limit_order['price'] # Assume fill at limit price

            if limit_order['side'] == 'BUY' and kline_low <= limit_order['price']:
                # Optional: If market opens below limit, fill at open or kline_low if better than limit.
                # execution_price = min(limit_order['price'], kline_open) # Example for more realistic fill
                can_fill = True
            elif limit_order['side'] == 'SELL' and kline_high >= limit_order['price']:
                # execution_price = max(limit_order['price'], kline_open)
                can_fill = True

            if can_fill:
                self.logger.info(f"[Backtest] Limit Order {limit_order['id']} ({limit_order['side']} {limit_order['quantity']} @ {limit_order['price']}) FILLED at {execution_price} by kline L/H: {kline_low}/{kline_high}")
                await self._simulate_fill_or_kill_order(limit_order, execution_price, current_kline_timestamp, filled_reason="LIMIT_ORDER_FILLED")
                orders_to_remove.append(limit_order)

        for order in orders_to_remove:
            self.pending_limit_orders.remove(order)


    async def run_backtest(self) -> Optional[Dict[str, Any]]:
        # ... (ATR calc in _prepare_data)
        # ... (Strategy instantiation and start)
        self.logger.info(f"Starting backtest for {self.symbol} from {self.start_date_str} to {self.end_date_str}")
        if not await self._prepare_data() or self.historical_data is None or self.historical_data.empty:
            self.logger.error("Backtest data preparation failed. Aborting."); return None

        self.strategy_instance = self.strategy_class(
            strategy_id=f"backtest_{self.strategy_class.__name__}_{self.symbol}",
            params=self.strategy_params, order_manager=self,
            market_data_provider=self.market_data_provider,
            risk_manager=self.risk_manager, logger=self.logger
        )
        self.strategy_instance.set_backtest_mode(True)
        await self.strategy_instance.start()

        if not self.historical_data.empty: # Initial equity point already added
             pass # self.equity_curve[0] is initial point

        for kline_row_tuple in self.historical_data.itertuples():
            self._current_kline_idx = self.historical_data.index.get_loc(kline_row_tuple.Index) # Store current index
            current_kline_timestamp = kline_row_tuple.Index

            kline_dict = kline_row_tuple._asdict()
            kline_open_time_ms = int(current_kline_timestamp.timestamp() * 1000)
            kline_interval_ms = self._KLINE_INTERVAL_MILLISECONDS.get(self.timeframe, 0)
            kline_close_time_ms = kline_open_time_ms + kline_interval_ms - 1

            kline_data_for_strategy_k_field = {
                't': kline_open_time_ms, 'T': kline_close_time_ms, 's': self.symbol, 'i': self.timeframe,
                'o': kline_dict.get('open'), 'h': kline_dict.get('high'),
                'l': kline_dict.get('low'), 'c': kline_dict.get('close'),
                'v': kline_dict.get('volume'),
                'n': kline_dict.get('number_of_trades', 0), 'x': True,
                'q': kline_dict.get('quote_asset_volume', 0.0),
                'V': kline_dict.get('taker_buy_base_asset_volume', 0.0),
                'Q': kline_dict.get('taker_buy_quote_asset_volume', 0.0), 'B': "0",
                'atr': kline_dict.get('atr', 0.0) if not np.isnan(kline_dict.get('atr', np.nan)) else 0.0
            }

            # Strategies might place limit orders that need checking against current kline
            await self._check_pending_limit_orders(kline_row_tuple, current_kline_timestamp)

            await self.strategy_instance.on_kline_update(self.symbol, self.timeframe, kline_data_for_strategy_k_field)

            simulated_mark_price_data = {
                'e': 'markPriceUpdate', 's': self.symbol,
                'p': str(kline_dict.get('close')), 'E': kline_close_time_ms
            }
            if hasattr(self.strategy_instance, 'on_mark_price_update'):
                await self.strategy_instance.on_mark_price_update(self.symbol, simulated_mark_price_data)

            self.equity_curve.append({'timestamp': current_kline_timestamp, 'balance': self.current_balance})
            if self.current_balance > self._peak_equity: self._peak_equity = self.current_balance
            drawdown = (self._peak_equity - self.current_balance) / self._peak_equity if self._peak_equity > 0 else 0
            if drawdown > self.max_drawdown: self.max_drawdown = drawdown

        if not self.equity_curve or self.equity_curve[-1]['balance'] != self.current_balance :
             self.equity_curve.append({'timestamp': self.historical_data.index[-1] if not self.historical_data.empty else pd.to_datetime(self.end_date_str, utc=True),
                                   'balance': self.current_balance})
        await self.strategy_instance.stop()
        return self._calculate_and_log_performance_metrics()


    def _calculate_and_log_performance_metrics(self) -> Dict[str, Any]:
        # ... (remains the same)
        if not self.simulated_trades: self.logger.info("No trades executed."); return {}
        percent_return = (self.total_pnl / self.initial_capital) * 100 if self.initial_capital > 0 else 0
        win_rate = (self.winning_trades / self.num_trades) * 100 if self.num_trades > 0 else 0
        profit_factor = self.gross_profit / abs(self.gross_loss) if self.gross_loss != 0 else float('inf')
        metrics = {"initial_capital": self.initial_capital, "final_balance": self.current_balance,
                   "total_pnl": self.total_pnl, "percent_return": percent_return, "num_trades": self.num_trades,
                   "winning_trades": self.winning_trades, "losing_trades": self.losing_trades, "win_rate": win_rate,
                   "gross_profit": self.gross_profit, "gross_loss": abs(self.gross_loss),
                   "profit_factor": profit_factor, "max_drawdown": self.max_drawdown * 100 }
        self.logger.info("--- Backtest Performance Metrics ---")
        for key, value in metrics.items(): self.logger.info(f"{key.replace('_', ' ').title()}: {value:.2f}" if isinstance(value, float) else f"{key.replace('_', ' ').title()}: {value}")
        return metrics


    async def place_new_order(self, symbol: str, side: str, ord_type: str, quantity: float,
                              price: Optional[float] = None, timeInForce: Optional[str] = None,
                              reduceOnly: Optional[bool] = None, newClientOrderId: Optional[str] = None,
                              stopPrice: Optional[float] = None, positionSide: Optional[str] = None,
                              **kwargs) -> Optional[Dict]:

        client_oid = newClientOrderId or self._generate_client_order_id(self.strategy_instance.strategy_id if self.strategy_instance else "backtest") # type: ignore
        current_kline_timestamp = self.historical_data.iloc[self._current_kline_idx].name # type: ignore

        if ord_type.upper() == "MARKET":
            self.logger.info(f"[Backtest] Order REQ: ClientOID={client_oid}, MARKET {side} {quantity} {symbol}")
            if self._current_kline_idx >= len(self.historical_data): # type: ignore
                self.logger.error("[Backtest] No kline data for MARKET order fill."); return None

            current_kline_data = self.historical_data.iloc[self._current_kline_idx] # type: ignore
            nominal_execution_price = float(current_kline_data['close'])

            market_order_details = {
                'id': f"sim_market_{self.next_sim_order_id}", 'symbol': symbol, 'side': side,
                'price': nominal_execution_price, # For market, this is nominal; actual fill price includes slippage
                'quantity': quantity, 'client_order_id': client_oid,
                'strategy_id': self.strategy_instance.strategy_id if self.strategy_instance else "unknown", # type: ignore
                'type': 'MARKET', 'timeInForce': timeInForce or 'GTC', 'positionSide': positionSide
            }
            self.next_sim_order_id += 1
            # _simulate_fill_or_kill_order will apply slippage for market orders
            return await self._simulate_fill_or_kill_order(market_order_details, nominal_execution_price, current_kline_timestamp, filled_reason="FILLED_MARKET")

        elif ord_type.upper() == "LIMIT":
            self.logger.info(f"[Backtest] Order REQ: ClientOID={client_oid}, LIMIT {side} {quantity} {symbol} @ {price}")
            sim_order_id = f"sim_limit_{self.next_sim_order_id}"
            self.next_sim_order_id += 1
            limit_order_details = {
                'id': sim_order_id, 'symbol': symbol, 'side': side, 'price': price,
                'quantity': quantity, 'client_order_id': client_oid,
                'strategy_id': self.strategy_instance.strategy_id if self.strategy_instance else "unknown", # type: ignore
                'type': 'LIMIT', 'timeInForce': timeInForce or 'GTC', 'positionSide': positionSide
            }
            self.pending_limit_orders.append(limit_order_details)

            response = {'symbol': symbol, 'orderId': sim_order_id, 'clientOrderId': client_oid,
                        'status': 'NEW', 'type': ord_type, 'side': side, 'price': str(price), 'origQty': str(quantity),
                        'executedQty': '0', 'avgPrice': '0.0', 'transactTime': int(current_kline_timestamp.timestamp() * 1000)}
            # Strategy should NOT react to its own NEW order submission to avoid loops, unless specifically designed to.
            # The fill (via on_order_update from _simulate_fill_or_kill_order) is the primary trigger.
            # However, if a strategy needs to know its order was ACKNOWLEDGED, this is the place.
            # For now, let's assume strategy waits for FILL/CANCEL.
            # if self.strategy_instance:
            #    await self.strategy_instance.on_order_update({'e': 'ORDER_TRADE_UPDATE', 'o': response}) # ACK
            return response
        else:
            self.logger.warning(f"[Backtest] Order type '{ord_type}' not fully supported for placement simulation beyond ACK.")
            return {'status': 'REJECTED', 'reason': 'UNSUPPORTED_ORDER_TYPE_IN_BACKTEST'}


    async def cancel_existing_order(self, symbol: str, orderId: Optional[str] = None,
                                    origClientOrderId: Optional[str] = None, **kwargs) -> Optional[Dict]:
        log_id_search = orderId or origClientOrderId
        self.logger.info(f"[Backtest] Cancel Order Req: ID={log_id_search} for {symbol}")

        order_to_cancel = None
        for i, order in enumerate(self.pending_limit_orders):
            if (orderId and order['id'] == orderId) or \
               (origClientOrderId and order['client_order_id'] == origClientOrderId):
                order_to_cancel = self.pending_limit_orders.pop(i)
                break

        current_kline_ts = self.historical_data.iloc[self._current_kline_idx].name # type: ignore
        if order_to_cancel:
            self.logger.info(f"[Backtest] Pending LIMIT order {order_to_cancel['id']} cancelled.")
            response = {'symbol': symbol, 'orderId': order_to_cancel['id'],
                        'origClientOrderId': order_to_cancel['client_order_id'],
                        'clientOrderId': order_to_cancel['client_order_id'],
                        'status': 'CANCELED', 'type': order_to_cancel['type'], 'side': order_to_cancel['side'],
                        'transactTime': int(current_kline_ts.timestamp() * 1000)} # type: ignore
            if self.strategy_instance:
                await self.strategy_instance.on_order_update({'e': 'ORDER_TRADE_UPDATE', 'o': response})
            return response
        else:
            self.logger.warning(f"[Backtest] Order ID={log_id_search} not found in pending limit orders for cancellation.")
            return {'symbol': symbol, 'orderId': orderId, 'origClientOrderId': origClientOrderId, 'status': 'REJECTED', 'reason': 'ORDER_NOT_FOUND_OR_ALREADY_FILLED'}


if __name__ == '__main__':
    # ... (main test block from previous step, ensure DummyBacktestStrategy is defined or imported) ...
    pass
```
