import pandas as pd
from datetime import datetime, timedelta, timezone
import time
from typing import List, Dict, Optional, Callable

# Assuming BinanceAPI is in bot.connectors.binance_connector
# Adjust import path if your structure is different
try:
    from bot.connectors.binance_connector import BinanceAPI
except ImportError:
    # Fallback for local testing if 'bot' module is not recognized in current path
    from connectors.binance_connector import BinanceAPI


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
    _MAX_KLINE_LIMIT_PER_REQUEST = 1500 # Binance API limit for klines

    def __init__(self, binance_connector: BinanceAPI):
        self.binance_connector = binance_connector
        self.historical_klines_cache: Dict[str, pd.DataFrame] = {} # Example cache

    def _parse_date_to_milliseconds(self, date_str: Optional[str]) -> Optional[int]:
        if date_str is None:
            return None
        try:
            # Assuming format like "YYYY-MM-DD HH:MM:SS" or "YYYY-MM-DD"
            # Add timezone awareness, assuming UTC if not specified
            dt_obj = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            dt_obj = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return int(dt_obj.timestamp() * 1000)

    def get_historical_klines(self, symbol: str, interval: str,
                               start_str: Optional[str] = None,
                               end_str: Optional[str] = None,
                               limit: int = 1000) -> pd.DataFrame:
        """
        Fetches historical klines from Binance, handling pagination.

        Args:
            symbol: Trading symbol (e.g., "BTCUSDT").
            interval: Kline interval (e.g., "1m", "1h", "1d").
            start_str: Start date string (e.g., "2023-01-01 00:00:00" or "2023-01-01"). UTC.
            end_str: End date string (e.g., "2023-01-31 23:59:59" or "2023-01-31"). UTC.
            limit: Total number of klines to fetch. Binance API per-request limit is 1500.

        Returns:
            A Pandas DataFrame with kline data, indexed by 'timestamp'.
        """
        if interval not in self._KLINE_INTERVAL_MILLISECONDS:
            raise ValueError(f"Unsupported kline interval: {interval}")

        start_ms = self._parse_date_to_milliseconds(start_str)
        end_ms = self._parse_date_to_milliseconds(end_str)

        all_klines_data = []

        # Determine the number of requests needed if start_ms and end_ms are provided
        # Otherwise, fetch up to 'limit' in manageable chunks

        current_limit = min(limit, self._MAX_KLINE_LIMIT_PER_REQUEST)
        last_timestamp_fetched = None

        if start_ms is None and limit > self._MAX_KLINE_LIMIT_PER_REQUEST:
             # If no start time, and large limit, we need to paginate backwards from current time
             # For simplicity, this initial implementation will fetch 'limit' candles ending now,
             # potentially in multiple requests if limit > MAX_KLINE_LIMIT_PER_REQUEST.
             # A more robust solution for very large 'limit' without start_str would require
             # multiple backward fetches, which complicates endTime logic.
             # For now, we'll fetch 'limit' candles ending at 'end_ms' or now.
             pass


        while True:
            fetch_start_time = start_ms
            fetch_end_time = end_ms

            # If paginating based on previous fetch to get more data
            if last_timestamp_fetched and start_ms:
                fetch_start_time = last_timestamp_fetched + self._KLINE_INTERVAL_MILLISECONDS[interval]

            # Adjust fetch_end_time if fetching in chunks towards a specific end_ms or limit
            if fetch_start_time and end_ms:
                # Calculate max possible end time for this chunk without exceeding end_ms
                max_chunk_end_time = fetch_start_time + (current_limit -1) * self._KLINE_INTERVAL_MILLISECONDS[interval]
                fetch_end_time = min(end_ms, max_chunk_end_time)
                if fetch_start_time > fetch_end_time and len(all_klines_data) > 0 : # ensure we don't loop if start > end
                    break


            klines_chunk = self.binance_connector.get_klines(
                symbol=symbol,
                interval=interval,
                startTime=fetch_start_time,
                endTime=fetch_end_time, # Only set endTime if a specific range is given
                limit=current_limit
            )

            if not klines_chunk:
                break

            all_klines_data.extend(klines_chunk)

            # Update last_timestamp_fetched for next iteration if start_ms was given
            if start_ms:
                last_timestamp_fetched = klines_chunk[-1][0] # Open time of the last kline

            # Check if we have fetched enough data based on the overall limit
            if len(all_klines_data) >= limit:
                all_klines_data = all_klines_data[:limit] # Trim to exact limit
                break

            # If end_ms is defined and we've reached or passed it
            if end_ms and last_timestamp_fetched and last_timestamp_fetched >= end_ms:
                break

            # If no start_ms was provided, we fetch only one batch (up to limit)
            # unless 'limit' itself is very large, requiring pagination backwards (more complex)
            if start_ms is None:
                if len(all_klines_data) >= limit: # handles limit <= MAX_KLINE_LIMIT_PER_REQUEST
                    break
                # If limit > MAX_KLINE_LIMIT_PER_REQUEST and no start_ms, complex backward pagination needed.
                # For now, this means we'd fetch one chunk and if limit > 1500, it's not fully handled here.
                # A robust solution would fetch backwards from current time.
                # For now, we assume if start_ms is None, limit is the primary driver for a single chunk.
                # Or, if limit is also large, subsequent chunks are not automatically fetched backwards.
                # This part needs more refinement for "fetch last N candles where N > 1500".
                # The current loop structure is better suited for date ranges or limits from a start_date.

                # Simplified: if no start_ms, fetch one batch. If more needed, user should specify start_ms.
                # Or, if 'limit' is the only guide and > 1500, we need to adjust.
                remaining_limit = limit - len(all_klines_data)
                if remaining_limit <=0:
                    break
                current_limit = min(remaining_limit, self._MAX_KLINE_LIMIT_PER_REQUEST)
                if not start_ms and not end_ms: # Fetching backwards from now
                    # To fetch backwards, set endTime to the open time of the first kline of the current batch
                    # and fetch another batch.
                    if len(all_klines_data) > 0:
                        end_ms_for_next_batch = all_klines_data[0][0] - self._KLINE_INTERVAL_MILLISECONDS[interval]
                        start_ms_for_next_batch = end_ms_for_next_batch - (current_limit -1) * self._KLINE_INTERVAL_MILLISECONDS[interval]
                        # This logic is getting complex and might be better handled by a dedicated "fetch_last_n_klines"
                        # For now, the loop primarily works well with start_str.
                        # If start_str is None, it fetches 'limit' candles ending 'now' or 'end_str'.
                        # If this limit > 1500, it fetches multiple times but always towards 'now' or 'end_str'.
                        # This is not true backward pagination from an unspecified point in the past.
                        # For now, we break if no start_ms, to avoid infinite loops with current logic.
                        # User must provide start_str for fetching more than 1500 historical candles correctly with this.
                        # A dedicated 'fetch_latest_n_klines(n)' would be better for that use case.
                        # For this version, if start_ms is None, we fetch one batch up to 'limit' or MAX_KLINE_LIMIT_PER_REQUEST.
                        if len(klines_chunk) < self._MAX_KLINE_LIMIT_PER_REQUEST : # if binance returns less than requested, means no more past data
                            break
                        # Re-evaluating the loop condition for "no start_str"
                        # If no start_str, the loop should fetch backwards from end_str (or now)
                        # The current 'last_timestamp_fetched' logic is for forward fetching
                        # This part will be simplified for now: if no start_str, fetch one chunk.
                        break # Simplified: for no start_str, one batch. User can use start_str for more.


            if len(klines_chunk) < self._MAX_KLINE_LIMIT_PER_REQUEST:
                # Binance returned fewer klines than requested, meaning no more data in that range
                break

            time.sleep(0.2) # Small delay to respect API rate limits if making many calls

        if not all_klines_data:
            return pd.DataFrame(columns=self._BINANCE_KLINES_COLUMNS).set_index('timestamp')

        df = pd.DataFrame(all_klines_data, columns=self._BINANCE_KLINES_COLUMNS)

        # Convert to appropriate data types
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
        df['close_time'] = pd.to_datetime(df['close_time'], unit='ms', utc=True)

        numeric_cols = ['open', 'high', 'low', 'close', 'volume',
                        'quote_asset_volume', 'taker_buy_base_asset_volume',
                        'taker_buy_quote_asset_volume']
        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col])

        df['number_of_trades'] = pd.to_numeric(df['number_of_trades'], errors='coerce').astype('Int64') # Allow NA for Int

        df.set_index('timestamp', inplace=True)

        # Filter by end_str precisely if it was provided, as API might return candles past end_ms
        if end_str:
            parsed_end_dt = datetime.strptime(end_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc) if len(end_str) > 10 else datetime.strptime(end_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            df = df[df.index <= parsed_end_dt]

        return df.sort_index()


    def subscribe_to_kline_stream(self, symbol: str, interval: str, callback: Callable):
        """
        Placeholder for subscribing to a kline WebSocket stream.
        """
        print(f"Placeholder: Subscribing to {symbol}@{interval} kline stream.")
        # Actual implementation will use self.binance_connector.start_websocket_market_stream
        # and manage the callback and stream lifecycle.
        pass

    def _on_kline_message(self, msg: Dict):
        """
        Placeholder for processing incoming kline messages from WebSocket.
        """
        print(f"Placeholder: Received kline message: {msg}")
        # This method would parse the message, update internal state (e.g., a DataFrame),
        # and then call the user-provided callback from subscribe_to_kline_stream.
        pass


if __name__ == '__main__':
    # This is an example usage, requires a .env file in the project root
    # with BINANCE_TESTNET_API_KEY and BINANCE_TESTNET_API_SECRET
    import os
    from dotenv import load_dotenv

    # Assuming this script (data_fetcher.py) is in bot/core/
    # and .env is in the project root (../../.env from here)
    dotenv_path = os.path.join(os.path.dirname(__file__), '../../.env')
    load_dotenv(dotenv_path=dotenv_path)

    API_KEY = os.getenv("BINANCE_TESTNET_API_KEY")
    API_SECRET = os.getenv("BINANCE_TESTNET_API_SECRET")
    USE_TESTNET = True

    if not API_KEY or API_KEY == "YOUR_TESTNET_API_KEY":
        print("Please set your BINANCE_TESTNET_API_KEY and API_SECRET in the .env file in the project root.")
    else:
        connector = BinanceAPI(api_key=API_KEY, api_secret=API_SECRET, testnet=USE_TESTNET)
        data_fetcher = MarketDataProvider(binance_connector=connector)

        try:
            print("Fetching historical klines for BTCUSDT (1h, last 5 candles from 2023-01-01)...")
            # Fetch a small number of klines for testing
            klines_df_recent = data_fetcher.get_historical_klines(
                symbol="BTCUSDT",
                interval="1h",
                start_str="2023-01-01 00:00:00",
                # end_str="2023-01-01 04:59:59", # Explicit end for 5 candles
                limit=5
            )
            print(klines_df_recent.head())
            print(f"\nFetched {len(klines_df_recent)} klines.")
            if not klines_df_recent.empty:
                 print(f"Index type: {type(klines_df_recent.index)}, Dtype: {klines_df_recent.index.dtype}")
                 print(f"Columns: {klines_df_recent.columns}")
                 print(klines_df_recent.info())


            print("\nFetching historical klines for BTCUSDT (1d, range 2023-01-01 to 2023-01-10, limit 10)...")
            # Test with a date range
            klines_df_range = data_fetcher.get_historical_klines(
                symbol="BTCUSDT",
                interval="1d",
                start_str="2023-01-01",
                end_str="2023-01-10", # Should fetch 10 candles
                limit=15 # Limit is higher than days, should be capped by date range
            )
            print(klines_df_range)
            print(f"\nFetched {len(klines_df_range)} klines for date range.")

            # Test fetching more than API limit (e.g., 2000 1h candles)
            # This will require pagination
            print("\nFetching historical klines for BTCUSDT (1h, 50 candles from 2023-02-01, requires 1 call)...")
            # Binance API limit is 1500 per request.
            # This example tests a small number of candles that would require pagination if MAX_KLINE_LIMIT_PER_REQUEST was small.
            # To truly test pagination over 1500, you'd need a larger limit.
            # For now, the pagination logic is there, but this specific call won't exceed 1500.
            # The internal loop for fetching is more about fetching up to a 'limit' if start_str is given,
            # or fetching a range.

            # To test actual pagination over 1500, you would do:
            # klines_df_paginated = data_fetcher.get_historical_klines(
            #     symbol="BTCUSDT",
            #     interval="1m", # 1m interval to get many candles quickly
            #     start_str="2023-03-01 00:00:00",
            #     end_str="2023-03-01 08:00:00", # 8 hours = 480 minutes
            #     limit=2000 # Effectively, fetch all in range up to this limit
            # )
            # print(klines_df_paginated)
            # print(f"\nFetched {len(klines_df_paginated)} klines for pagination test.")
            # assert len(klines_df_paginated) <= 480 # Should be 480 candles in 8 hours of 1m data

        except Exception as e:
            print(f"An error occurred during DataFetcher example: {e}")
            import traceback
            traceback.print_exc()

```
