import requests
import time
import hmac
import hashlib
import json
from urllib.parse import urlencode
import asyncio
import websockets
import threading
import logging
from typing import List, Callable, Dict, Optional


class BinanceAPI:
    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None, testnet: bool = False):
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet

        if testnet:
            self.base_url = "https://testnet.binancefuture.com/fapi"
            self.ws_base_url = "wss://fstream.binancefuture.com"
        else:
            self.base_url = "https://fapi.binance.com/fapi"
            self.ws_base_url = "wss://fstream.binance.com"

        self.session = requests.Session()
        self.logger = logging.getLogger('algo_trader_bot')

        self.active_market_websockets: Dict[str, Dict] = {}
        self._ws_stream_id_counter = 0
        self._ws_lock = threading.Lock()

        # User Data Stream attributes
        self.user_data_listen_key: Optional[str] = None
        self.user_data_ws_client: Optional[websockets.WebSocketClientProtocol] = None
        self.user_data_thread: Optional[threading.Thread] = None
        self.user_data_control_flag = {'keep_running': False} # Shared control flag for loops
        self.listen_key_refresh_interval = 30 * 60  # 30 minutes
        self.listen_key_refresher_thread: Optional[threading.Thread] = None


    def _generate_signature(self, data: str) -> str:
        if not self.api_secret:
            self.logger.error("API secret is not set. Cannot generate signature.")
            raise ValueError("API secret is not set. Cannot generate signature.")
        return hmac.new(self.api_secret.encode('utf-8'), data.encode('utf-8'), hashlib.sha256).hexdigest()

    def _prepare_params(self, params: dict) -> dict:
        return {k: v for k, v in params.items() if v is not None}

    def _make_request(self, method: str, endpoint: str, params: dict = None, is_signed: bool = False):
        if params is None:
            params = {}
        params = self._prepare_params(params)

        # For signed POST/PUT/DELETE, parameters for signature must be in query_string_for_signature
        # But the actual request might send them as form-data in body or in query string.
        # Binance API typically uses query string for all params in signed requests, even for POST/DELETE.

        query_params_for_req = params.copy() # Start with all params for the request query/body

        if is_signed:
            if not self.api_key or not self.api_secret:
                self.logger.error("API key and/or secret not provided for signed request.")
                raise ValueError("API key and/or secret not provided for signed request.")

            # Parameters for signature generation
            sign_params = params.copy()
            sign_params['timestamp'] = int(time.time() * 1000)
            sign_params['recvWindow'] = 60000

            query_string_for_signature = urlencode(sign_params)
            # The signature is generated from all parameters that would be sent,
            # regardless of whether they are in query string or body for the actual request.
            # For simplicity and common Binance practice, we'll build the URL with all params.

            # Update query_params_for_req for the actual request to include timestamp, recvWindow, and signature
            query_params_for_req['timestamp'] = sign_params['timestamp']
            query_params_for_req['recvWindow'] = sign_params['recvWindow']
            query_params_for_req['signature'] = self._generate_signature(query_string_for_signature)

        url = f"{self.base_url}{endpoint}"
        full_url = url
        request_body = None

        headers = {}
        if self.api_key: # Required for signed endpoints
            headers['X-MBX-APIKEY'] = self.api_key

        # For GET, DELETE: params in query string
        # For POST, PUT: params usually in query string for Binance signed, or body for non-signed/public
        if method.upper() in ['GET', 'DELETE'] or (is_signed and method.upper() in ['POST', 'PUT']):
            if query_params_for_req:
                full_url = f"{url}?{urlencode(query_params_for_req)}"
        elif method.upper() in ['POST', 'PUT'] and not is_signed: # Non-signed POST/PUT, params in body
            request_body = query_params_for_req # or json=query_params_for_req if API expects JSON body

        try:
            if method.upper() == 'GET':
                response = self.session.get(full_url, headers=headers)
            elif method.upper() == 'POST':
                response = self.session.post(full_url, headers=headers, data=None if is_signed else request_body)
            elif method.upper() == 'PUT':
                response = self.session.put(full_url, headers=headers, data=None if is_signed else request_body)
            elif method.upper() == 'DELETE':
                response = self.session.delete(full_url, headers=headers)
            else:
                self.logger.error(f"Unsupported HTTP method: {method}")
                raise ValueError(f"Unsupported HTTP method: {method}")

            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as http_err:
            error_msg = f"HTTP error: {http_err.response.status_code} {http_err.response.reason} for url {http_err.request.url} - Full response: {http_err.response.text}"
            try:
                err_json = http_err.response.json()
                error_msg += f" - Binance Error Code: {err_json.get('code')}, Message: {err_json.get('msg')}"
            except json.JSONDecodeError:
                pass
            self.logger.error(error_msg, exc_info=True)
            raise Exception(error_msg)
        except requests.exceptions.RequestException as req_err:
            self.logger.error(f"Request exception: {req_err} for url {req_err.request.url if req_err.request else 'N/A'}", exc_info=True)
            raise Exception(f"Request exception occurred: {req_err}")


    # --- User Data Stream Methods ---
    def _get_listen_key(self) -> Optional[str]:
        self.logger.info("Attempting to get new listen key for user data stream.")
        try:
            # is_signed should be True, but _make_request handles adding signature if api_key/secret are present
            # For POST /fapi/v1/listenKey, it's a signed endpoint but takes no parameters for signature itself.
            # The signature is generated based on an empty parameter string if no params are sent.
            # However, our _make_request adds timestamp/recvWindow which are then signed.
            # The endpoint POST /fapi/v1/listenKey actually requires API Key in header but no signed params.
            # This needs a slight adjustment in _make_request or a specific call here.
            # For now, let's try with is_signed=False, but ensure API key header is sent.

            # Correct approach for listenKey: it's a POST, needs API key, but no body/query params for signature.
            # Our _make_request might overcomplicate this. Let's use session directly for this specific case.
            url = f"{self.base_url}/fapi/v1/listenKey"
            headers = {'X-MBX-APIKEY': self.api_key} if self.api_key else {}
            if not headers:
                 self.logger.error("API Key must be provided for listen key operations.")
                 raise ValueError("API Key must be provided for listen key operations.")

            response = self.session.post(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            self.user_data_listen_key = data.get('listenKey')
            if self.user_data_listen_key:
                self.logger.info(f"Obtained listen key: {self.user_data_listen_key[:10]}...")
                return self.user_data_listen_key
            else:
                self.logger.error(f"Failed to get listen key from response: {data}")
                return None
        except Exception as e:
            self.logger.error(f"Error getting listen key: {e}", exc_info=True)
            return None

    def _keep_listen_key_alive(self) -> bool:
        if not self.user_data_listen_key:
            self.logger.warning("No listen key available to keep alive.")
            return False
        self.logger.info(f"Attempting to keep listen key alive: {self.user_data_listen_key[:10]}...")
        try:
            # Similar to _get_listen_key, PUT /fapi/v1/listenKey needs API key, no signed body.
            # The listenKey itself is not sent in the request body or query for PUT.
            url = f"{self.base_url}/fapi/v1/listenKey" # Some docs say params={'listenKey': self.user_data_listen_key}
                                                      # but official python-binance does not send it for PUT.
                                                      # For futures, it seems no listenKey param is needed for PUT.
            headers = {'X-MBX-APIKEY': self.api_key} if self.api_key else {}
            if not headers:
                 self.logger.error("API Key must be provided for listen key operations.")
                 raise ValueError("API Key must be provided for listen key operations.")

            response = self.session.put(url, headers=headers) # No params needed for PUT according to some examples
            response.raise_for_status()
            self.logger.info(f"Listen key kept alive successfully ({response.status_code}). Response: {response.json()}")
            return response.status_code == 200
        except Exception as e:
            self.logger.error(f"Error keeping listen key alive: {e}", exc_info=True)
            return False

    def _close_listen_key(self) -> bool:
        if not self.user_data_listen_key:
            self.logger.info("No listen key to close.")
            return False
        self.logger.info(f"Attempting to close listen key: {self.user_data_listen_key[:10]}...")
        try:
            # DELETE /fapi/v1/listenKey - also just needs API key, listenKey is implicit to the API key for deletion
            # Some docs imply listenKey param is needed, others not. Test what official connector does.
            # Let's assume it doesn't need it in query/body and is tied to API key.
            # If it does, it would be params={'listenKey': self.user_data_listen_key}
            url = f"{self.base_url}/fapi/v1/listenKey"
            headers = {'X-MBX-APIKEY': self.api_key} if self.api_key else {}
            if not headers:
                 self.logger.error("API Key must be provided for listen key operations.")
                 raise ValueError("API Key must be provided for listen key operations.")

            response = self.session.delete(url, headers=headers) # No params for DELETE by default here
            response.raise_for_status()
            self.logger.info(f"Listen key closed successfully ({response.status_code}). Response: {response.json()}")
            return response.status_code == 200
        except Exception as e:
            self.logger.error(f"Error closing listen key: {e}", exc_info=True)
            return False


    def _listen_key_refresher_loop(self):
        self.logger.info("Listen key refresher loop started.")
        while self.user_data_control_flag.get('keep_running') and self.user_data_listen_key:
            for _ in range(self.listen_key_refresh_interval): # Check every second
                if not self.user_data_control_flag.get('keep_running'):
                    break
                time.sleep(1)
            if self.user_data_control_flag.get('keep_running') and self.user_data_listen_key:
                if not self._keep_listen_key_alive():
                    self.logger.warning("Failed to keep listen key alive in refresher loop. Stream might disconnect.")
                    # Optionally, try to get a new key and restart stream if this happens.
            else:
                break # Exit if flag turned off or listen key cleared
        self.logger.info("Listen key refresher loop stopped.")


    def start_user_stream(self, callback: Callable) -> bool:
        if self.user_data_control_flag.get('keep_running'):
            self.logger.warning("User data stream is already running.")
            return False

        if not self._get_listen_key() or not self.user_data_listen_key:
            self.logger.error("Failed to start user stream: Could not obtain listen key.")
            return False

        self.user_data_control_flag['keep_running'] = True

        async def _user_ws_handler():
            ws_url = f"{self.ws_base_url}/ws/{self.user_data_listen_key}"
            self.logger.info(f"User data stream WebSocket handler started for URL: {ws_url}")

            while self.user_data_control_flag.get('keep_running'):
                try:
                    async with websockets.connect(ws_url, ping_interval=60, ping_timeout=30) as ws:
                        self.user_data_ws_client = ws
                        self.logger.info("User data stream WebSocket connected.")
                        while self.user_data_control_flag.get('keep_running'):
                            try:
                                message = await asyncio.wait_for(ws.recv(), timeout=1.0)
                                data = json.loads(message)
                                callback(data)
                                self.logger.debug(f"User WS Recv: {message[:200]}")
                            except asyncio.TimeoutError:
                                continue
                            except websockets.exceptions.ConnectionClosed:
                                self.logger.warning("User data stream WebSocket connection closed. Will attempt reconnect if keep_running.")
                                break # To outer loop for reconnection
                            except Exception as e_recv:
                                self.logger.error(f"Error during user data stream message processing: {e_recv}", exc_info=True)
                                # Decide if to break or continue based on error
                                await asyncio.sleep(1) # Avoid tight loop on continuous error

                        if not self.user_data_control_flag.get('keep_running'):
                            break # Exit if outer control says stop

                except Exception as e_ws_connect:
                    self.logger.error(f"Error connecting to user data stream WebSocket: {e_ws_connect}", exc_info=True)

                if self.user_data_control_flag.get('keep_running'):
                    self.logger.info("Attempting user data stream WebSocket reconnect in 5 seconds...")
                    await asyncio.sleep(5)
                else:
                    break

            self.user_data_ws_client = None
            self.logger.info("User data stream WebSocket handler finished.")

        def _run_user_ws_handler_in_thread():
            try:
                asyncio.run(_user_ws_handler())
            except Exception as e_thread_run:
                self.logger.error(f"Exception in user data stream thread runner: {e_thread_run}", exc_info=True)

        self.user_data_thread = threading.Thread(target=_run_user_ws_handler_in_thread, daemon=True, name="UserDataThread")
        self.user_data_thread.start()

        self.listen_key_refresher_thread = threading.Thread(target=self._listen_key_refresher_loop, daemon=True, name="ListenKeyRefresherThread")
        self.listen_key_refresher_thread.start()

        self.logger.info("User data stream services (WebSocket and listen key refresher) started.")
        return True

    def stop_user_stream(self):
        if self.user_data_control_flag.get('keep_running'):
            self.logger.info("Attempting to stop user data stream services...")
            self.user_data_control_flag['keep_running'] = False

            if self.user_data_thread and self.user_data_thread.is_alive():
                self.logger.debug("Joining user data WebSocket thread...")
                self.user_data_thread.join(timeout=5.0)
                if self.user_data_thread.is_alive():
                    self.logger.warning("User data WebSocket thread did not join in time.")

            if self.listen_key_refresher_thread and self.listen_key_refresher_thread.is_alive():
                self.logger.debug("Joining listen key refresher thread...")
                self.listen_key_refresher_thread.join(timeout=5.0) # It checks keep_running every second
                if self.listen_key_refresher_thread.is_alive():
                     self.logger.warning("Listen key refresher thread did not join in time.")

            if self.user_data_listen_key:
                self._close_listen_key() # Attempt to close the listen key on server

            self.user_data_listen_key = None
            self.user_data_ws_client = None # Should be None already from handler exit
            self.logger.info("User data stream services stopped.")
        else:
            self.logger.info("User data stream is not currently running.")


    # --- Market Data WebSocket Methods (existing) ---
    def _get_next_stream_id(self) -> str:
        with self._ws_lock:
            self._ws_stream_id_counter += 1
            return f"market_ws_{self._ws_stream_id_counter}"

    def start_market_stream(self, stream_names: List[str], callback: Callable) -> str: # Removed stream_type for now
        if not stream_names:
            self.logger.error("stream_names cannot be empty for start_market_stream.")
            raise ValueError("stream_names cannot be empty.")

        stream_id = self._get_next_stream_id()

        if len(stream_names) == 1:
            path = f"/ws/{stream_names[0].lower()}" # Ensure stream names are lowercase
        else:
            streams_param = "/".join([s.lower() for s in stream_names])
            path = f"/stream?streams={streams_param}"

        full_ws_url = f"{self.ws_base_url}{path}"

        control = {'keep_running': True}
        self.active_market_websockets[stream_id] = {
            'ws_client': None, 'control': control, 'thread': None, 'url': full_ws_url
        }

        async def _ws_handler():
            self.logger.info(f"Market WebSocket handler started for stream ID {stream_id} ({full_ws_url})")
            while control['keep_running']:
                try:
                    async with websockets.connect(full_ws_url, ping_interval=60, ping_timeout=30) as ws:
                        self.active_market_websockets[stream_id]['ws_client'] = ws
                        self.logger.info(f"Market WebSocket connected for stream ID {stream_id}.")
                        while control['keep_running']:
                            try:
                                message = await asyncio.wait_for(ws.recv(), timeout=1.0)
                                data = json.loads(message)
                                callback(data)
                                self.logger.debug(f"Market WS Recv ({stream_id}): {message[:200]}")
                            except asyncio.TimeoutError:
                                continue
                            except websockets.exceptions.ConnectionClosed:
                                self.logger.warning(f"Market WebSocket ConnectionClosed for ID {stream_id}. Will attempt reconnect if keep_running.")
                                break
                            except Exception as e_inner:
                                self.logger.error(f"Error in Market WebSocket handler ({stream_id}) inner loop: {e_inner}", exc_info=True)
                                await asyncio.sleep(1)
                        if not control['keep_running']: break
                except Exception as e_outer: # Catch connection errors too
                    self.logger.error(f"Error connecting to Market WebSocket ({stream_id}): {e_outer}", exc_info=True)
                if control['keep_running']:
                    self.logger.info(f"Attempting Market WebSocket reconnect for ID {stream_id} in 5s...")
                    await asyncio.sleep(5)
                else: break
            self.logger.info(f"Market WebSocket handler stopped for stream ID {stream_id}.")

        def _run_ws_handler_in_thread():
            try: asyncio.run(_ws_handler())
            except Exception as e_thread: self.logger.error(f"Exception in Market WebSocket thread ({stream_id}): {e_thread}", exc_info=True)

        thread = threading.Thread(target=_run_ws_handler_in_thread, daemon=True, name=f"MarketWsThread-{stream_id}")
        self.active_market_websockets[stream_id]['thread'] = thread
        thread.start()
        self.logger.info(f"Market stream {stream_id} started for {', '.join(stream_names)} on URL: {full_ws_url}")
        return stream_id

    def stop_market_stream(self, stream_id: str):
        if stream_id in self.active_market_websockets:
            self.logger.info(f"Stopping market stream {stream_id}...")
            control = self.active_market_websockets[stream_id]['control']
            control['keep_running'] = False
            thread = self.active_market_websockets[stream_id].get('thread')
            if thread and thread.is_alive():
                self.logger.debug(f"Waiting for Market WebSocket thread {stream_id} to join...")
                thread.join(timeout=10)
                if thread.is_alive(): self.logger.warning(f"Market WebSocket thread {stream_id} did not join in time.")
            del self.active_market_websockets[stream_id]
            self.logger.info(f"Market stream {stream_id} stopped and removed.")
        else:
            self.logger.warning(f"Attempted to stop non-existent market stream ID: {stream_id}")

    # --- REST API Methods ---
    def ping(self): return self._make_request(method='GET', endpoint='/v1/ping')
    def get_server_time(self): return self._make_request(method='GET', endpoint='/v1/time')
    def get_exchange_info(self): return self._make_request(method='GET', endpoint='/v1/exchangeInfo')
    def get_klines(self, symbol: str, interval: str, startTime: int = None, endTime: int = None, limit: int = 500):
        params = {'symbol': symbol, 'interval': interval, 'startTime': startTime, 'endTime': endTime, 'limit': limit}
        return self._make_request(method='GET', endpoint='/v1/klines', params=params)
    def get_order_book(self, symbol: str, limit: int = 100):
        params = {'symbol': symbol, 'limit': limit}
        return self._make_request(method='GET', endpoint='/v1/depth', params=params)
    def get_recent_trades(self, symbol: str, limit: int = 500):
        params = {'symbol': symbol, 'limit': limit}
        return self._make_request(method='GET', endpoint='/v1/trades', params=params)
    def get_mark_price(self, symbol: str = None):
        params = {'symbol': symbol} if symbol else {}
        return self._make_request(method='GET', endpoint='/v1/premiumIndex', params=params)
    def place_order(self, symbol: str, side: str, ord_type: str, quantity: float = None,
                    price: float = None, timeInForce: str = None, reduceOnly: bool = None,
                    newClientOrderId: str = None, stopPrice: float = None, closePosition: bool = None,
                    workingType: str = None, positionSide: str = None, newOrderRespType: str = 'ACK'):
        params = {'symbol': symbol, 'side': side, 'type': ord_type, 'quantity': quantity, 'price': price,
                  'timeInForce': timeInForce, 'newClientOrderId': newClientOrderId, 'stopPrice': stopPrice,
                  'workingType': workingType, 'positionSide': positionSide, 'newOrderRespType': newOrderRespType}
        if reduceOnly is not None: params['reduceOnly'] = "true" if reduceOnly else "false"
        if closePosition is not None: params['closePosition'] = "true" if closePosition else "false"
        return self._make_request(method='POST', endpoint='/v1/order', params=params, is_signed=True)
    def get_order_status(self, symbol: str, orderId: int = None, origClientOrderId: str = None):
        if not orderId and not origClientOrderId: raise ValueError("Either orderId or origClientOrderId must be sent.")
        params = {'symbol': symbol, 'orderId': orderId, 'origClientOrderId': origClientOrderId}
        return self._make_request(method='GET', endpoint='/v1/order', params=params, is_signed=True)
    def cancel_order(self, symbol: str, orderId: int = None, origClientOrderId: str = None):
        if not orderId and not origClientOrderId: raise ValueError("Either orderId or origClientOrderId must be sent.")
        params = {'symbol': symbol, 'orderId': orderId, 'origClientOrderId': origClientOrderId}
        return self._make_request(method='DELETE', endpoint='/v1/order', params=params, is_signed=True)
    def get_open_orders(self, symbol: str = None):
        params = {'symbol': symbol} if symbol else {}
        return self._make_request(method='GET', endpoint='/v1/openOrders', params=params, is_signed=True)
    def get_all_orders(self, symbol: str, orderId: int = None, startTime: int = None, endTime: int = None, limit: int = 500):
        params = {'symbol': symbol, 'orderId': orderId, 'startTime': startTime, 'endTime': endTime, 'limit': limit}
        return self._make_request(method='GET', endpoint='/v1/allOrders', params=params, is_signed=True)
    def get_account_balance(self):
        return self._make_request(method='GET', endpoint='/v2/balance', params={}, is_signed=True)
    def get_position_information(self, symbol: str = None):
        params = {'symbol': symbol} if symbol else {}
        return self._make_request(method='GET', endpoint='/v2/positionRisk', params=params, is_signed=True)


if __name__ == '__main__':
    import os
    from dotenv import load_dotenv

    # Setup basic logger for console output during this test
    if not logging.getLogger('algo_trader_bot').hasHandlers():
        logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(module)s - %(funcName)s - %(message)s')

    logger_main = logging.getLogger('algo_trader_bot')

    dotenv_path = os.path.join(os.path.dirname(__file__), '../../.env')
    load_dotenv(dotenv_path=dotenv_path)
    API_KEY = os.getenv("BINANCE_TESTNET_API_KEY")
    API_SECRET = os.getenv("BINANCE_TESTNET_API_SECRET")

    if not (API_KEY and API_SECRET and API_KEY != "YOUR_TESTNET_API_KEY"):
        logger_main.error("API_KEY and API_SECRET must be set in .env file and not be placeholders.")
        exit()

    USE_TESTNET = True
    connector = BinanceAPI(api_key=API_KEY, api_secret=API_SECRET, testnet=USE_TESTNET)

    def sample_user_data_callback(data):
        event_type = data.get('e')
        if event_type == 'ACCOUNT_UPDATE':
            logger_main.info(f"User Stream (ACCOUNT_UPDATE): Positions: {data.get('a', {}).get('P')}")
        elif event_type == 'ORDER_TRADE_UPDATE':
            logger_main.info(f"User Stream (ORDER_TRADE_UPDATE): Symbol {data.get('o',{}).get('s')}, Status {data.get('o',{}).get('X')}")
        else:
            logger_main.info(f"User Stream ({event_type}): {data}")

    user_stream_started = False
    try:
        logger_main.info("\n--- Testing WebSocket User Data Stream ---")
        user_stream_started = connector.start_user_stream(callback=sample_user_data_callback)

        if user_stream_started:
            logger_main.info("User data stream started. Waiting for 60 seconds to receive events...")
            time.sleep(60) # Keep main thread alive to receive user data
            # Try placing a small order to trigger an event, if desired for testing
            # Be very careful with automated order placement, even on testnet
            # try:
            #     logger_main.info("Placing a small test order on BTCUSDT to trigger user data event...")
            #     test_order = connector.place_order(symbol="BTCUSDT", side="BUY", ord_type="MARKET", quantity=0.001, positionSide="BOTH")
            #     logger_main.info(f"Test order placement response: {test_order}")
            # except Exception as e_order:
            #     logger_main.error(f"Error placing test order: {e_order}")
            # time.sleep(10) # Wait for order event

        else:
            logger_main.error("User data stream failed to start.")

    except KeyboardInterrupt:
        logger_main.info("Keyboard interrupt received. Stopping streams...")
    except Exception as e:
        logger_main.error(f"An error occurred during User Data Stream test: {e}", exc_info=True)
    finally:
        if user_stream_started:
            logger_main.info("\nStopping user data stream...")
            connector.stop_user_stream()

        logger_main.info("Waiting a bit for user stream threads to clean up...")
        time.sleep(5)
        logger_main.info("User data stream test finished.")
```
