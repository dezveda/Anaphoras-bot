import pandas as pd
from datetime import datetime, timedelta, timezone
import time
from typing import List, Dict, Optional, Callable, Tuple, Any
from collections import defaultdict
import logging

try:
    from bot.connectors.binance_connector import BinanceAPI
except ImportError:
    from connectors.binance_connector import BinanceAPI # Fallback for local testing


class MarketDataProvider:
    _KLINE_INTERVAL_MILLISECONDS = {
        "1m": 60000, "3m": 180000, "5m": 300000, "15m": 900000, "30m": 1800000,
        "1h": 3600000, "2h": 7200000, "4h": 14400000, "6h": 21600000, "8h": 28800000,
        "12h": 43200000, "1d": 86400000, "3d": 259200000, "1w": 604800000, "1M": 2592000000 # Approx for 1M
    }
    _BINANCE_KLINES_COLUMNS = [
        'timestamp', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_asset_volume', 'number_of_trades',
        'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
    ]
    _MAX_KLINE_LIMIT_PER_REQUEST = 1500

    def __init__(self, binance_connector: BinanceAPI): # Removed order_update_callback from __init__
        self.binance_connector = binance_connector
        self.logger = logging.getLogger('algo_trader_bot')
        self.historical_klines_cache: Dict[str, pd.DataFrame] = {}

        self.active_streams: Dict[str, Dict[str, Any]] = {}
        self.stream_callbacks: Dict[str, List[Callable]] = defaultdict(list)

        # List to hold all registered general user data callbacks
        self.user_data_callbacks: List[Callable] = []


    def _parse_date_to_milliseconds(self, date_str: Optional[str]) -> Optional[int]:
        if date_str is None:
            return None
        try:
            dt_obj = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            dt_obj = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return int(dt_obj.timestamp() * 1000)

    def get_historical_klines(self, symbol: str, interval: str,
                               start_str: Optional[str] = None,
                               end_str: Optional[str] = None,
                               limit: int = 1000) -> pd.DataFrame:
        if interval not in self._KLINE_INTERVAL_MILLISECONDS:
            self.logger.error(f"Unsupported kline interval: {interval}")
            raise ValueError(f"Unsupported kline interval: {interval}")

        start_ms = self._parse_date_to_milliseconds(start_str)
        end_ms = self._parse_date_to_milliseconds(end_str)
        all_klines_data = []

        self.logger.info(f"Fetching historical klines for {symbol} ({interval}). Range: {start_str} to {end_str}. Limit: {limit}")

        current_start_time_ms = start_ms
        klines_fetched_count = 0

        while klines_fetched_count < limit:
            remaining_limit = limit - klines_fetched_count
            batch_limit = min(remaining_limit, self._MAX_KLINE_LIMIT_PER_REQUEST)
            if batch_limit <= 0:
                break

            actual_end_ms = end_ms
            if current_start_time_ms is not None and end_ms is not None:
                max_possible_end_for_batch = current_start_time_ms + (batch_limit -1) * self._KLINE_INTERVAL_MILLISECONDS[interval]
                actual_end_ms = min(end_ms, max_possible_end_for_batch)

            self.logger.debug(f"Fetching chunk: Symbol={symbol}, Interval={interval}, Start={current_start_time_ms}, End={actual_end_ms}, Limit={batch_limit}")

            try:
                klines_chunk = self.binance_connector.get_klines(
                    symbol=symbol,
                    interval=interval,
                    startTime=current_start_time_ms,
                    endTime=actual_end_ms,
                    limit=batch_limit
                )
            except Exception as e:
                self.logger.error(f"Error fetching klines chunk for {symbol}: {e}", exc_info=True)
                break

            if not klines_chunk:
                self.logger.debug("No more klines returned from API for the current request.")
                break

            all_klines_data.extend(klines_chunk)
            klines_fetched_count = len(all_klines_data)

            if current_start_time_ms is not None:
                last_kline_open_time = int(klines_chunk[-1][0])
                current_start_time_ms = last_kline_open_time + self._KLINE_INTERVAL_MILLISECONDS[interval]
                if end_ms is not None and current_start_time_ms > end_ms:
                    break
            else:
                break

            if len(klines_chunk) < batch_limit:
                break

            time.sleep(0.2)

        if not all_klines_data:
            return pd.DataFrame(columns=self._BINANCE_KLINES_COLUMNS).set_index('timestamp')

        df = pd.DataFrame(all_klines_data, columns=self._BINANCE_KLINES_COLUMNS)
        df.drop_duplicates(subset=['timestamp'], keep='first', inplace=True)

        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
        df['close_time'] = pd.to_datetime(df['close_time'], unit='ms', utc=True)
        numeric_cols = ['open', 'high', 'low', 'close', 'volume', 'quote_asset_volume', 'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume']
        for col in numeric_cols: df[col] = pd.to_numeric(df[col])
        df['number_of_trades'] = pd.to_numeric(df['number_of_trades'], errors='coerce').astype('Int64')
        df.set_index('timestamp', inplace=True)
        df.sort_index(inplace=True)

        if start_str: df = df[df.index >= pd.Timestamp(start_str, tz='UTC')]
        if end_str: df = df[df.index <= pd.Timestamp(end_str, tz='UTC')]

        return df.head(limit)


    def dispatch_data_update(self, event_type: str, data: Any):
        self.logger.debug(f"Dispatching data for event: {event_type}, {len(self.stream_callbacks.get(event_type, []))} callbacks registered.")
        for callback in self.stream_callbacks.get(event_type, []):
            try: callback(data)
            except Exception as e: self.logger.error(f"Error in market data callback for event {event_type}: {e}", exc_info=True)

    def _handle_market_message(self, stream_name: str, data: dict):
        self.logger.debug(f"Received market message for stream '{stream_name}': {str(data)[:200]}")

        parsed_data = data.get('data', data)
        actual_stream_name = data.get('stream', stream_name)

        parts = actual_stream_name.split('@')
        symbol_lower = parts[0].lower()
        event_suffix = parts[1] if len(parts) > 1 else "unknown"

        if event_suffix.startswith("kline_"):
            interval = event_suffix.split('_')[1]
            self._process_kline_data(symbol_lower, interval, parsed_data)
        elif event_suffix.startswith("depth"):
            self._process_depth_data(symbol_lower, parsed_data)
        elif event_suffix == "aggTrade":
            self._process_trade_data(symbol_lower, parsed_data)
        elif event_suffix.startswith("markPrice"):
            self._process_mark_price_data(symbol_lower, parsed_data)
        else:
            self.logger.warning(f"Unknown market data event suffix '{event_suffix}' from stream '{actual_stream_name}'")
            self.dispatch_data_update(f"{symbol_lower}_{event_suffix}", parsed_data)

    def _process_kline_data(self, symbol: str, interval: str, kline_event_data: dict):
        k_data = kline_event_data.get('k')
        if not k_data: self.logger.warning(f"Malformed kline data for {symbol}_{interval}: {kline_event_data}"); return
        self.logger.info(f"KLINE [{symbol}-{interval}]: T:{k_data.get('t')} O:{k_data.get('o')} C:{k_data.get('c')} Closed:{k_data.get('x')}")
        self.dispatch_data_update(f"{symbol}_kline_{interval}", k_data)

    def _process_depth_data(self, symbol: str, depth_event_data: dict):
        self.logger.info(f"DEPTH [{symbol}]: EventTime: {depth_event_data.get('E')}, Bids: {len(depth_event_data.get('b',[]))}, Asks: {len(depth_event_data.get('a',[]))}")
        self.dispatch_data_update(f"{symbol}_depth", depth_event_data)

    def _process_trade_data(self, symbol: str, trade_event_data: dict):
        self.logger.info(f"TRADE [{symbol}]: Price: {trade_event_data.get('p')}, Qty: {trade_event_data.get('q')}")
        self.dispatch_data_update(f"{symbol}_trade", trade_event_data)

    def _process_mark_price_data(self, symbol: str, mark_price_event_data: dict):
        self.logger.info(f"MARK_PRICE [{symbol}]: {mark_price_event_data.get('p')}")
        self.dispatch_data_update(f"{symbol}_mark_price", mark_price_event_data)

    def _create_stream_handler_wrapper(self, stream_name_key: str) -> Callable:
        def handler(data: dict): self._handle_market_message(stream_name_key, data)
        return handler

    def _subscribe_generic_market_stream(self, symbol: str, stream_suffix: str, event_type_suffix: str, callback: Optional[Callable]) -> Optional[str]:
        symbol_lower = symbol.lower()
        stream_name = f"{symbol_lower}@{stream_suffix}"
        event_type = f"{symbol_lower}_{event_type_suffix}"

        stream_id = self.binance_connector.start_market_stream([stream_name], callback=self._create_stream_handler_wrapper(stream_name))
        if stream_id:
            self.active_streams[stream_id] = {'name': stream_name, 'type': event_type_suffix}
            if callback: self.stream_callbacks[event_type].append(callback)
            self.logger.info(f"Subscribed to {event_type_suffix} stream: {stream_name} (ID: {stream_id}). Callback {'set' if callback else 'not set'}.")
            return stream_id
        self.logger.error(f"Failed to subscribe to {stream_name}")
        return None

    def subscribe_to_kline_stream(self, symbol: str, interval: str, callback: Optional[Callable] = None) -> Optional[str]:
        return self._subscribe_generic_market_stream(symbol, f"kline_{interval}", f"kline_{interval}", callback)

    def subscribe_to_depth_stream(self, symbol: str, callback: Optional[Callable] = None, levels: int = 5, update_speed: str = "100ms") -> Optional[str]:
        return self._subscribe_generic_market_stream(symbol, f"depth{levels}@{update_speed}", "depth", callback)

    def subscribe_to_trade_stream(self, symbol: str, callback: Optional[Callable] = None) -> Optional[str]:
        return self._subscribe_generic_market_stream(symbol, "aggTrade", "trade", callback)

    def subscribe_to_mark_price_stream(self, symbol: str, callback: Optional[Callable] = None, update_speed: str = "1s") -> Optional[str]:
        return self._subscribe_generic_market_stream(symbol, f"markPrice@{update_speed}", "mark_price", callback)

    def _handle_user_data_message(self, data: dict):
        """
        Internal callback for BinanceConnector's user data stream.
        This method dispatches the raw user data message to all registered generic user data callbacks.
        """
        event_type = data.get('e')
        self.logger.debug(f"User Data Received by MDP - Event: {event_type}, Data: {str(data)[:300]}")

        for cb in self.user_data_callbacks:
            try:
                cb(data) # Pass the raw data dictionary
            except Exception as e:
                self.logger.error(f"Error in a generic user data callback for event {event_type}: {e}", exc_info=True)

    def subscribe_to_user_data(self, user_data_event_callback: Callable) -> bool:
        """
        Subscribes to the user data stream and registers a callback for all user data events.
        Multiple callbacks can be registered by calling this method multiple times.
        Args:
            user_data_event_callback: The function to call with each raw user data event.
        """
        if user_data_event_callback and user_data_event_callback not in self.user_data_callbacks:
            self.user_data_callbacks.append(user_data_event_callback)
            self.logger.info(f"Registered user data callback: {user_data_event_callback.__name__}")

        if not self.binance_connector.user_data_control_flag.get('keep_running', False):
            self.logger.info("User data stream not running. Attempting to start via BinanceConnector.")
            # The _handle_user_data_message method of this class will be passed to the connector
            success = self.binance_connector.start_user_stream(self._handle_user_data_message)
            if success:
                self.logger.info("Successfully started user data stream via BinanceConnector.")
            else:
                self.logger.error("Failed to start user data stream via BinanceConnector.")
                if user_data_event_callback in self.user_data_callbacks: # Clean up if start failed
                    self.user_data_callbacks.remove(user_data_event_callback)
                return False
            return success
        else:
            self.logger.info("User data stream already running. New callback registered if provided.")
            return True

    def unsubscribe_all_streams(self):
        self.logger.info("Unsubscribing all market data streams...")
        for stream_id in list(self.active_streams.keys()):
            self.binance_connector.stop_market_stream(stream_id)
        self.active_streams.clear()
        self.stream_callbacks.clear()
        self.logger.info("All market data streams stopped and cleared.")

        if self.binance_connector.user_data_control_flag.get('keep_running', False):
            self.logger.info("Stopping user data stream...")
            self.binance_connector.stop_user_stream()
        self.user_data_callbacks.clear() # Clear all registered user data callbacks
        self.logger.info("User data stream stopped and all user data callbacks cleared.")


