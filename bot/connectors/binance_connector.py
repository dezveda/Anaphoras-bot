import requests
import time
import hmac
import hashlib
import json
from urllib.parse import urlencode

class BinanceAPI:
    def __init__(self, api_key=None, api_secret=None, testnet=False):
        self.api_key = api_key
        self.api_secret = api_secret
        if testnet:
            self.base_url = "https://testnet.binancefuture.com/fapi"
        else:
            self.base_url = "https://fapi.binance.com/fapi"

        self.session = requests.Session()
        # API Key header is added in _make_request if needed

    def _generate_signature(self, data: str) -> str:
        """Generates HMAC SHA256 signature."""
        if not self.api_secret:
            raise ValueError("API secret is not set. Cannot generate signature.")
        return hmac.new(self.api_secret.encode('utf-8'), data.encode('utf-8'), hashlib.sha256).hexdigest()

    def _prepare_params(self, params: dict) -> dict:
        """Removes None values from params dict."""
        return {k: v for k, v in params.items() if v is not None}

    def _make_request(self, method: str, endpoint: str, params: dict = None, is_signed: bool = False):
        """Makes an HTTP request to the specified endpoint."""
        if params is None:
            params = {}

        # Remove None values from params before any processing
        params = self._prepare_params(params)

        url = f"{self.base_url}{endpoint}"

        headers = {}
        if self.api_key: # Required for signed endpoints, optional for some public ones if specific permissions are needed
            headers['X-MBX-APIKEY'] = self.api_key

        query_string = ""
        request_body = None

        if is_signed:
            if not self.api_key or not self.api_secret:
                raise ValueError("API key and/or secret not provided for signed request.")

            params['timestamp'] = int(time.time() * 1000)
            params['recvWindow'] = 60000  # Max recvWindow, can be configured

            query_string_for_signature = urlencode(params)
            params['signature'] = self._generate_signature(query_string_for_signature)

        # For all methods, parameters are typically sent as query string
        # For POST, PUT, DELETE, if params were meant for body, they should be handled differently (e.g. json=params for POST)
        # However, Binance often uses query string for parameters even in POST/DELETE for signed endpoints.
        # Let's assume all params go into query string for now, as it's common for Binance.
        if params:
            query_string = urlencode(params)
            url = f"{url}?{query_string}"

        try:
            if method.upper() == 'GET':
                response = self.session.get(url, headers=headers)
            elif method.upper() == 'POST':
                # For POST, if data needs to be in the body and not query string:
                # response = self.session.post(f"{self.base_url}{endpoint}", data=params, headers=headers)
                # But since signature includes all params, they usually go in query.
                response = self.session.post(url, headers=headers) # Params are already in URL
            elif method.upper() == 'PUT':
                response = self.session.put(url, headers=headers) # Params are already in URL
            elif method.upper() == 'DELETE':
                response = self.session.delete(url, headers=headers) # Params are already in URL
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as http_err:
            error_msg = f"HTTP error occurred: {http_err} - {response.status_code} - {response.text}"
            try:
                err_json = response.json()
                error_msg += f" - Binance Error Code: {err_json.get('code')}, Message: {err_json.get('msg')}"
            except json.JSONDecodeError:
                pass
            raise Exception(error_msg)
        except requests.exceptions.RequestException as req_err:
            raise Exception(f"Request exception occurred: {req_err}")

    # Public Endpoints
    def ping(self):
        """Tests connectivity to the Rest API."""
        return self._make_request(method='GET', endpoint='/v1/ping')

    def get_server_time(self):
        """Gets the current server time."""
        return self._make_request(method='GET', endpoint='/v1/time')

    def get_exchange_info(self):
        """Gets exchange trading rules and symbol information."""
        return self._make_request(method='GET', endpoint='/v1/exchangeInfo')

    def get_klines(self, symbol: str, interval: str, startTime: int = None, endTime: int = None, limit: int = 500):
        """Gets kline/candlestick bars for a symbol."""
        params = {
            'symbol': symbol,
            'interval': interval,
            'startTime': startTime,
            'endTime': endTime,
            'limit': limit
        }
        return self._make_request(method='GET', endpoint='/v1/klines', params=params)

    def get_order_book(self, symbol: str, limit: int = 100):
        """Gets the order book (depth) for a symbol."""
        params = {'symbol': symbol, 'limit': limit}
        return self._make_request(method='GET', endpoint='/v1/depth', params=params)

    def get_recent_trades(self, symbol: str, limit: int = 500):
        """Gets recent trades for a symbol."""
        params = {'symbol': symbol, 'limit': limit}
        return self._make_request(method='GET', endpoint='/v1/trades', params=params)

    def get_mark_price(self, symbol: str = None):
        """Gets mark price and premium index for a symbol or all symbols."""
        params = {'symbol': symbol} if symbol else {}
        return self._make_request(method='GET', endpoint='/v1/premiumIndex', params=params)

    # Account/Signed Endpoints
    def place_order(self, symbol: str, side: str, ord_type: str, quantity: float = None,
                    price: float = None, timeInForce: str = None, reduceOnly: bool = None,
                    newClientOrderId: str = None, stopPrice: float = None, closePosition: bool = None,
                    workingType: str = None, positionSide: str = None, newOrderRespType: str = 'ACK'):
        """Places a new order."""
        params = {
            'symbol': symbol,
            'side': side,
            'type': ord_type, # API uses 'type' for order type
            'quantity': quantity,
            'price': price,
            'timeInForce': timeInForce,
            'newClientOrderId': newClientOrderId,
            'stopPrice': stopPrice,
            'workingType': workingType,
            'positionSide': positionSide,
            'newOrderRespType': newOrderRespType
        }
        if reduceOnly is not None:
            params['reduceOnly'] = "true" if reduceOnly else "false"
        if closePosition is not None:
            params['closePosition'] = "true" if closePosition else "false"

        return self._make_request(method='POST', endpoint='/v1/order', params=params, is_signed=True)

    def get_order_status(self, symbol: str, orderId: int = None, origClientOrderId: str = None):
        """Checks an order's status."""
        if not orderId and not origClientOrderId:
            raise ValueError("Either orderId or origClientOrderId must be provided.")
        params = {
            'symbol': symbol,
            'orderId': orderId,
            'origClientOrderId': origClientOrderId
        }
        return self._make_request(method='GET', endpoint='/v1/order', params=params, is_signed=True)

    def cancel_order(self, symbol: str, orderId: int = None, origClientOrderId: str = None):
        """Cancels an active order."""
        if not orderId and not origClientOrderId:
            raise ValueError("Either orderId or origClientOrderId must be provided.")
        params = {
            'symbol': symbol,
            'orderId': orderId,
            'origClientOrderId': origClientOrderId
        }
        return self._make_request(method='DELETE', endpoint='/v1/order', params=params, is_signed=True)

    def get_open_orders(self, symbol: str = None):
        """Gets all open orders on a symbol or all symbols."""
        params = {'symbol': symbol} if symbol else {}
        return self._make_request(method='GET', endpoint='/v1/openOrders', params=params, is_signed=True)

    def get_all_orders(self, symbol: str, orderId: int = None, startTime: int = None, endTime: int = None, limit: int = 500):
        """Get all account orders; active, canceled, or filled.
           Note: If orderId is set, it will get orders >= that orderId. Otherwise most recent orders are returned.
        """
        params = {
            'symbol': symbol,
            'orderId': orderId,
            'startTime': startTime,
            'endTime': endTime,
            'limit': limit
        }
        return self._make_request(method='GET', endpoint='/v1/allOrders', params=params, is_signed=True)

    def get_account_balance(self):
        """Gets account balance (v2 for more details)."""
        # Using /v2/balance as it's often recommended for futures
        return self._make_request(method='GET', endpoint='/v2/balance', params={}, is_signed=True)

    def get_position_information(self, symbol: str = None):
        """Gets position information (v2 for more details)."""
        # Using /v2/positionRisk as it's often recommended
        params = {'symbol': symbol} if symbol else {}
        return self._make_request(method='GET', endpoint='/v2/positionRisk', params=params, is_signed=True)


