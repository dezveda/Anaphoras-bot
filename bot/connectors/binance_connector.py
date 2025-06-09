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
from typing import List, Callable, Dict, Optional, Any
import functools


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

        self.session = requests.Session() # Synchronous session for now
        self.logger = logging.getLogger('algo_trader_bot')

        self.active_market_websockets: Dict[str, Dict] = {}
        self._ws_stream_id_counter = 0
        self._ws_lock = threading.Lock()

        self.user_data_listen_key: Optional[str] = None
        self.user_data_ws_client: Optional[websockets.WebSocketClientProtocol] = None
        self.user_data_thread: Optional[threading.Thread] = None
        self.user_data_control_flag = {'keep_running': False}
        self.listen_key_refresh_interval = 30 * 60  # 30 minutes
        self.listen_key_refresher_thread: Optional[threading.Thread] = None

        # Configuration for async HTTP requests
        self.recv_window = 60000 # Max is 60000 for futures
        self.timeout = 10 # HTTP request timeout in seconds
        self.http_headers = {
            'Content-Type': 'application/json;charset=utf-8', # Though often x-www-form-urlencoded for Binance
            'Accept': 'application/json'
        }


    def _generate_signature(self, data: str) -> str:
        if not self.api_secret:
            self.logger.error("API secret is not set. Cannot generate signature.")
            raise ValueError("API secret is not set for signature generation.")
        return hmac.new(self.api_secret.encode('utf-8'), data.encode('utf-8'), hashlib.sha256).hexdigest()

    def _prepare_params(self, params: dict) -> dict:
        """Removes None values from params dict, as Binance API might not like empty values for some optional params."""
        return {k: v for k, v in params.items() if v is not None}

    def _get_headers(self, requires_api_key: bool = False) -> dict:
        """Prepares headers for HTTP requests."""
        headers = self.http_headers.copy()
        if requires_api_key and self.api_key:
            headers['X-MBX-APIKEY'] = self.api_key
        elif requires_api_key and not self.api_key:
            self.logger.error("API key required but not set.")
            raise ValueError("API key is required for this endpoint but not set.")
        return headers

    def _sign_request_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Adds timestamp, recvWindow to the payload, generates signature from its urlencoded form,
        and adds the signature to the payload.
        Modifies the payload dictionary in-place.
        """
        if not self.api_key or not self.api_secret: # Should be checked before calling this
            raise ValueError("API key and secret must be set for signing requests.")

        payload['timestamp'] = int(time.time() * 1000)
        payload['recvWindow'] = self.recv_window

        # Ensure all values are appropriate for urlencode (e.g. bools to string)
        # Our _prepare_params should handle None, but bools might need explicit conversion
        # For signing, Binance expects boolean 'true'/'false' as strings if they are part of the query.
        # However, if a boolean is for a JSON body, it should remain boolean.
        # This function signs based on urlencoded string, so bools should be strings here if they were query params.
        # This is mostly handled by how params are constructed before calling this.

        query_string_to_sign = urlencode({k: v for k, v in payload.items() if v is not None and k != 'signature'}) # Exclude signature if already there
        payload['signature'] = self._generate_signature(query_string_to_sign)
        return payload


    async def _make_request(self, method: str, endpoint: str,
                            params: Optional[Dict[str, Any]] = None, # For query string
                            data_payload: Optional[Dict[str, Any]] = None, # For request body (e.g., x-www-form-urlencoded or JSON)
                            is_signed: bool = False,
                            requires_api_key: bool = False): # Some endpoints need API key but aren't signed

        loop = asyncio.get_event_loop()

        # Prepare parameters and data (remove Nones, etc.)
        final_query_params = self._prepare_params(params.copy() if params else {})
        final_body_data = self._prepare_params(data_payload.copy() if data_payload else {})

        current_headers = self._get_headers(requires_api_key=(is_signed or requires_api_key))
        full_url = f"{self.base_url}{endpoint}"

        # Determine what to sign. For Binance:
        # - GET/DELETE: Sign all query parameters.
        # - POST/PUT: Typically sign all parameters (query + form body).
        #   If JSON body, JSON body is NOT part of signature string; only signed query params.
        #   For this implementation, we'll assume for signed POST/PUT, all business params
        #   are sent in the query string and signed there, matching common Binance client behavior.
        #   If a specific endpoint requires a signed JSON body, it would need special handling.

        if is_signed:
            if not self.api_key or not self.api_secret:
                self.logger.error("API key/secret not set for signed request.")
                raise ValueError("API key and secret must be set for signed requests.")

            # All signed parameters go into the query string for Binance Futures API (typically)
            # This includes business params, timestamp, recvWindow. Signature is then added.
            # If data_payload was intended for the body (e.g. for a non-signed JSON POST),
            # it should NOT be mixed into final_query_params for signing here.
            # For signed requests, Binance usually puts everything in the query string or x-www-form-urlencoded body.
            # We'll prepare final_query_params for signing.

            # Add business params from final_body_data to final_query_params if they were meant to be signed as query params
            # This part is tricky: what if final_body_data was meant for a JSON body (which isn't signed like this)?
            # For now, assume all signed params go into query. If a POST has a body, it's usually not signed or handled separately.
            # Let's assume for signed POSTs, all params are in query.
            if method.upper() in ["POST", "PUT", "DELETE"] and final_body_data and not final_query_params:
                 # If body data is present and no query params, assume body data is what needs signing (x-www-form-urlencoded)
                 self._sign_request_payload(final_body_data) # Signs final_body_data
                 # Convert to x-www-form-urlencoded string for requests library
                 body_to_send = urlencode(final_body_data) if final_body_data else None
                 current_headers['Content-Type'] = 'application/x-www-form-urlencoded'
                 final_query_params = {} # Ensure no query params if body is signed and sent
            else: # GET or POST/PUT/DELETE where all signed params are in query
                self._sign_request_payload(final_query_params) # Signs final_query_params
                body_to_send = None # No body for GET/DELETE, or signed POSTs with params in query
        else: # Not signed
            body_to_send = json.dumps(final_body_data) if final_body_data and method.upper() in ["POST", "PUT"] else None
            if body_to_send:
                current_headers['Content-Type'] = 'application/json;charset=utf-8'

        # Construct URL with query parameters if any
        query_string = urlencode(final_query_params) if final_query_params else ""
        request_url = f"{full_url}?{query_string}" if query_string else full_url

        self.logger.debug(f"Async Request: {method} {request_url}, Headers: {current_headers}, Body: {body_to_send}")

        try:
            fn = functools.partial(self.session.request, method, request_url, data=body_to_send, headers=current_headers, timeout=self.timeout)
            response = await loop.run_in_executor(None, fn)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            err_text = e.response.text if e.response else "No response text"
            self.logger.error(f"HTTP Error for {method} {request_url}: {e.response.status_code if e.response else 'N/A'} - {err_text}", exc_info=True)
            raise # Re-raise after logging
        except Exception as e:
            self.logger.error(f"General Error for {method} {request_url}: {e}", exc_info=True)
            raise

    # --- Refactored REST API Methods ---
    async def ping(self):
        return await self._make_request(method='GET', endpoint='/v1/ping')

    async def get_server_time(self):
        return await self._make_request(method='GET', endpoint='/v1/time')

    async def get_exchange_info(self):
        return await self._make_request(method='GET', endpoint='/v1/exchangeInfo', requires_api_key=True) # Typically needs API key

    async def get_klines(self, symbol: str, interval: str, startTime: int = None, endTime: int = None, limit: int = 500):
        params = {'symbol': symbol, 'interval': interval, 'startTime': startTime, 'endTime': endTime, 'limit': limit}
        return await self._make_request(method='GET', endpoint='/v1/klines', params=params)

    async def get_order_book(self, symbol: str, limit: int = 100):
        params = {'symbol': symbol, 'limit': limit}
        return await self._make_request(method='GET', endpoint='/v1/depth', params=params)

    async def get_recent_trades(self, symbol: str, limit: int = 500):
        params = {'symbol': symbol, 'limit': limit}
        return await self._make_request(method='GET', endpoint='/v1/trades', params=params)

    async def get_mark_price(self, symbol: str = None):
        params = {'symbol': symbol} if symbol else {}
        return await self._make_request(method='GET', endpoint='/v1/premiumIndex', params=params)

    async def place_order(self, symbol: str, side: str, ord_type: str, quantity: float = None,
                          price: float = None, timeInForce: str = None, reduceOnly: bool = None,
                          newClientOrderId: str = None, stopPrice: float = None, closePosition: bool = None,
                          workingType: str = None, positionSide: str = None, newOrderRespType: str = 'ACK'):
        params = {'symbol': symbol, 'side': side, 'type': ord_type, 'newOrderRespType': newOrderRespType}
        if quantity is not None: params['quantity'] = str(quantity) # Binance expects string for quantity
        if price is not None: params['price'] = str(price)
        if timeInForce is not None: params['timeInForce'] = timeInForce
        if reduceOnly is not None: params['reduceOnly'] = "true" if reduceOnly else "false"
        if newClientOrderId is not None: params['newClientOrderId'] = newClientOrderId
        if stopPrice is not None: params['stopPrice'] = str(stopPrice)
        if closePosition is not None: params['closePosition'] = "true" if closePosition else "false"
        if workingType is not None: params['workingType'] = workingType
        if positionSide is not None: params['positionSide'] = positionSide

        # For POST, all signed params go into the query string usually
        return await self._make_request(method='POST', endpoint='/v1/order', params=params, is_signed=True)

    async def get_order_status(self, symbol: str, orderId: int = None, origClientOrderId: str = None):
        if not orderId and not origClientOrderId: raise ValueError("Either orderId or origClientOrderId must be sent.")
        params = {'symbol': symbol, 'orderId': orderId, 'origClientOrderId': origClientOrderId}
        return await self._make_request(method='GET', endpoint='/v1/order', params=params, is_signed=True)

    async def cancel_order(self, symbol: str, orderId: int = None, origClientOrderId: str = None):
        if not orderId and not origClientOrderId: raise ValueError("Either orderId or origClientOrderId must be sent.")
        params = {'symbol': symbol, 'orderId': orderId, 'origClientOrderId': origClientOrderId}
        return await self._make_request(method='DELETE', endpoint='/v1/order', params=params, is_signed=True)

    async def get_open_orders(self, symbol: str = None):
        params = {'symbol': symbol} if symbol else {}
        return await self._make_request(method='GET', endpoint='/v1/openOrders', params=params, is_signed=True)

    async def get_all_orders(self, symbol: str, orderId: int = None, startTime: int = None, endTime: int = None, limit: int = 500):
        params = {'symbol': symbol, 'orderId': orderId, 'startTime': startTime, 'endTime': endTime, 'limit': limit}
        return await self._make_request(method='GET', endpoint='/v1/allOrders', params=params, is_signed=True)

    async def get_account_balance(self):
        return await self._make_request(method='GET', endpoint='/v2/balance', params={}, is_signed=True)

    async def get_position_information(self, symbol: str = None):
        params = {'symbol': symbol} if symbol else {}
        return await self._make_request(method='GET', endpoint='/v2/positionRisk', params=params, is_signed=True)

    # --- Refactored User Data Stream Listen Key Methods ---
    async def _get_listen_key(self) -> Optional[str]:
        self.logger.info("Attempting to get new listen key for user data stream (async).")
        try:
            # POST /fapi/v1/listenKey requires API Key in header, no body/query params for signature.
            # The _make_request with is_signed=False but requires_api_key=True handles this.
            response = await self._make_request('POST', '/fapi/v1/listenKey', requires_api_key=True)
            self.user_data_listen_key = response.get('listenKey')
            if self.user_data_listen_key:
                self.logger.info(f"Obtained listen key (async): {self.user_data_listen_key[:10]}...")
                return self.user_data_listen_key
            else:
                self.logger.error(f"Failed to get listen key from response (async): {response}")
                return None
        except Exception as e:
            self.logger.error(f"Error getting listen key (async): {e}", exc_info=True)
            return None

    async def _keep_listen_key_alive(self) -> bool:
        if not self.user_data_listen_key:
            self.logger.warning("No listen key available to keep alive (async).")
            return False
        self.logger.info(f"Attempting to keep listen key alive (async): {self.user_data_listen_key[:10]}...")
        try:
            # PUT /fapi/v1/listenKey - requires API key, no body/query.
            await self._make_request('PUT', '/fapi/v1/listenKey', requires_api_key=True) # No params needed beyond what _make_request handles
            self.logger.info(f"Listen key kept alive successfully (async).")
            return True # HTTPError would be raised by _make_request on failure
        except Exception as e:
            self.logger.error(f"Error keeping listen key alive (async): {e}", exc_info=True)
            return False

    async def _close_listen_key(self) -> bool:
        if not self.user_data_listen_key:
            self.logger.info("No listen key to close (async).")
            return False
        self.logger.info(f"Attempting to close listen key (async): {self.user_data_listen_key[:10]}...")
        try:
            # DELETE /fapi/v1/listenKey - requires API key, no body/query.
            await self._make_request('DELETE', '/fapi/v1/listenKey', requires_api_key=True)
            self.logger.info(f"Listen key closed successfully (async).")
            return True
        except Exception as e:
            self.logger.error(f"Error closing listen key (async): {e}", exc_info=True)
            return False

    # --- WebSocket Methods (largely unchanged, but listen key methods they call are now async) ---
    # ... (start_market_stream, stop_market_stream, _get_next_stream_id remain mostly the same)
    # ... (_listen_key_refresher_loop, start_user_stream, stop_user_stream need to call await on async listen key methods)

    def _listen_key_refresher_loop(self): # This runs in a sync thread, calls async method
        self.logger.info("Listen key refresher loop started.")
        loop = asyncio.new_event_loop() # Create a new event loop for this thread
        asyncio.set_event_loop(loop)

        async def keep_alive_task():
            if self.user_data_control_flag.get('keep_running') and self.user_data_listen_key:
                if not await self._keep_listen_key_alive(): # Call async version
                    self.logger.warning("Failed to keep listen key alive in refresher loop (async).")

        while self.user_data_control_flag.get('keep_running') and self.user_data_listen_key:
            sleep_duration = self.listen_key_refresh_interval
            # Sleep in short intervals to check keep_running flag
            for _ in range(int(sleep_duration)): # Check every second
                if not self.user_data_control_flag.get('keep_running'):
                    break
                time.sleep(1)

            if self.user_data_control_flag.get('keep_running') and self.user_data_listen_key:
                try:
                    loop.run_until_complete(keep_alive_task())
                except Exception as e:
                    self.logger.error(f"Exception in listen key refresher keep_alive_task: {e}", exc_info=True)
            else:
                break
        loop.close()
        self.logger.info("Listen key refresher loop stopped.")


    def start_user_stream(self, callback: Callable) -> bool: # This is sync, calls async methods
        if self.user_data_control_flag.get('keep_running'):
            self.logger.warning("User data stream is already running.")
            return False

        # Run _get_listen_key in a temporary event loop for this sync method
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        listen_key_obtained = loop.run_until_complete(self._get_listen_key())
        # loop.close() # Don't close if other async things might use it, or manage loops carefully.
                       # The _user_ws_handler will run its own loop via asyncio.run in its thread.

        if not listen_key_obtained or not self.user_data_listen_key:
            self.logger.error("Failed to start user stream: Could not obtain listen key (async).")
            return False

        self.user_data_control_flag['keep_running'] = True

        async def _user_ws_handler(): # This is the async part for the WebSocket
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
                                callback(data) # This callback must be thread-safe or handle its own threading
                                self.logger.debug(f"User WS Recv: {message[:200]}")
                            except asyncio.TimeoutError: continue
                            except websockets.exceptions.ConnectionClosed:
                                self.logger.warning("User WS ConnectionClosed. Will reconnect if keep_running.")
                                break
                            except Exception as e_recv:
                                self.logger.error(f"Error in User WS message processing: {e_recv}", exc_info=True)
                                await asyncio.sleep(1)
                        if not self.user_data_control_flag.get('keep_running'): break
                except Exception as e_ws_connect:
                    self.logger.error(f"Error connecting User WS: {e_ws_connect}", exc_info=True)
                if self.user_data_control_flag.get('keep_running'):
                    self.logger.info("Attempting User WS reconnect in 5s...")
                    await asyncio.sleep(5)
                else: break
            self.user_data_ws_client = None
            self.logger.info("User data stream WebSocket handler finished.")

        def _run_user_ws_handler_in_thread():
            asyncio.run(_user_ws_handler())

        self.user_data_thread = threading.Thread(target=_run_user_ws_handler_in_thread, daemon=True, name="UserDataThread")
        self.user_data_thread.start()

        self.listen_key_refresher_thread = threading.Thread(target=self._listen_key_refresher_loop, daemon=True, name="ListenKeyRefresherThread")
        self.listen_key_refresher_thread.start()
        self.logger.info("User data stream services started.")
        return True

    def stop_user_stream(self): # This is sync, calls async methods
        if self.user_data_control_flag.get('keep_running'):
            self.logger.info("Attempting to stop user data stream services...")
            self.user_data_control_flag['keep_running'] = False

            if self.user_data_thread and self.user_data_thread.is_alive():
                self.user_data_thread.join(timeout=5.0)
            if self.listen_key_refresher_thread and self.listen_key_refresher_thread.is_alive():
                self.listen_key_refresher_thread.join(timeout=self.listen_key_refresh_interval + 5) # Wait for its loop cycle + buffer

            if self.user_data_listen_key:
                loop = asyncio.new_event_loop() # Or get existing if main thread is async
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(self._close_listen_key())
                except Exception as e:
                    self.logger.error(f"Exception during async _close_listen_key in stop_user_stream: {e}")
                finally:
                    loop.close()

            self.user_data_listen_key = None
            self.logger.info("User data stream services stopped.")
        else:
            self.logger.info("User data stream is not currently running.")

    # --- Market Data WebSocket Methods (mostly unchanged, ensure callbacks are handled if they become async) ---
    def _get_next_stream_id(self) -> str:
        with self._ws_lock: self._ws_stream_id_counter += 1
        return f"market_ws_{self._ws_stream_id_counter}"

    def start_market_stream(self, stream_names: List[str], callback: Callable) -> str:
        if not stream_names: raise ValueError("stream_names cannot be empty.")
        stream_id = self._get_next_stream_id()
        path = f"/ws/{stream_names[0].lower()}" if len(stream_names) == 1 else f"/stream?streams={'/'.join([s.lower() for s in stream_names])}"
        full_ws_url = f"{self.ws_base_url}{path}"
        control = {'keep_running': True}
        self.active_market_websockets[stream_id] = {'ws_client': None, 'control': control, 'thread': None, 'url': full_ws_url}

        async def _ws_handler(): # This is fine as is, runs in its own thread with its own loop via asyncio.run
            self.logger.info(f"Market WS handler started for ID {stream_id} ({full_ws_url})")
            # ... (rest of _ws_handler is okay, uses websockets.connect which is async)
            while control['keep_running']:
                try:
                    async with websockets.connect(full_ws_url, ping_interval=60, ping_timeout=30) as ws: # Added ping_interval
                        self.active_market_websockets[stream_id]['ws_client'] = ws
                        self.logger.info(f"Market WebSocket connected for stream ID {stream_id}.")
                        while control['keep_running']:
                            try:
                                message = await asyncio.wait_for(ws.recv(), timeout=1.0) # Timeout to check keep_running
                                data = json.loads(message)
                                callback(data) # This callback must be thread-safe
                                self.logger.debug(f"Market WS Recv ({stream_id}): {message[:200]}...")
                            except asyncio.TimeoutError: continue
                            except websockets.exceptions.ConnectionClosed:
                                self.logger.warning(f"Market WS ConnectionClosed for ID {stream_id}. Will reconnect if keep_running.")
                                break
                            except Exception as e_inner:
                                self.logger.error(f"Error in Market WS handler ({stream_id}) inner loop: {e_inner}", exc_info=True)
                                await asyncio.sleep(1)
                        if not control['keep_running']: break
                except Exception as e_outer:
                    self.logger.error(f"Error connecting Market WS ({stream_id}): {e_outer}", exc_info=True)
                if control['keep_running']:
                    self.logger.info(f"Attempting Market WS reconnect for ID {stream_id} in 5s...")
                    await asyncio.sleep(5)
                else: break
            self.logger.info(f"Market WebSocket handler stopped for stream ID {stream_id}.")


        def _run_ws_handler_in_thread(): asyncio.run(_ws_handler())
        thread = threading.Thread(target=_run_ws_handler_in_thread, daemon=True, name=f"MarketWsThread-{stream_id}")
        self.active_market_websockets[stream_id]['thread'] = thread
        thread.start()
        self.logger.info(f"Market stream {stream_id} started for {', '.join(stream_names)}")
        return stream_id

    def stop_market_stream(self, stream_id: str):
        if stream_id in self.active_market_websockets:
            self.logger.info(f"Stopping market stream {stream_id}...")
            control = self.active_market_websockets[stream_id]['control']
            control['keep_running'] = False
            thread = self.active_market_websockets[stream_id].get('thread')
            if thread and thread.is_alive(): thread.join(timeout=10)
            del self.active_market_websockets[stream_id]
            self.logger.info(f"Market stream {stream_id} stopped.")
        else: self.logger.warning(f"Attempted to stop non-existent market stream ID: {stream_id}")


if __name__ == '__main__':
    import os
    from dotenv import load_dotenv

    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(module)s:%(lineno)d - %(funcName)s - %(message)s')
    logger_main = logging.getLogger('algo_trader_bot')

    dotenv_path = os.path.join(os.path.dirname(__file__), '../../.env')
    load_dotenv(dotenv_path=dotenv_path)
    API_KEY = os.getenv("BINANCE_TESTNET_API_KEY")
    API_SECRET = os.getenv("BINANCE_TESTNET_API_SECRET")

    if not (API_KEY and API_SECRET and API_KEY != "YOUR_TESTNET_API_KEY"):
        logger_main.error("API_KEY/SECRET must be set in .env and not be placeholders.")
        exit()

    connector = BinanceAPI(api_key=API_KEY, api_secret=API_SECRET, testnet=True)

    async def main_test():
        logger_main.info("--- Testing Async REST Endpoints ---")
        try:
            server_time = await connector.get_server_time()
            logger_main.info(f"Async Server Time: {server_time}")

            # Test a signed endpoint
            # balance_info = await connector.get_account_balance()
            # logger_main.info(f"Async Account Balance (USDT): {[b for b in balance_info if b.get('asset') == 'USDT']}")

            # Test placing an order (example, be careful)
            # try:
            #     order_params = {
            #         'symbol': "BTCUSDT", 'side': "BUY", 'ord_type': "LIMIT",
            #         'quantity': 0.001, 'price': 20000, 'timeInForce': "GTC"
            #     }
            #     # placed_order = await connector.place_order(**order_params)
            #     # logger_main.info(f"Async Place Order Response: {placed_order}")
            #     # if placed_order and placed_order.get('orderId'):
            #     #     cancelled_order = await connector.cancel_order("BTCUSDT", orderId=placed_order.get('orderId'))
            #     #     logger_main.info(f"Async Cancel Order Response: {cancelled_order}")
            #     logger_main.info("Order placement/cancellation commented out in main_test for safety.")
            # except Exception as e_order:
            #     logger_main.error(f"Error during async order test: {e_order}")

        except Exception as e:
            logger_main.error(f"Error in async REST test: {e}", exc_info=True)

        # Test User Data Stream (which now uses async listen key methods internally)
        logger_main.info("\n--- Testing User Data Stream (with async listen key calls) ---")
        user_stream_started_async_test = False
        def user_cb(data): logger_main.info(f"User CB (async test): {str(data)[:200]}")

        try:
            # start_user_stream is sync but calls async _get_listen_key
            user_stream_started_async_test = connector.start_user_stream(callback=user_cb)
            if user_stream_started_async_test:
                logger_main.info("User stream started (async test). Waiting 20s...")
                time.sleep(20) # Keep main thread alive
            else:
                logger_main.error("User stream failed to start (async test).")
        except Exception as e:
            logger_main.error(f"Error in user stream test (async): {e}", exc_info=True)
        finally:
            if user_stream_started_async_test:
                logger_main.info("Stopping user stream (async test)...")
                connector.stop_user_stream() # This is sync but calls async _close_listen_key
            time.sleep(2)
            logger_main.info("User stream test (async) finished.")

    asyncio.run(main_test())
```