if __name__ == '__main__':
    import os
    from dotenv import load_dotenv
    try:
        from bot.core.logger_setup import setup_logger
    except ImportError:
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        logger = logging.getLogger('algo_trader_bot_test')

    dotenv_path_for_log = os.path.join(os.path.dirname(__file__), '../../.env')
    load_dotenv(dotenv_path=dotenv_path_for_log)

    logger = logging.getLogger('algo_trader_bot')
    if not logger.hasHandlers():
        log_level_str = os.getenv('LOG_LEVEL', 'DEBUG').upper() # Default to DEBUG for testing data_fetcher
        log_level_int = getattr(logging, log_level_str, logging.DEBUG)
        # Basic setup if main app didn't set it up. For testing, use setup_logger if available.
        try:
            setup_logger(level=log_level_int, log_file="data_fetcher_test.log")
        except NameError: # setup_logger not imported
             logging.basicConfig(level=log_level_int, format='%(asctime)s - %(name)s - %(levelname)s - %(module)s - %(funcName)s - %(message)s')


    API_KEY = os.getenv("BINANCE_TESTNET_API_KEY")
    API_SECRET = os.getenv("BINANCE_TESTNET_API_SECRET")
    USE_TESTNET = True

    if not API_KEY or API_KEY == "YOUR_TESTNET_API_KEY" or not API_SECRET:
        logger.error("Please set your BINANCE_TESTNET_API_KEY and API_SECRET in the .env file in the project root.")
    else:
        connector = BinanceAPI(api_key=API_KEY, api_secret=API_SECRET, testnet=USE_TESTNET)

        # MarketDataProvider now does not take order_update_callback in __init__ directly
        data_fetcher = MarketDataProvider(binance_connector=connector)

        def my_kline_callback(data):logger.info(f"MY KLINE CB: Symbol={data.get('s')}, C={data.get('c')}, T={data.get('T')}")
        def my_trade_callback(data):logger.info(f"MY TRADE CB: Symbol={data.get('s')}, P={data.get('p')}")

        # This will be a generic user data callback that receives ALL user data events
        def generic_user_data_handler_for_test(data):
            logger.info(f"GENERIC USER DATA HANDLER: Event={data.get('e')}, Data={str(data)[:150]}")
            if data.get('e') == 'ORDER_TRADE_UPDATE':
                logger.info(f"  Specific Order Update within Generic Handler: {data.get('o', {}).get('c')} -> {data.get('o', {}).get('X')}")


        k_sid, t_sid = None, None
        try:
            logger.info("\nSubscribing to market and user streams...")
            k_sid = data_fetcher.subscribe_to_kline_stream("BTCUSDT", "1m", my_kline_callback)
            t_sid = data_fetcher.subscribe_to_trade_stream("ETHUSDT", my_trade_callback)

            # Register the generic handler for user data
            data_fetcher.subscribe_to_user_data(user_data_event_callback=generic_user_data_handler_for_test)
            # OrderManager would also call subscribe_to_user_data with its own handler.

            if k_sid or t_sid or data_fetcher.binance_connector.user_data_control_flag.get('keep_running'):
                logger.info("Streams subscribed. Running for 25 seconds...")
                time.sleep(25)
            else: logger.error("No streams were started.")
        except KeyboardInterrupt: logger.info("Test interrupted.")
        except Exception as e: logger.error(f"Error in test: {e}", exc_info=True)
        finally:
            logger.info("\nUnsubscribing all streams...")
            data_fetcher.unsubscribe_all_streams()
            logger.info("Test finished.")
            time.sleep(2)

```