if __name__ == '__main__':
    # Example usage:
    # Load API keys from .env file (assuming .env is in the project root)
    import os
    from dotenv import load_dotenv
    # Construct the path to the .env file.
    # This assumes this script (binance_connector.py) is in bot/connectors/
    # So, .env would be two levels up.
    dotenv_path = os.path.join(os.path.dirname(__file__), '../../.env')
    load_dotenv(dotenv_path=dotenv_path)

    API_KEY = os.getenv("BINANCE_TESTNET_API_KEY")
    API_SECRET = os.getenv("BINANCE_TESTNET_API_SECRET")
    USE_TESTNET = True # True for testnet, False for mainnet

    print(f"Attempting to use Testnet: {USE_TESTNET}")
    print(f"API Key Loaded: {'Yes' if API_KEY and API_KEY != 'YOUR_TESTNET_API_KEY' else 'No or Placeholder'}")
    # Be careful not to print the secret itself

    connector = BinanceAPI(api_key=API_KEY, api_secret=API_SECRET, testnet=USE_TESTNET)

    try:
        print("\n--- Public Endpoints ---")
        print("Pinging server...")
        print(f"Ping: {connector.ping()}")
        print("Getting server time...")
        server_time = connector.get_server_time()
        print(f"Server Time: {server_time} (ms: {server_time.get('serverTime')})")

        print("\nGetting BTCUSDT klines (1m, limit 3)...")
        klines = connector.get_klines(symbol="BTCUSDT", interval="1m", limit=3)
        print(f"Klines: {klines}")

        print("\nGetting BTCUSDT Order Book (limit 5)...")
        order_book = connector.get_order_book(symbol="BTCUSDT", limit=5)
        print(f"Order Book: {order_book}")

        print("\nGetting BTCUSDT Recent Trades (limit 3)...")
        trades = connector.get_recent_trades(symbol="BTCUSDT", limit=3)
        print(f"Recent Trades: {trades}")

        print("\nGetting BTCUSDT Mark Price...")
        mark_price = connector.get_mark_price(symbol="BTCUSDT")
        print(f"Mark Price BTCUSDT: {mark_price}")

        print("\nGetting Exchange Info (first few symbols)...")
        exchange_info = connector.get_exchange_info()
        if exchange_info and 'symbols' in exchange_info:
            print(f"Total symbols: {len(exchange_info['symbols'])}")
            for i, symbol_data in enumerate(exchange_info['symbols'][:2]): # Print first 2 symbols
                 print(f"Symbol {i+1}: {symbol_data['symbol']}, Status: {symbol_data['status']}")
        else:
            print("Could not fetch or parse exchange info symbols.")


        if API_KEY and API_KEY != "YOUR_TESTNET_API_KEY" and API_SECRET:
            print("\n--- Signed Endpoints (Testnet) ---")

            print("Getting account balance...")
            balance = connector.get_account_balance()
            # print(f"Account Balance: {balance}") # Full balance can be very long
            if isinstance(balance, list):
                for asset_balance in balance:
                    if asset_balance.get('asset') == 'USDT': # Example: print only USDT balance
                        print(f"USDT Balance: {asset_balance}")
            else:
                print(f"Account Balance: {balance}")


            print("\nGetting position information (BTCUSDT)...")
            positions = connector.get_position_information(symbol="BTCUSDT")
            # print(f"Position Info: {positions}")
            if isinstance(positions, list):
                for position in positions:
                    print(f"Position for {position.get('symbol')}: Amount {position.get('positionAmt')}, Entry {position.get('entryPrice')}, PnL {position.get('unRealizedProfit')}")
            else:
                print(f"Position Info for BTCUSDT: {positions}")


            print("\nGetting open orders (BTCUSDT)...")
            open_orders = connector.get_open_orders(symbol="BTCUSDT")
            print(f"Open Orders for BTCUSDT: {open_orders}")

            # Example: Placing a test order (ensure symbol and parameters are valid for testnet)
            # This is a high price to avoid accidental fill if testnet market is live
            # print("\nPlacing a test order for BTCUSDT (LIMIT BUY)...")
            # try:
            #     test_order_params = {
            #         'symbol': "BTCUSDT",
            #         'side': "BUY",
            #         'positionSide': "BOTH", # or LONG/SHORT if in hedge mode
            #         'ord_type': "LIMIT",
            #         'quantity': 0.001,
            #         'price': 10000, # Deliberately low price for BUY to not fill, or high for SELL
            #         'timeInForce': "GTC"
            #     }
            #     # placed_order = connector.place_order(**test_order_params)
            #     # print(f"Placed Order: {placed_order}")
            #     # order_id_to_check = placed_order.get('orderId')

            #     # if order_id_to_check:
            #     #     print(f"\nGetting status for order ID {order_id_to_check}...")
            #     #     order_status = connector.get_order_status(symbol="BTCUSDT", orderId=order_id_to_check)
            #     #     print(f"Order Status: {order_status}")

            #     #     print(f"\nCancelling order ID {order_id_to_check}...")
            #     #     cancel_status = connector.cancel_order(symbol="BTCUSDT", orderId=order_id_to_check)
            #     #     print(f"Cancel Status: {cancel_status}")
            #     print("Order placement/cancel commented out for safety in test run.")

            # except Exception as e_order:
            #     print(f"Error during order placement/cancellation: {e_order}")

        else:
            print("\nSkipping signed endpoint tests as API_KEY or API_SECRET are placeholders or not found.")

    except Exception as e:
        print(f"An error occurred: {e}")
        import traceback
        traceback.print_exc()
