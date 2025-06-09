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

        self.session = requests.Session()
        self.logger = logging.getLogger('algo_trader_bot.BinanceAPI') # More specific logger name

        self.active_market_websockets: Dict[str, Dict] = {}
        self._ws_stream_id_counter = 0
        self._ws_lock = threading.Lock()

        self.user_data_listen_key: Optional[str] = None
        self.user_data_ws_client: Optional[websockets.WebSocketClientProtocol] = None
        self.user_data_thread: Optional[threading.Thread] = None
        self.user_data_control_flag = {'keep_running': False}
        self.listen_key_refresh_interval = 30 * 60
        self.listen_key_refresher_thread: Optional[threading.Thread] = None

        self.recv_window = 60000
        self.timeout = 10
        self.http_headers = {'Accept': 'application/json'} # Content-Type set dynamically

    def _generate_signature(self, data: str) -> str:
        if not self.api_secret:
            self.logger.error("API secret is not set for signature generation.")
            raise ValueError("API secret is not set for signature generation.")
        return hmac.new(self.api_secret.encode('utf-8'), data.encode('utf-8'), hashlib.sha256).hexdigest()

    def _prepare_params(self, params: dict) -> dict:
        return {k: v for k, v in params.items() if v is not None}

    def _get_headers(self, requires_api_key: bool = False, content_type: Optional[str] = None) -> dict:
        headers = self.http_headers.copy()
        if requires_api_key:
            if not self.api_key:
                self.logger.error("API key required but not set for endpoint.")
                raise ValueError("API key is required for this endpoint but not set.")
            headers['X-MBX-APIKEY'] = self.api_key
        if content_type:
            headers['Content-Type'] = content_type
        return headers

    def _sign_request_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self.api_key or not self.api_secret:
            raise ValueError("API key and secret must be set for signing requests.")
        payload['timestamp'] = int(time.time() * 1000)
        payload['recvWindow'] = self.recv_window

        # Remove signature if present (e.g. from a previous attempt) before creating query string
        payload.pop('signature', None)
        query_string_to_sign = urlencode(self._prepare_params(payload.copy())) # Sign only non-None params
        payload['signature'] = self._generate_signature(query_string_to_sign)
        return payload

    async def _make_request(self, method: str, endpoint: str,
                            params: Optional[Dict[str, Any]] = None, # For query string
                            data_payload: Optional[Dict[str, Any]] = None, # For request body
                            is_signed: bool = False,
                            requires_api_key: bool = False):

        loop = asyncio.get_event_loop()

        final_query_params = self._prepare_params(params.copy() if params else {})
        final_body_params = self._prepare_params(data_payload.copy() if data_payload else {}) # For body if needed

        content_type_header = None
        body_to_send: Optional[str] = None

        if is_signed:
            if not self.api_key or not self.api_secret:
                self.logger.error("API key/secret not set for signed request."); raise ValueError("API key/secret missing.")

            # For Binance Futures, all signed parameters (including business ones) usually go in the query string.
            # If a method like POST also has a specific non-signed JSON body, that's a separate case.
            # Here, we assume all params in `final_query_params` are signed for GET/DELETE.
            # For POST/PUT, if `final_body_params` are provided, they might be signed as x-www-form-urlencoded.
            # However, common practice for Binance is to put all signed params in the query string for POST/PUT too.

            if method.upper() in ['GET', 'DELETE']:
                self._sign_request_payload(final_query_params) # Signs query params
            elif method.upper() in ['POST', 'PUT']:
                # If there's data payload, assume it's x-www-form-urlencoded and needs signing
                # If no data_payload, but final_query_params exist, those are signed and go in URL.
                if final_body_params: # Assume these are form data to be signed
                    self._sign_request_payload(final_body_params)
                    body_to_send = urlencode(final_body_params)
                    content_type_header = 'application/x-www-form-urlencoded'
                    final_query_params = {} # Clear query params if body is signed form data
                elif final_query_params : # No body, but query params exist for POST/PUT, sign them
                     self._sign_request_payload(final_query_params)
                # Else (no query, no body, but signed POST, e.g. listenKey) -> empty signature base string
                else: # No params, no data, but signed (e.g. POST listenKey)
                     # An empty dict for _sign_request_payload will add timestamp/recvWindow for signature
                    self._sign_request_payload(final_query_params)


        elif method.upper() in ["POST", "PUT"] and final_body_params: # Not signed, but has body data
            body_to_send = json.dumps(final_body_params)
            content_type_header = 'application/json;charset=utf-8'

        current_headers = self._get_headers(requires_api_key=(is_signed or requires_api_key), content_type=content_type_header)

        query_string = urlencode(final_query_params) if final_query_params else ""
        request_url = f"{self.base_url}{endpoint}"
        if query_string: request_url += f"?{query_string}"

        self.logger.debug(f"Async Request: {method} {request_url}, Headers: {current_headers}, Body: {str(body_to_send)[:200] if body_to_send else None}")

        try:
            fn = functools.partial(self.session.request, method, request_url, data=body_to_send, headers=current_headers, timeout=self.timeout)
            response = await loop.run_in_executor(None, fn)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            err_text = e.response.text if e.response else "No response text"
            self.logger.error(f"HTTP Error for {method} {request_url}: {e.response.status_code if e.response else 'N/A'} - {err_text}", exc_info=False) # Reduced exc_info noise
            raise
        except Exception as e:
            self.logger.error(f"General Error for {method} {request_url}: {e}", exc_info=True)
            raise

    # --- Refactored REST API Methods ---
    async def ping(self): return await self._make_request(method='GET', endpoint='/v1/ping')
    async def get_server_time(self): return await self._make_request(method='GET', endpoint='/v1/time')
    async def get_exchange_info(self): return await self._make_request(method='GET', endpoint='/v1/exchangeInfo', requires_api_key=False) # Public

    async def get_klines(self, symbol: str, interval: str, startTime: int = None, endTime: int = None, limit: int = 500):
        return await self._make_request('GET', '/v1/klines', params={'symbol':symbol,'interval':interval,'startTime':startTime,'endTime':endTime,'limit':limit})
    async def get_order_book(self, symbol: str, limit: int = 100):
        return await self._make_request('GET', '/v1/depth', params={'symbol':symbol,'limit':limit})
    async def get_recent_trades(self, symbol: str, limit: int = 500): # Public trades
        return await self._make_request('GET', '/v1/trades', params={'symbol':symbol,'limit':limit})
    async def get_mark_price(self, symbol: str = None):
        return await self._make_request('GET', '/v1/premiumIndex', params={'symbol':symbol} if symbol else {})

    async def place_order(self, symbol: str, side: str, ord_type: str, quantity: Optional[float] = None, price: Optional[float] = None,
                        timeInForce: Optional[str] = None, reduceOnly: Optional[bool] = None, newClientOrderId: Optional[str] = None,
                        stopPrice: Optional[float] = None, closePosition: Optional[bool] = None, workingType: Optional[str] = None,
                        positionSide: Optional[str] = None, newOrderRespType: str = 'ACK'):
        params = {'symbol':symbol,'side':side,'type':ord_type,'newOrderRespType':newOrderRespType}
        if quantity is not None: params['quantity'] = str(quantity)
        if price is not None: params['price'] = str(price)
        if timeInForce: params['timeInForce'] = timeInForce
        if reduceOnly is not None: params['reduceOnly'] = "true" if reduceOnly else "false"
        if newClientOrderId: params['newClientOrderId'] = newClientOrderId
        if stopPrice is not None: params['stopPrice'] = str(stopPrice)
        if closePosition is not None: params['closePosition'] = "true" if closePosition else "false"
        if workingType: params['workingType'] = workingType
        if positionSide: params['positionSide'] = positionSide
        # For POST, all signed params are typically in the query string for Binance Futures
        return await self._make_request('POST', '/v1/order', params=params, is_signed=True)

    async def get_order_status(self, symbol: str, orderId: Optional[int] = None, origClientOrderId: Optional[str] = None):
        if not orderId and not origClientOrderId: raise ValueError("Either orderId or origClientOrderId required.")
        return await self._make_request('GET', '/v1/order', params={'symbol':symbol,'orderId':orderId,'origClientOrderId':origClientOrderId}, is_signed=True)

    async def cancel_order(self, symbol: str, orderId: Optional[int] = None, origClientOrderId: Optional[str] = None):
        if not orderId and not origClientOrderId: raise ValueError("Either orderId or origClientOrderId required.")
        return await self._make_request('DELETE', '/v1/order', params={'symbol':symbol,'orderId':orderId,'origClientOrderId':origClientOrderId}, is_signed=True)

    async def get_open_orders(self, symbol: Optional[str] = None):
        return await self._make_request('GET', '/v1/openOrders', params={'symbol':symbol} if symbol else {}, is_signed=True)

    async def get_all_orders(self, symbol: str, orderId: Optional[int] = None, startTime: Optional[int] = None, endTime: Optional[int] = None, limit: int = 500):
        return await self._make_request('GET', '/v1/allOrders', params={'symbol':symbol,'orderId':orderId,'startTime':startTime,'endTime':endTime,'limit':limit}, is_signed=True)

    async def get_my_trades(self, symbol: str, startTime: Optional[int] = None, endTime: Optional[int] = None, fromId: Optional[int] = None, limit: Optional[int] = 500):
        """ Gets trades for a specific account and symbol. """
        params = {'symbol': symbol, 'startTime': startTime, 'endTime': endTime, 'fromId': fromId, 'limit': limit}
        return await self._make_request(method='GET', endpoint='/fapi/v1/userTrades', params=params, is_signed=True)

    async def get_account_balance(self):
        return await self._make_request('GET', '/v2/balance', params={}, is_signed=True)
    async def get_position_information(self, symbol: Optional[str] = None):
        return await self._make_request('GET', '/v2/positionRisk', params={'symbol':symbol} if symbol else {}, is_signed=True)

    # --- User Data Stream Listen Key Methods (now async) ---
    async def _get_listen_key(self) -> Optional[str]:
        self.logger.info("Async: Getting listen key...");_data=None
        try: _data = await self._make_request('POST', '/fapi/v1/listenKey', requires_api_key=True) # No params, just API key header
        except Exception as e: self.logger.error(f"Async _get_listen_key error: {e}"); return None
        self.user_data_listen_key = _data.get('listenKey') if _data else None
        if self.user_data_listen_key: self.logger.info(f"Async Listen Key obtained: {self.user_data_listen_key[:10]}...")
        else: self.logger.error(f"Async Failed to get listen key: {_data}")
        return self.user_data_listen_key

    async def _keep_listen_key_alive(self) -> bool:
        if not self.user_data_listen_key: self.logger.warning("Async: No listen key to keep alive."); return False
        self.logger.info(f"Async: Keeping listen key alive: {self.user_data_listen_key[:10]}...")
        try: await self._make_request('PUT', '/fapi/v1/listenKey', requires_api_key=True); self.logger.info("Async Listen key kept alive."); return True
        except Exception as e: self.logger.error(f"Async Error keeping listen key alive: {e}"); return False

    async def _close_listen_key(self) -> bool:
        if not self.user_data_listen_key: self.logger.info("Async: No listen key to close."); return False
        self.logger.info(f"Async: Closing listen key: {self.user_data_listen_key[:10]}...")
        try: await self._make_request('DELETE', '/fapi/v1/listenKey', requires_api_key=True); self.logger.info("Async Listen key closed."); return True
        except Exception as e: self.logger.error(f"Async Error closing listen key: {e}"); return False

    # ... (WebSocket methods: _listen_key_refresher_loop, start_user_stream, stop_user_stream need careful review for sync/async calls) ...
    # ... (start_market_stream, stop_market_stream are okay as they run their own async loops in threads) ...

    # The methods below run in their own threads but call async methods.
    # This requires an event loop to be available in that thread.
    def _listen_key_refresher_loop(self):
        self.logger.info("Listen key refresher loop started.")
        try: loop = asyncio.get_running_loop()
        except RuntimeError: loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)

        async def keep_alive_task(): # wrapper
            if not await self._keep_listen_key_alive():
                self.logger.warning("Failed to keep listen key alive (async). Attempting to get new key.")
                if await self._get_listen_key(): self.logger.info("New listen key obtained in refresher.")
                else: self.logger.error("Failed to get new listen key in refresher. User stream may fail.")

        while self.user_data_control_flag.get('keep_running'):
            for _ in range(self.listen_key_refresh_interval // 60): # Check every minute
                if not self.user_data_control_flag.get('keep_running'): break
                time.sleep(60)
            if not self.user_data_control_flag.get('keep_running'): break
            self.logger.debug("Refresher: Time to refresh listen key.")
            loop.run_until_complete(keep_alive_task())
        self.logger.info("Listen key refresher loop stopped.")


    def start_user_stream(self, callback: Callable) -> bool:
        if self.user_data_control_flag.get('keep_running'): self.logger.warning("User stream already running."); return False

        try: loop = asyncio.get_running_loop()
        except RuntimeError: loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)

        if not loop.run_until_complete(self._get_listen_key()):
            self.logger.error("Failed to start user stream: No listen key."); return False

        self.user_data_control_flag['keep_running'] = True
        # ... (rest of _user_ws_handler and thread setup remains the same)
        async def _user_ws_handler():
            ws_url = f"{self.ws_base_url}/ws/{self.user_data_listen_key}"
            self.logger.info(f"User WS handler started for URL: {ws_url}")
            while self.user_data_control_flag.get('keep_running'):
                try:
                    async with websockets.connect(ws_url, ping_interval=60, ping_timeout=30) as ws:
                        self.user_data_ws_client = ws
                        self.logger.info("User WS connected.")
                        while self.user_data_control_flag.get('keep_running'):
                            try:
                                message = await asyncio.wait_for(ws.recv(), timeout=1.0)
                                data = json.loads(message); callback(data)
                            except asyncio.TimeoutError: continue
                            except websockets.exceptions.ConnectionClosed: self.logger.warning("User WS ConnectionClosed."); break
                            except Exception as e_recv: self.logger.error(f"Error in User WS recv: {e_recv}", exc_info=True); await asyncio.sleep(1)
                        if not self.user_data_control_flag.get('keep_running'): break
                except Exception as e_conn: self.logger.error(f"Error connecting User WS: {e_conn}", exc_info=True)
                if self.user_data_control_flag.get('keep_running'): await asyncio.sleep(5) # Reconnect delay
                else: break
            self.user_data_ws_client = None; self.logger.info("User WS handler finished.")
        def _run_in_thread(): asyncio.run(_user_ws_handler())
        self.user_data_thread = threading.Thread(target=_run_in_thread, daemon=True, name="UserDataThread"); self.user_data_thread.start()
        self.listen_key_refresher_thread = threading.Thread(target=self._listen_key_refresher_loop, daemon=True, name="ListenKeyRefresher"); self.listen_key_refresher_thread.start()
        self.logger.info("User data stream services started."); return True

    def stop_user_stream(self):
        if not self.user_data_control_flag.get('keep_running', False): self.logger.info("User stream not running."); return
        self.logger.info("Stopping user data stream services...")
        self.user_data_control_flag['keep_running'] = False
        if self.user_data_thread and self.user_data_thread.is_alive(): self.user_data_thread.join(timeout=5.0)
        if self.listen_key_refresher_thread and self.listen_key_refresher_thread.is_alive(): self.listen_key_refresher_thread.join(timeout=5.0) # Refresher checks flag often
        if self.user_data_listen_key:
            try: loop = asyncio.get_running_loop()
            except RuntimeError: loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
            try: loop.run_until_complete(self._close_listen_key())
            except Exception as e: self.logger.error(f"Exception closing listen key in stop: {e}")
            # loop.close() # Careful with closing shared/main loops
        self.user_data_listen_key = None; self.logger.info("User data stream services stopped.")

    # Market stream methods remain the same as they manage their own loops in threads
    def _get_next_stream_id(self) -> str: # ... (same)
        with self._ws_lock: self._ws_stream_id_counter += 1
        return f"market_ws_{self._ws_stream_id_counter}"
    def start_market_stream(self, stream_names: List[str], callback: Callable) -> str: # ... (same)
        if not stream_names: raise ValueError("stream_names cannot be empty.")
        stream_id = self._get_next_stream_id()
        path = f"/ws/{stream_names[0].lower()}" if len(stream_names) == 1 else f"/stream?streams={'/'.join([s.lower() for s in stream_names])}"
        full_ws_url = f"{self.ws_base_url}{path}"
        control = {'keep_running': True}
        self.active_market_websockets[stream_id] = {'ws_client': None, 'control': control, 'thread': None, 'url': full_ws_url}
        async def _ws_handler():
            self.logger.info(f"Market WS handler started for ID {stream_id} ({full_ws_url})")
            while control['keep_running']:
                try:
                    async with websockets.connect(full_ws_url, ping_interval=60, ping_timeout=30) as ws:
                        self.active_market_websockets[stream_id]['ws_client'] = ws
                        self.logger.info(f"Market WebSocket connected for stream ID {stream_id}.")
                        while control['keep_running']:
                            try:
                                message = await asyncio.wait_for(ws.recv(), timeout=1.0)
                                data = json.loads(message); callback(data)
                            except asyncio.TimeoutError: continue
                            except websockets.exceptions.ConnectionClosed: self.logger.warning(f"Market WS ConnectionClosed for ID {stream_id}."); break
                            except Exception as e_inner: self.logger.error(f"Error in Market WS handler ({stream_id}) inner loop: {e_inner}", exc_info=True); await asyncio.sleep(1)
                        if not control['keep_running']: break
                except Exception as e_outer: self.logger.error(f"Error connecting Market WS ({stream_id}): {e_outer}", exc_info=True)
                if control['keep_running']: await asyncio.sleep(5)
                else: break
            self.logger.info(f"Market WebSocket handler stopped for stream ID {stream_id}.")
        def _run_ws_handler_in_thread(): asyncio.run(_ws_handler())
        thread = threading.Thread(target=_run_ws_handler_in_thread, daemon=True, name=f"MarketWsThread-{stream_id}")
        self.active_market_websockets[stream_id]['thread'] = thread; thread.start()
        self.logger.info(f"Market stream {stream_id} started for {', '.join(stream_names)}")
        return stream_id
    def stop_market_stream(self, stream_id: str): # ... (same)
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
    # ... (main test block from previous step, needs to be async now) ...
    pass # Needs to be updated for async

```
