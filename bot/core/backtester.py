import pandas as pd
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Type, Any, Callable # Added Callable
import asyncio # Added asyncio

# Assuming these are accessible, adjust paths if necessary
try:
    from bot.core.data_fetcher import MarketDataProvider
    from bot.strategies.base_strategy import BaseStrategy
    # OrderManager is not directly used as a dependency by BacktestEngine,
    # but BacktestEngine implements a compatible interface for the strategy.
except ImportError:
    # Fallbacks for local testing or if structure is slightly different
    from data_fetcher import MarketDataProvider
    # Need to ensure strategies.base_strategy is findable if running this file directly
    import sys
    sys.path.append('../strategies') # Assuming strategies is one level up from core if running from core
    from base_strategy import BaseStrategy


class BacktestEngine:
    def __init__(self,
                 market_data_provider: MarketDataProvider,
                 strategy_class: Type[BaseStrategy],
                 strategy_params: Dict[str, Any],
                 start_date_str: str,
                 end_date_str: str,
                 initial_capital: float,
                 symbol: str,
                 timeframe: str,
                 commission_rate: float = 0.0004): # 0.04%

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
        self.equity_curve: List[Dict[str, Any]] = []

        self.current_balance = initial_capital
        # Position: {'side': 'LONG'/'SHORT', 'entry_price': float, 'quantity': float, 'entry_timestamp': datetime, 'value': float}
        self.current_position: Optional[Dict[str, Any]] = None

        self.strategy_instance: Optional[BaseStrategy] = None
        self._current_kline_index = 0 # To help strategy get current price if needed

    def _generate_client_order_id(self, strategy_id: str = "backtest") -> str:
        prefix = strategy_id.replace("_", "")[:10]
        timestamp_ms = int(time.time() * 1000 * 1000) # Microseconds for more uniqueness
        return f"{prefix}bt{timestamp_ms}"[:36]

    async def _prepare_data(self) -> bool:
        self.logger.info(f"Preparing historical data for {self.symbol} ({self.timeframe}) from {self.start_date_str} to {self.end_date_str}")
        try:
            # Fetch a bit more data before start_date if strategy needs warmup, then slice if necessary
            # For now, fetching exact range. Limit is large to get all data in range.
            self.historical_data = await asyncio.to_thread(
                self.market_data_provider.get_historical_klines,
                symbol=self.symbol,
                interval=self.timeframe,
                start_str=self.start_date_str,
                end_str=self.end_date_str,
                limit=999999 # Effectively get all data in the range
            )
            if self.historical_data is None or self.historical_data.empty:
                self.logger.error("Failed to fetch historical data or no data available for the period.")
                return False

            # Ensure data is sorted by timestamp
            self.historical_data.sort_index(inplace=True)
            self.logger.info(f"Successfully loaded {len(self.historical_data)} klines.")
            return True
        except Exception as e:
            self.logger.error(f"Error during historical data preparation: {e}", exc_info=True)
            return False

    def _simulate_market_order(self, side: str, quantity_asset: float, execution_price: float, execution_timestamp: datetime):
        commission = quantity_asset * execution_price * self.commission_rate
        self.current_balance -= commission

        trade_value = quantity_asset * execution_price
        pnl = 0

        if self.current_position: # Existing position
            if self.current_position['side'] == side: # Increasing position size
                current_value = self.current_position['quantity'] * self.current_position['entry_price']
                new_total_quantity = self.current_position['quantity'] + quantity_asset
                new_total_value = current_value + trade_value
                self.current_position['entry_price'] = new_total_value / new_total_quantity
                self.current_position['quantity'] = new_total_quantity
                self.current_position['value'] = new_total_value # or keep track of margin used
            else: # Reducing or closing position
                if quantity_asset >= self.current_position['quantity']: # Closing position or more
                    closed_quantity = self.current_position['quantity']
                    if side == "SELL": # Closing a LONG
                        pnl = (execution_price - self.current_position['entry_price']) * closed_quantity
                    else: # Closing a SHORT
                        pnl = (self.current_position['entry_price'] - execution_price) * closed_quantity

                    self.current_balance += pnl
                    self.current_position = None # Position closed
                    if quantity_asset > closed_quantity: # Flipped position
                        remaining_qty = quantity_asset - closed_quantity
                        self.current_position = {
                            'side': side,
                            'entry_price': execution_price,
                            'quantity': remaining_qty,
                            'entry_timestamp': execution_timestamp,
                            'value': remaining_qty * execution_price
                        }
                else: # Reducing position size
                    closed_quantity = quantity_asset
                    if side == "SELL": # Reducing a LONG
                        pnl = (execution_price - self.current_position['entry_price']) * closed_quantity
                    else: # Reducing a SHORT
                        pnl = (self.current_position['entry_price'] - execution_price) * closed_quantity
                    self.current_balance += pnl
                    self.current_position['quantity'] -= closed_quantity
                    # Entry price of remaining position does not change
        else: # Opening new position
            self.current_position = {
                'side': side,
                'entry_price': execution_price,
                'quantity': quantity_asset,
                'entry_timestamp': execution_timestamp,
                'value': trade_value
            }

        trade_record = {
            'timestamp': execution_timestamp,
            'symbol': self.symbol,
            'type': 'MARKET',
            'side': side,
            'price': execution_price,
            'quantity': quantity_asset,
            'commission': commission,
            'pnl': pnl, # PnL from this trade if it closed/reduced a position
            'balance': self.current_balance
        }
        self.simulated_trades.append(trade_record)
        self.logger.info(f"SIM TRADE: {side} {quantity_asset} {self.symbol} @ {execution_price:.2f}, Comm: {commission:.4f}, PnL: {pnl:.2f}, Bal: {self.current_balance:.2f}")
        return trade_record


    async def run_backtest(self):
        self.logger.info(f"Starting backtest for {self.symbol} from {self.start_date_str} to {self.end_date_str}")
        if not await self._prepare_data() or self.historical_data is None:
            self.logger.error("Backtest preparation failed. Aborting.")
            return

        # The backtester itself acts as the order manager for the strategy during backtesting
        self.strategy_instance = self.strategy_class(
            strategy_id=f"backtest_{self.strategy_class.__name__}_{self.symbol}",
            params=self.strategy_params,
            order_manager=self, # Pass self (BacktestEngine) as the order_manager
            market_data_provider=self.market_data_provider, # MDP might be used by strategy for other symbols or context
            logger=self.logger
        )

        # Strategies in backtest mode should not try to make live subscriptions.
        # The BaseStrategy or individual strategies might need a 'backtest_mode' flag or check.
        if hasattr(self.strategy_instance, 'set_backtest_mode'):
             self.strategy_instance.set_backtest_mode(True)

        await self.strategy_instance.start() # Initialize strategy state

        self.equity_curve.append({'timestamp': self.historical_data.index[0] - pd.Timedelta(seconds=1), 'balance': self.initial_capital}) # Initial equity point

        for kline_row in self.historical_data.itertuples():
            self._current_kline_index = self.historical_data.index.get_loc(kline_row.Index)
            current_timestamp = kline_row.Index # This is already a pandas Timestamp (datetime like)

            # Prepare kline_data in the format strategy expects (similar to WebSocket kline event)
            kline_data_for_strategy = {
                'e': 'kline',           # Event type
                'E': int(current_timestamp.timestamp() * 1000 + self._KLINE_INTERVAL_MILLISECONDS[self.timeframe] -1), # Event time (approx kline close)
                's': self.symbol,
                'k': {
                    't': int(current_timestamp.timestamp() * 1000),              # Kline start time
                    'T': int(current_timestamp.timestamp() * 1000 + self._KLINE_INTERVAL_MILLISECONDS[self.timeframe] -1), # Kline close time
                    's': self.symbol,
                    'i': self.timeframe,
                    'o': kline_row.open,
                    'h': kline_row.high,
                    'l': kline_row.low,
                    'c': kline_row.close,
                    'v': kline_row.volume,
                    'n': kline_row.number_of_trades if 'number_of_trades' in kline_row._fields else 0, # Field name from df
                    'x': True, # Kline is closed
                    'q': kline_row.quote_asset_volume if 'quote_asset_volume' in kline_row._fields else 0.0,
                    'V': kline_row.taker_buy_base_asset_volume if 'taker_buy_base_asset_volume' in kline_row._fields else 0.0,
                    'Q': kline_row.taker_buy_quote_asset_volume if 'taker_buy_quote_asset_volume' in kline_row._fields else 0.0,
                    'B': "0" # Ignore
                }
            }
            # Pass the 'k' dict as kline_data to on_kline_update, as per BaseStrategy hint
            await self.strategy_instance.on_kline_update(self.symbol, self.timeframe, kline_data_for_strategy['k'])

            # Record equity at the end of each bar (after strategy processing and potential trades)
            self.equity_curve.append({'timestamp': current_timestamp, 'balance': self.current_balance})

        await self.strategy_instance.stop()
        self._calculate_and_log_performance_metrics()
        self.logger.info("Backtest finished.")
        return self.simulated_trades, self.equity_curve


    def _calculate_and_log_performance_metrics(self):
        if not self.simulated_trades:
            self.logger.info("No trades were executed during the backtest.")
            return

        total_pnl = self.current_balance - self.initial_capital
        percent_return = (total_pnl / self.initial_capital) * 100
        num_trades = len(self.simulated_trades)

        winning_trades = sum(1 for trade in self.simulated_trades if trade['pnl'] > 0)
        losing_trades = sum(1 for trade in self.simulated_trades if trade['pnl'] < 0)
        win_rate = (winning_trades / num_trades) * 100 if num_trades > 0 else 0

        self.logger.info("--- Backtest Performance Metrics ---")
        self.logger.info(f"Initial Capital: {self.initial_capital:.2f}")
        self.logger.info(f"Final Balance:   {self.current_balance:.2f}")
        self.logger.info(f"Total P&L:       {total_pnl:.2f}")
        self.logger.info(f"Percent Return:  {percent_return:.2f}%")
        self.logger.info(f"Number of Trades:{num_trades}")
        self.logger.info(f"Winning Trades:  {winning_trades}")
        self.logger.info(f"Losing Trades:   {losing_trades}")
        self.logger.info(f"Win Rate:        {win_rate:.2f}%")
        # TODO: Max Drawdown, Sharpe Ratio, etc.

    # --- Mock OrderManager Interface for Strategy ---
    async def place_new_order(self, symbol: str, side: str, ord_type: str, quantity: float,
                              price: Optional[float] = None, timeInForce: Optional[str] = None,
                              reduceOnly: Optional[bool] = None, newClientOrderId: Optional[str] = None,
                              stopPrice: Optional[float] = None, positionSide: Optional[str] = None, **kwargs) -> Optional[Dict]:

        current_kline_data = self.historical_data.iloc[self._current_kline_index]
        execution_timestamp = current_kline_data.name # This is the kline open time (Pandas Timestamp)

        # For backtesting, MARKET orders are filled at the close of the current bar.
        # LIMIT orders would require more complex logic (checking if price hits in next bar, etc.)
        if ord_type.upper() == "MARKET":
            execution_price = current_kline_data['close']
            self.logger.info(f"[Backtest] Simulating MARKET {side} order for {quantity} {symbol} at {execution_price} (Close of current bar)")

            simulated_fill_details = self._simulate_market_order(side, quantity, execution_price, execution_timestamp)

            # Simulate Binance API response for a filled market order
            response = {
                'symbol': symbol,
                'orderId': int(time.time() * 1000000), # Mock order ID
                'clientOrderId': newClientOrderId or self._generate_client_order_id(),
                'transactTime': int(execution_timestamp.timestamp() * 1000),
                'price': '0', # Market orders have price 0
                'origQty': str(quantity),
                'executedQty': str(quantity),
                'cumQuote': str(simulated_fill_details['price'] * quantity), # Filled value
                'status': 'FILLED',
                'timeInForce': timeInForce or 'GTC', # Market orders are usually GTC or IOC/FOK
                'type': 'MARKET',
                'side': side,
                'avgPrice': str(simulated_fill_details['price']),
                'positionSide': positionSide or self.current_position.get('side') if self.current_position else 'BOTH',
                # Include other fields as strategy might expect them from on_order_update
            }
            # Simulate calling strategy's on_order_update
            if self.strategy_instance:
                # Structure for ORDER_TRADE_UPDATE event
                order_update_event = {'e': 'ORDER_TRADE_UPDATE', 'T': response['transactTime'], 'E': response['transactTime'], 'o': response}
                await self.strategy_instance.on_order_update(order_update_event['o'])
            return response
        else:
            self.logger.warning(f"[Backtest] Order type '{ord_type}' not fully simulated. Only MARKET orders are processed for fill.")
            # Return a PENDING_NEW like status or None
            return {
                'symbol': symbol, 'orderId': int(time.time() * 1000000), 'clientOrderId': newClientOrderId or self._generate_client_order_id(),
                'status': 'NEW', 'type': ord_type, 'side': side, 'price': str(price), 'origQty': str(quantity),
                # ... other typical fields for a NEW order
            }

    async def cancel_existing_order(self, symbol: str, orderId: Optional[int] = None,
                                    origClientOrderId: Optional[str] = None, **kwargs) -> Optional[Dict]:
        log_id = orderId if orderId else origClientOrderId
        self.logger.info(f"[Backtest] Strategy requests to cancel order: ID={log_id} for {symbol}")
        # In this simplified backtester, non-MARKET orders aren't really "active" to be cancelled.
        # If we were simulating limit orders, we'd check a list of pending simulated orders.
        # For now, assume cancellation is successful if the order was (theoretically) placed.
        return {
            'symbol': symbol, 'orderId': orderId, 'clientOrderId': origClientOrderId,
            'status': 'CANCELED', # Simulate successful cancellation
            # ... other fields
        }

