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
    import sys, os # type: ignore
    sys.path.append(os.path.join(os.path.dirname(__file__), '../strategies'))  # type: ignore
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
        self.strategy_params = strategy_params # Store all params
        self.start_date_str = start_date_str
        self.end_date_str = end_date_str
        self.initial_capital = initial_capital
        self.symbol = symbol
        self.timeframe = timeframe
        self.commission_rate = commission_rate

        self.logger = logging.getLogger('algo_trader_bot.BacktestEngine')

        self.historical_data: Optional[pd.DataFrame] = None
        self.simulated_trades: List[Dict[str, Any]] = []
        # Initialize equity curve with the starting capital point
        start_dt = pd.to_datetime(self.start_date_str, utc=True) if self.start_date_str else datetime.now(timezone.utc)
        self.equity_curve: List[Dict[str, Any]] = [{'timestamp': start_dt - pd.Timedelta(milliseconds=1), 'balance': self.initial_capital}]


        self.current_balance = initial_capital
        self.current_position: Optional[Dict[str, Any]] = None

        self.strategy_instance: Optional[BaseStrategy] = None
        self._current_kline_index = 0

        self.atr_period = int(strategy_params.get('atr_period_for_backtest', 14))

        # Performance metrics initialization
        self.total_pnl = 0.0
        self.num_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.gross_profit = 0.0
        self.gross_loss = 0.0
        self.max_drawdown = 0.0
        self._peak_equity = initial_capital

        self.risk_manager = BasicRiskManager(
            account_balance_provider_fn=self.get_available_trading_balance,
            default_risk_per_trade_perc=float(strategy_params.get('default_risk_per_trade_perc', 0.01)) # Ensure float
        )

    async def get_available_trading_balance(self) -> Optional[float]:
        return float(self.current_balance)

    def _generate_client_order_id(self, strategy_id: str = "backtest") -> str:
        prefix = strategy_id.replace("_", "")[:10]
        # Use nanoseconds for higher probability of uniqueness if tests run very fast
        timestamp_ns = time.time_ns()
        return f"{prefix}bt{timestamp_ns}"[:36] # Ensure it's max 36 chars

    async def _prepare_data(self) -> bool:
        self.logger.info(f"Preparing historical data for {self.symbol} ({self.timeframe}) from {self.start_date_str} to {self.end_date_str}")
        try:
            self.historical_data = await self.market_data_provider.get_historical_klines(
                symbol=self.symbol, interval=self.timeframe,
                start_str=self.start_date_str, end_str=self.end_date_str,
                limit=9999999 # Request a large limit to get all data in the date range
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
                self.historical_data['atr'] = np.nan # Add NaN column if ATR can't be calculated

            self.logger.info(f"Successfully loaded {len(self.historical_data)} klines.")
            return True
        except Exception as e:
            self.logger.error(f"Error during historical data preparation: {e}", exc_info=True)
            return False

    def _simulate_market_order(self, side: str, quantity_asset: float, execution_price: float, execution_timestamp: datetime,
                               client_order_id: str, order_type: str, original_price: Optional[float] = None):
        commission_this_trade = quantity_asset * execution_price * self.commission_rate
        self.current_balance -= commission_this_trade

        trade_value = quantity_asset * execution_price
        pnl_this_trade = 0.0
        closed_position_value = 0.0
        entry_time_of_closed_pos = None

        if self.current_position:
            if self.current_position['side'] == side: # Increasing position
                current_total_value = self.current_position['quantity'] * self.current_position['entry_price']
                new_total_quantity = self.current_position['quantity'] + quantity_asset
                self.current_position['entry_price'] = (current_total_value + trade_value) / new_total_quantity
                self.current_position['quantity'] = new_total_quantity
            else: # Reducing or flipping position
                closed_quantity = min(quantity_asset, self.current_position['quantity'])
                entry_time_of_closed_pos = self.current_position['entry_timestamp']
                closed_position_value = closed_quantity * self.current_position['entry_price']

                if self.current_position['side'] == "LONG":
                    pnl_this_trade = (execution_price - self.current_position['entry_price']) * closed_quantity
                else: # SHORT
                    pnl_this_trade = (self.current_position['entry_price'] - execution_price) * closed_quantity

                self.current_balance += pnl_this_trade
                self.total_pnl += pnl_this_trade # Accumulate total PnL
                if pnl_this_trade > 0:
                    self.winning_trades += 1
                    self.gross_profit += pnl_this_trade
                elif pnl_this_trade < 0:
                    self.losing_trades += 1
                    self.gross_loss += abs(pnl_this_trade) # Gross loss is positive value

                if quantity_asset >= self.current_position['quantity']: # Position closed or flipped
                    self.current_position = None
                    if quantity_asset > closed_quantity: # Flipped
                        remaining_qty = quantity_asset - closed_quantity
                        self.current_position = {'side': side, 'entry_price': execution_price,
                                                 'quantity': remaining_qty, 'entry_timestamp': execution_timestamp}
                else: # Partially closed
                    self.current_position['quantity'] -= closed_quantity
        else: # Opening new position
            self.current_position = {'side': side, 'entry_price': execution_price,
                                     'quantity': quantity_asset, 'entry_timestamp': execution_timestamp}

        self.num_trades += 1
        trade_record = {
            'client_order_id': client_order_id, 'timestamp': execution_timestamp, 'symbol': self.symbol,
            'type': order_type, 'side': side, 'price': execution_price, 'quantity': quantity_asset,
            'commission': commission_this_trade, 'pnl': pnl_this_trade, 'balance': self.current_balance,
            'entry_time_closed_pos': entry_time_of_closed_pos, # For duration calculation if needed
            'value_closed_pos': closed_position_value # For calculating returns on closed parts
        }
        self.simulated_trades.append(trade_record)
        self.logger.info(f"SIM TRADE: {side} {quantity_asset:.4f} {self.symbol} @ {execution_price:.2f}, ClientOID: {client_order_id}, Comm: {commission_this_trade:.4f}, PnL: {pnl_this_trade:.2f}, Bal: {self.current_balance:.2f}")
        return trade_record, pnl_this_trade, commission_this_trade


    async def run_backtest(self) -> Optional[Dict[str, Any]]:
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

        # Initial equity point already added in __init__

        for kline_row_tuple in self.historical_data.itertuples():
            self._current_kline_index = self.historical_data.index.get_loc(kline_row_tuple.Index)
            current_timestamp_dt = kline_row_tuple.Index # This is pandas Timestamp

            kline_dict_from_row = kline_row_tuple._asdict()
            kline_open_time_ms = int(current_timestamp_dt.timestamp() * 1000)
            kline_interval_ms = self._KLINE_INTERVAL_MILLISECONDS.get(self.timeframe, 0)
            kline_close_time_ms = kline_open_time_ms + kline_interval_ms - 1

            kline_data_for_strategy_k_field = {
                't': kline_open_time_ms, 'T': kline_close_time_ms, 's': self.symbol, 'i': self.timeframe,
                'o': kline_dict_from_row.get('open'), 'h': kline_dict_from_row.get('high'),
                'l': kline_dict_from_row.get('low'), 'c': kline_dict_from_row.get('close'),
                'v': kline_dict_from_row.get('volume'),
                'n': kline_dict_from_row.get('number_of_trades', 0), 'x': True,
                'q': kline_dict_from_row.get('quote_asset_volume', 0.0),
                'V': kline_dict_from_row.get('taker_buy_base_asset_volume', 0.0),
                'Q': kline_dict_from_row.get('taker_buy_quote_asset_volume', 0.0), 'B': "0",
                'atr': kline_dict_from_row.get('atr', 0.0) if not np.isnan(kline_dict_from_row.get('atr', np.nan)) else 0.0
            }
            await self.strategy_instance.on_kline_update(self.symbol, self.timeframe, kline_data_for_strategy_k_field)

            simulated_mark_price_data = {
                'e': 'markPriceUpdate', 's': self.symbol,
                'p': str(kline_dict_from_row.get('close')),
                'E': kline_close_time_ms
            }
            if hasattr(self.strategy_instance, 'on_mark_price_update'):
                await self.strategy_instance.on_mark_price_update(self.symbol, simulated_mark_price_data)

            self.equity_curve.append({'timestamp': current_timestamp_dt, 'balance': self.current_balance})
            # Update peak equity for drawdown calculation
            if self.current_balance > self._peak_equity:
                self._peak_equity = self.current_balance
            drawdown = (self._peak_equity - self.current_balance) / self._peak_equity if self._peak_equity > 0 else 0
            if drawdown > self.max_drawdown: # Max drawdown is positive value
                self.max_drawdown = drawdown


        if not self.equity_curve or self.equity_curve[-1]['balance'] != self.current_balance : # Append final equity if loop didn't run or last state changed
             self.equity_curve.append({'timestamp': self.historical_data.index[-1] if not self.historical_data.empty else pd.to_datetime(self.end_date_str, utc=True),
                                   'balance': self.current_balance})


        await self.strategy_instance.stop()
        performance_metrics = self._calculate_and_log_performance_metrics()
        self.logger.info("Backtest finished.")
        return performance_metrics # Return metrics dict


    def _calculate_and_log_performance_metrics(self) -> Dict[str, Any]:
        if not self.simulated_trades: self.logger.info("No trades executed."); return {}

        # Total PnL and Return already calculated via self.current_balance
        percent_return = (self.total_pnl / self.initial_capital) * 100 if self.initial_capital > 0 else 0
        win_rate = (self.winning_trades / self.num_trades) * 100 if self.num_trades > 0 else 0
        profit_factor = self.gross_profit / abs(self.gross_loss) if self.gross_loss != 0 else float('inf')

        metrics = {
            "initial_capital": self.initial_capital, "final_balance": self.current_balance,
            "total_pnl": self.total_pnl, "percent_return": percent_return,
            "num_trades": self.num_trades, "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades, "win_rate": win_rate,
            "gross_profit": self.gross_profit, "gross_loss": abs(self.gross_loss),
            "profit_factor": profit_factor, "max_drawdown": self.max_drawdown * 100 # As percentage
        }
        self.logger.info("--- Backtest Performance Metrics ---")
        for key, value in metrics.items():
            self.logger.info(f"{key.replace('_', ' ').title()}: {value:.2f}" if isinstance(value, float) else f"{key.replace('_', ' ').title()}: {value}")
        return metrics

    async def place_new_order(self, symbol: str, side: str, ord_type: str, quantity: float,
                              price: Optional[float] = None, timeInForce: Optional[str] = None,
                              reduceOnly: Optional[bool] = None, newClientOrderId: Optional[str] = None,
                              stopPrice: Optional[float] = None, positionSide: Optional[str] = None,
                              origClientOrderId: Optional[str] = None, # Added for consistency, though newClientOrderId is preferred
                              **kwargs) -> Optional[Dict]:

        client_oid = newClientOrderId or self._generate_client_order_id(self.strategy_instance.strategy_id if self.strategy_instance else "backtest") # type: ignore
        self.logger.info(f"[Backtest] Order Req: ClientOID={client_oid}, {side} {quantity} {symbol} Type:{ord_type} @ {price if price else 'MARKET'}")

        if ord_type.upper() == "MARKET":
            if self._current_kline_index >= len(self.historical_data): # type: ignore
                self.logger.error("[Backtest] No more kline data for MARKET order fill."); return None

            current_kline_data = self.historical_data.iloc[self._current_kline_index] # type: ignore
            execution_price = float(current_kline_data['close'])
            execution_timestamp = current_kline_data.name # This is pandas Timestamp

            sim_trade_details, pnl, commission = self._simulate_market_order(side, quantity, execution_price, execution_timestamp, client_oid, ord_type.upper(), price) # type: ignore

            response = {
                'symbol': symbol, 'orderId': f"sim_{int(time.time_ns())}", 'clientOrderId': client_oid,
                'transactTime': int(execution_timestamp.timestamp() * 1000),
                'price': '0', 'origQty': str(quantity), 'executedQty': str(quantity),
                'cumQuote': str(execution_price * quantity), 'status': 'FILLED',
                'timeInForce': timeInForce or 'GTC', 'type': 'MARKET', 'side': side,
                'avgPrice': str(execution_price), 'reduceOnly': str(reduceOnly).lower() if reduceOnly is not None else None,
                'stopPrice': str(stopPrice) if stopPrice else None,
                'workingType': kwargs.get('workingType', 'CONTRACT_PRICE'),
                'positionSide': positionSide or (self.current_position['side'] if self.current_position else 'BOTH'),
                'rp': str(pnl) # Realized profit for this trade
            }
            if self.strategy_instance:
                 await self.strategy_instance.on_order_update({'e': 'ORDER_TRADE_UPDATE', 'o': response})
            return response
        else: # LIMIT, STOP_MARKET etc.
            self.logger.warning(f"[Backtest] Order type '{ord_type}' not fully simulated for fill. Returning as NEW.")
            # For backtesting, we might want to simulate limit order fills based on H/L prices of subsequent bars.
            # For now, just acknowledge it.
            current_kline_ts = self.historical_data.iloc[self._current_kline_index].name # type: ignore
            response = {
                'symbol': symbol, 'orderId': f"sim_{int(time.time_ns())}", 'clientOrderId': client_oid,
                'status': 'NEW', 'type': ord_type, 'side': side, 'price': str(price), 'origQty': str(quantity),
                'transactTime': int(current_kline_ts.timestamp() * 1000), # type: ignore
                # ... other typical fields for a NEW order
            }
            if self.strategy_instance:
                await self.strategy_instance.on_order_update({'e': 'ORDER_TRADE_UPDATE', 'o': response})
            return response

    async def cancel_existing_order(self, symbol: str, orderId: Optional[str] = None,  # orderId can be string from sim
                                    origClientOrderId: Optional[str] = None, **kwargs) -> Optional[Dict]:
        log_id = orderId or origClientOrderId
        self.logger.info(f"[Backtest] Cancel Order Req: ID={log_id} for {symbol}")
        # In a more complex backtester, we'd check a list of pending (simulated) limit orders.
        # Here, we just simulate a successful cancellation acknowledgement.
        current_kline_ts = self.historical_data.iloc[self._current_kline_index].name # type: ignore
        response = {'symbol': symbol, 'orderId': orderId, 'origClientOrderId': origClientOrderId, 'clientOrderId': origClientOrderId,
                    'status': 'CANCELED', 'type': kwargs.get('type', 'LIMIT'), # Guess type if not provided
                    'side': kwargs.get('side', 'UNKNOWN'),
                    'transactTime': int(current_kline_ts.timestamp() * 1000)} # type: ignore
        if self.strategy_instance:
            await self.strategy_instance.on_order_update({'e': 'ORDER_TRADE_UPDATE', 'o': response})
        return response


if __name__ == '__main__':
    # ... (main test block from previous step, ensure DummyBacktestStrategy is defined or imported) ...
    # Note: The DummyBacktestStrategy needs to be adapted to use the new async RiskManager methods
    # and the more detailed kline_data and order_update formats.
    # For this step, the focus is on BacktestEngine structure.
    # The __main__ block from previous step can be used as a template but might need adjustments
    # to reflect that RiskManager is now internal to BacktestEngine and strategies get it via constructor.
    pass # Keeping __main__ simple for now, focus on class implementation.

```