# Example Dummy Strategy for testing BacktestEngine
class DummyBacktestStrategy(BaseStrategy):
    async def start(self):
        await super().start() # Important for base class logging
        self.logger.info(f"{self.strategy_id} started with params: {self.params}")
        # In a real strategy, you might initialize indicators or subscribe to data (not for backtest)
        self.long_ma_period = self.get_param('long_ma_period', 20)
        self.short_ma_period = self.get_param('short_ma_period', 5)
        self.trade_quantity = self.get_param('trade_quantity', 0.001)
        self.klines_buffer = pd.DataFrame()


    async def on_kline_update(self, symbol: str, interval: str, kline_data: Dict):
        # self.logger.debug(f"{self.strategy_id} kline: {kline_data['c']}")
        # Append new kline to buffer
        new_kline = pd.Series({
            'open': float(kline_data['o']),
            'high': float(kline_data['h']),
            'low': float(kline_data['l']),
            'close': float(kline_data['c']),
            'volume': float(kline_data['v'])
        }, name=pd.to_datetime(kline_data['t'], unit='ms', utc=True))

        # self.klines_buffer = self.klines_buffer.append(new_kline) # .append is deprecated
        self.klines_buffer = pd.concat([self.klines_buffer, new_kline.to_frame().T])


        if len(self.klines_buffer) > self.long_ma_period:
            self.klines_buffer['short_ma'] = self.klines_buffer['close'].rolling(window=self.short_ma_period).mean()
            self.klines_buffer['long_ma'] = self.klines_buffer['close'].rolling(window=self.long_ma_period).mean()

            if len(self.klines_buffer) < 2: return # Need at least 2 points to check crossover

            # MA Crossover Logic
            # short_ma_prev = self.klines_buffer['short_ma'].iloc[-2]
            # long_ma_prev = self.klines_buffer['long_ma'].iloc[-2]
            # short_ma_curr = self.klines_buffer['short_ma'].iloc[-1]
            # long_ma_curr = self.klines_buffer['long_ma'].iloc[-1]

            # Simplified: access last two values if available
            if len(self.klines_buffer) < self.long_ma_period + 1: return

            short_ma_prev, short_ma_curr = self.klines_buffer['short_ma'].iloc[-2:]
            long_ma_prev, long_ma_curr = self.klines_buffer['long_ma'].iloc[-2:]


            # Access current position from BacktestEngine (which is self.order_manager here)
            current_position_side = self.order_manager.current_position['side'] if self.order_manager.current_position else None

            if short_ma_curr > long_ma_curr and short_ma_prev <= long_ma_prev: # Bullish crossover
                if current_position_side != 'LONG':
                    if current_position_side == 'SHORT': # Close short first
                        await self.order_manager.place_new_order(symbol, "BUY", "MARKET", self.order_manager.current_position['quantity'], strategy_id=self.strategy_id)
                    await self.order_manager.place_new_order(symbol, "BUY", "MARKET", self.trade_quantity, strategy_id=self.strategy_id)
                    self.logger.info(f"{self.strategy_id}: Bullish crossover. Placed BUY order.")
            elif short_ma_curr < long_ma_curr and short_ma_prev >= long_ma_prev: # Bearish crossover
                if current_position_side != 'SHORT':
                    if current_position_side == 'LONG': # Close long first
                         await self.order_manager.place_new_order(symbol, "SELL", "MARKET", self.order_manager.current_position['quantity'], strategy_id=self.strategy_id)
                    await self.order_manager.place_new_order(symbol, "SELL", "MARKET", self.trade_quantity, strategy_id=self.strategy_id)
                    self.logger.info(f"{self.strategy_id}: Bearish crossover. Placed SELL order.")

    async def on_depth_update(self, symbol: str, depth_data: Dict): pass
    async def on_trade_update(self, symbol: str, trade_data: Dict): pass
    async def on_mark_price_update(self, symbol: str, mark_price_data: Dict): pass
    async def on_order_update(self, order_update: Dict):
        self.logger.info(f"{self.strategy_id} received order update in strategy: ClientOrderID: {order_update.get('c')}, Status: {order_update.get('X')}")
    async def stop(self):
        await super().stop()


if __name__ == '__main__':
    import os
    from dotenv import load_dotenv
    try:
        from bot.core.logger_setup import setup_logger
        from bot.connectors.binance_connector import BinanceAPI # For MDP
    except ImportError:
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        logger = logging.getLogger('algo_trader_bot_test_backtester')


    dotenv_path = os.path.join(os.path.dirname(__file__), '../../.env') # Adjust if .env is elsewhere
    load_dotenv(dotenv_path=dotenv_path)

    logger = logging.getLogger('algo_trader_bot')
    if not logger.handlers:
        log_level_str = os.getenv('LOG_LEVEL', 'INFO').upper()
        log_level_int = getattr(logging, log_level_str, logging.INFO)
        try: setup_logger(level=log_level_int, log_file="backtester_test.log")
        except NameError: logging.basicConfig(level=log_level_int)


    API_KEY_TEST = os.getenv("BINANCE_TESTNET_API_KEY")
    API_SECRET_TEST = os.getenv("BINANCE_TESTNET_API_SECRET")

    if not API_KEY_TEST or API_KEY_TEST == "YOUR_TESTNET_API_KEY":
        logger.error("Testnet API keys not found in .env. Backtester test for data fetching might fail.")
        # For backtesting that only needs historical data, API keys might not be strictly needed
        # if get_historical_klines doesn't enforce signed requests for public data.
        # However, BinanceAPI class requires it for header setup.
        # We can proceed if MDP can fetch data without full auth.
        mock_connector = None # Or a BinanceAPI instance with no keys if it allows public calls
    else:
        mock_connector = BinanceAPI(api_key=API_KEY_TEST, api_secret=API_SECRET_TEST, testnet=True)


    async def run_test():
        if not mock_connector:
            logger.warning("Mock connector not available, full backtest might not run if data fetching needs auth.")
            # Create a dummy connector if real one fails, to test logic flow
            class DummyConnector:
                def get_klines(self, **kwargs): return [] # Returns empty list
            mdp = MarketDataProvider(binance_connector=DummyConnector()) # type: ignore
        else:
            mdp = MarketDataProvider(binance_connector=mock_connector)

        strategy_params = {'long_ma_period': 10, 'short_ma_period': 3, 'trade_quantity': 0.002} # Shorter MAs for more trades

        backtester = BacktestEngine(
            market_data_provider=mdp,
            strategy_class=DummyBacktestStrategy,
            strategy_params=strategy_params,
            start_date_str="2023-12-01", # Use a short recent period for testing
            end_date_str="2023-12-05",
            initial_capital=1000.0,
            symbol="BTCUSDT",
            timeframe="1h" # Use 1h to have fewer data points for quick test
        )

        await backtester.run_backtest()

        logger.info("\n--- Simulated Trades ---")
        for trade in backtester.simulated_trades:
            logger.info(trade)

        # logger.info("\n--- Equity Curve ---")
        # for point in backtester.equity_curve:
        #     logger.info(point)

    if mock_connector or True: # Allow running even if real connector init failed, with DummyConnector
        asyncio.run(run_test())
    else:
        logger.error("Cannot run backtest example without API keys for MarketDataProvider.")

```
