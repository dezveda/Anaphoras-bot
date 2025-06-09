import logging
import time
import uuid # For more unique clientOrderIds
from typing import Dict, Optional, Callable

try:
    from bot.connectors.binance_connector import BinanceAPI
    from bot.core.data_fetcher import MarketDataProvider # Will be used later for price checks etc.
except ImportError:
    # Fallbacks for local testing
    from connectors.binance_connector import BinanceAPI
    from core.data_fetcher import MarketDataProvider


class OrderManager:
    def __init__(self,
                 binance_connector: BinanceAPI,
                 market_data_provider: MarketDataProvider): # market_data_provider might be used later
        self.binance_connector = binance_connector
        self.market_data_provider = market_data_provider # Stored for future use
        self.logger = logging.getLogger('algo_trader_bot')

        # Stores active orders placed by this manager. Key: clientOrderId, Value: order details from Binance
        self.active_orders: Dict[str, Dict] = {}
        # self.risk_manager = risk_manager # To be added later

    def _generate_client_order_id(self, strategy_id: str = "default") -> str:
        """
        Generates a unique client order ID.
        Binance Futures clientOrderId max length is 36.
        Format: <strategy_id_prefix (max 8 chars)>_<timestamp_ms (13 chars)>_<uuid_suffix (variable)>
        Example: manual_1625097600000_abc123
        """
        prefix = strategy_id[:8] # Ensure prefix is not too long
        timestamp_ms = int(time.time() * 1000)
        # UUID generates 36 chars, too long with prefix and timestamp. Take a part of it.
        # Generate a random suffix to ensure uniqueness even if called in the same millisecond.
        random_suffix = uuid.uuid4().hex[:6] # 6 random hex characters

        client_order_id = f"{prefix}_{timestamp_ms}_{random_suffix}"
        return client_order_id[:32] # Ensure it's well within any potential limits (Binance actual limit might be higher for futures)
                                    # Officially for fapi, "A unique id among open orders. Automatically generated if not sent."
                                    # "Restrictions: Max 36 characters. Does not support special characters ^, _, ?, ! etc."
                                    # The above generator is fine, but let's ensure we don't use restricted chars.
                                    # Using uuid.hex is safe. Let's adjust to fit better.
                                    # Max length for clientOrderId is 36 according to some docs, others say it's for user an unique string.
                                    # Let's use a shorter version: <strategy_id>_t<timestamp_ms>
        prefix = strategy_id.replace("_", "")[:10] # Clean and shorten strategy_id
        client_order_id = f"{prefix}t{timestamp_ms}"
        return client_order_id[:36] # Ensure within 36 chars


    def place_new_order(self, symbol: str, side: str, ord_type: str, quantity: float,
                        price: Optional[float] = None, timeInForce: Optional[str] = None,
                        reduceOnly: Optional[bool] = None, stopPrice: Optional[float] = None,
                        positionSide: Optional[str] = None, strategy_id: str = "manual",
                        newOrderRespType: str = 'ACK') -> Optional[Dict]:
        """
        Places a new order.
        (Later: Will include risk checks)
        """
        client_order_id = self._generate_client_order_id(strategy_id)
        self.logger.info(f"Attempting to place new order: ClientOrderID={client_order_id}, Symbol={symbol}, Side={side}, Type={ord_type}, Qty={quantity}, Price={price}, PosSide={positionSide}")

        # TODO: Later - Call RiskManager.check_order_validity() before placing
        # if not self.risk_manager.check_order_validity(...):
        #     self.logger.warning(f"Order rejected by RiskManager: {client_order_id}")
        #     return None

        try:
            order_response = self.binance_connector.place_order(
                symbol=symbol,
                side=side,
                ord_type=ord_type,
                quantity=quantity,
                price=price,
                timeInForce=timeInForce,
                reduceOnly=reduceOnly,
                newClientOrderId=client_order_id,
                stopPrice=stopPrice,
                positionSide=positionSide,
                newOrderRespType=newOrderRespType # ACK, RESULT, FULL
            )

            if order_response:
                self.logger.info(f"Order placed successfully (API Response): ClientOrderID={client_order_id}, OrderID={order_response.get('orderId')}, Status={order_response.get('status')}")
                # Store basic info. More details will come via WebSocket if RESULT/FULL or via handle_order_update
                self.active_orders[client_order_id] = order_response
                # If newOrderRespType is RESULT or FULL, it might already contain final status.
                if order_response.get('status') in ['FILLED', 'CANCELED', 'EXPIRED', 'REJECTED']:
                    self.logger.info(f"Order {client_order_id} is already in a final state: {order_response.get('status')}")
                    # Optionally move from active_orders or handle immediately
            else: # Should not happen if _make_request raises an exception
                self.logger.error(f"Order placement failed for ClientOrderID={client_order_id}. No response from connector.")
                return None
            return order_response
        except Exception as e:
            self.logger.error(f"Exception during order placement for ClientOrderID={client_order_id}: {e}", exc_info=True)
            return None

    def cancel_existing_order(self, symbol: str, orderId: Optional[int] = None, origClientOrderId: Optional[str] = None) -> Optional[Dict]:
        """Cancels an existing order."""
        log_id = orderId if orderId else origClientOrderId
        self.logger.info(f"Attempting to cancel order: ID={log_id}, Symbol={symbol}")

        if not orderId and not origClientOrderId:
            self.logger.error("Cannot cancel order: Either orderId or origClientOrderId must be provided.")
            return None

        try:
            cancel_response = self.binance_connector.cancel_order(
                symbol=symbol,
                orderId=orderId,
                origClientOrderId=origClientOrderId
            )
            if cancel_response:
                self.logger.info(f"Order cancel request successful (API Response): ID={log_id}, Status={cancel_response.get('status')}")
                # Update local cache. The actual removal/update might be better handled by ORDER_TRADE_UPDATE event.
                # For now, assume direct update based on response.
                client_oid_to_update = cancel_response.get('clientOrderId', origClientOrderId)
                if client_oid_to_update and client_oid_to_update in self.active_orders:
                    self.active_orders[client_oid_to_update].update(cancel_response)
                    if cancel_response.get('status') == 'CANCELED':
                        self.logger.info(f"Order {client_oid_to_update} confirmed CANCELED and updated in active_orders.")
                        # Optionally move to a 'processed_orders' list here or upon WebSocket confirmation.
                elif orderId and any(o.get('orderId') == orderId for o in self.active_orders.values()):
                    # Find by orderId if clientOrderId not primary key or not in response
                    for k,v in list(self.active_orders.items()): # list() for safe iteration if modifying
                        if v.get('orderId') == orderId:
                            self.active_orders[k].update(cancel_response)
                            if cancel_response.get('status') == 'CANCELED':
                                self.logger.info(f"Order {k} (ID: {orderId}) confirmed CANCELED.")
                            break
            else: # Should not happen
                self.logger.error(f"Order cancel failed for ID={log_id}. No response from connector.")
                return None
            return cancel_response
        except Exception as e:
            self.logger.error(f"Exception during order cancellation for ID={log_id}: {e}", exc_info=True)
            return None

    def get_order_info_from_active(self, clientOrderId: Optional[str] = None, orderId: Optional[int] = None) -> Optional[Dict]:
        """Retrieves order information from the internal active_orders cache."""
        if clientOrderId and clientOrderId in self.active_orders:
            return self.active_orders[clientOrderId]
        if orderId:
            for order_details in self.active_orders.values():
                if order_details.get('orderId') == orderId:
                    return order_details
        self.logger.debug(f"Order not found in active_orders cache: clientOrderId={clientOrderId}, orderId={orderId}")
        return None

    def update_order_status_from_api(self, symbol: str, orderId: Optional[int] = None, origClientOrderId: Optional[str] = None) -> Optional[Dict]:
        """Fetches the latest order status from API and updates the local cache."""
        log_id = orderId if orderId else origClientOrderId
        self.logger.debug(f"Updating order status from API for ID={log_id}, Symbol={symbol}")
        try:
            status_response = self.binance_connector.get_order_status(symbol, orderId, origClientOrderId)
            if status_response:
                client_oid_to_update = status_response.get('clientOrderId')
                if client_oid_to_update in self.active_orders:
                    self.active_orders[client_oid_to_update].update(status_response)
                    self.logger.info(f"Order status updated from API for {client_oid_to_update}: {status_response.get('status')}")
                elif origClientOrderId and origClientOrderId in self.active_orders: # If clientOrderId in response is different but we used origClientOrderId
                     self.active_orders[origClientOrderId].update(status_response)
                     self.logger.info(f"Order status updated from API for {origClientOrderId}: {status_response.get('status')}")
                else: # If order was not in active_orders or clientOrderId changed/missing
                    self.logger.info(f"Order {client_oid_to_update or log_id} status from API: {status_response.get('status')}. Not found or matched in active_orders for direct update by clientOrderId.")
                    # Could still store it if needed, or rely on ORDER_TRADE_UPDATE to populate it initially
                    # For now, we only update if it's already tracked by clientOrderId
            return status_response
        except Exception as e:
            self.logger.error(f"Exception fetching order status for ID={log_id}: {e}", exc_info=True)
            return None

    def handle_order_update(self, order_data_event: dict):
        """
        Handles 'ORDER_TRADE_UPDATE' events from the user data stream.
        'order_data_event' is expected to be the full event dictionary from Binance.
        """
        if order_data_event.get('e') == 'ORDER_TRADE_UPDATE':
            order_info = order_data_event.get('o', {}) # The 'o' field contains the order details

            client_order_id = order_info.get('c')
            order_id = order_info.get('i')
            symbol = order_info.get('s')
            status = order_info.get('X') # Order Status
            exec_type = order_info.get('x') # Execution Type

            self.logger.info(f"ORDER_TRADE_UPDATE received: ClientOrderID={client_order_id}, OrderID={order_id}, Symbol={symbol}, Status={status}, ExecType={exec_type}, Price={order_info.get('p')}, Qty={order_info.get('q')}")

            if client_order_id in self.active_orders:
                # Merge new update with existing data; new data takes precedence
                self.active_orders[client_order_id].update(order_info)
                self.logger.debug(f"Updated active order {client_order_id} with data: {order_info}")
            else:
                # If we are tracking by orderId or it's a new order not placed by this manager instance
                # but relevant (e.g. manual order on UI, or from another bot instance sharing account)
                # We can choose to add it or log it. For now, only update if client_order_id matches.
                # This assumes orders are primarily tracked by the clientOrderId generated by this manager.
                self.logger.info(f"Order update for ClientOrderID {client_order_id} (OrderID {order_id}) not found in this manager's active list for merging. Storing as new if not present.")
                # If you want to track all orders on the account regardless of who placed them:
                # self.active_orders[client_order_id or str(order_id)] = order_info

            if status in ['FILLED', 'CANCELED', 'EXPIRED', 'REJECTED']:
                self.logger.info(f"Order {client_order_id} (ID: {order_id}) reached final state: {status}.")
                # Optionally, move from self.active_orders to a separate history list
                # or simply log and let it be updated. If it's removed, subsequent updates for fills (if partial then canceled) might be missed.
                # For now, we keep it in active_orders but its status reflects it's final.
                # A cleanup mechanism might be needed for very long running bots.

            # TODO: Here, you would typically dispatch this update to other parts of the application
            # e.g., strategy modules that need to react to fills, GUI updates, etc.
            # self.dispatch_order_event(order_info)

        elif order_data_event.get('e') == 'ACCOUNT_UPDATE':
            # Handle account updates (balances, positions) if OrderManager is responsible for this
            self.logger.info(f"ACCOUNT_UPDATE received by OrderManager: {str(order_data_event)[:300]}")
            # This might trigger risk manager updates or P&L calculations
        else:
            self.logger.debug(f"Unhandled user data event type in OrderManager: {order_data_event.get('e')}")


if __name__ == '__main__':
    import os
    from dotenv import load_dotenv
    from bot.core.logger_setup import setup_logger # Assuming logger_setup is in the same directory

    # Setup logger
    dotenv_path_for_log = os.path.join(os.path.dirname(__file__), '../../.env')
    load_dotenv(dotenv_path=dotenv_path_for_log)
    log_level_str = os.getenv('LOG_LEVEL', 'INFO').upper()
    log_level_int = getattr(logging, log_level_str, logging.INFO)
    logger = setup_logger(level=log_level_int)

    API_KEY = os.getenv("BINANCE_TESTNET_API_KEY")
    API_SECRET = os.getenv("BINANCE_TESTNET_API_SECRET")
    USE_TESTNET = True

    if not API_KEY or API_KEY == "YOUR_TESTNET_API_KEY" or not API_SECRET:
        logger.error("Please set your BINANCE_TESTNET_API_KEY and API_SECRET in the .env file in the project root.")
    else:
        connector = BinanceAPI(api_key=API_KEY, api_secret=API_SECRET, testnet=USE_TESTNET)
        # MarketDataProvider is instantiated but not fully used in this OrderManager-focused test yet
        mdp = MarketDataProvider(binance_connector=connector)
        order_manager = OrderManager(binance_connector=connector, market_data_provider=mdp)

        # Register order_manager.handle_order_update with MarketDataProvider's user stream
        # This requires MarketDataProvider to be adapted to call this.
        # For this test, we'll directly call it if we had a mock user stream.
        # In full integration, MDP would call om.handle_order_update.

        # For now, let's simulate by directly starting the user stream from connector
        # and passing order_manager.handle_order_update as the callback.
        # This is what MDP's subscribe_to_user_data would effectively do.

        user_stream_active = False
        if connector.start_user_stream(callback=order_manager.handle_order_update):
            logger.info("User stream started directly via connector for OrderManager test.")
            user_stream_active = True
        else:
            logger.error("Failed to start user stream for OrderManager test.")

        test_client_order_id = None
        test_order_id = None

        try:
            if user_stream_active:
                logger.info("\n--- Testing Order Placement (Testnet) ---")
                # Place a LIMIT order that is unlikely to fill immediately for testing cancellation
                # Ensure symbol, price, quantity are valid for the Testnet environment
                # Using BTCUSDT as an example. Adjust price to be far from market if testing cancel.
                # For testnet, market orders are simpler if you just want to see a fill.

                # Example: LIMIT BUY order (far from market to test cancellation)
                order_response_place = order_manager.place_new_order(
                    symbol="BTCUSDT",
                    side="BUY",
                    ord_type="LIMIT",
                    quantity=0.001,
                    price=10000, # Adjust price to be far from current market to prevent immediate fill
                    timeInForce="GTC",
                    positionSide="BOTH", # or "LONG" / "SHORT" if hedge mode enabled on account
                    strategy_id="testlimit"
                )

                if order_response_place:
                    test_client_order_id = order_response_place.get('clientOrderId')
                    test_order_id = order_response_place.get('orderId')
                    logger.info(f"Test order placed: {test_client_order_id}, Binance Order ID: {test_order_id}")

                    time.sleep(5) # Wait for potential ORDER_TRADE_UPDATE via WebSocket

                    logger.info(f"\n--- Updating status from API for {test_client_order_id} ---")
                    order_manager.update_order_status_from_api(symbol="BTCUSDT", origClientOrderId=test_client_order_id)
                    cached_order = order_manager.get_order_info_from_active(clientOrderId=test_client_order_id)
                    logger.info(f"Cached order status after API update: {cached_order}")


                    if test_order_id and cached_order and cached_order.get('status') not in ['FILLED', 'CANCELED']:
                        logger.info(f"\n--- Testing Order Cancellation (Testnet) for {test_client_order_id} ---")
                        cancel_response = order_manager.cancel_existing_order(symbol="BTCUSDT", origClientOrderId=test_client_order_id)
                        logger.info(f"Cancel response: {cancel_response}")
                        time.sleep(2) # Wait for WebSocket update
                        cached_after_cancel = order_manager.get_order_info_from_active(clientOrderId=test_client_order_id)
                        logger.info(f"Cached order status after cancel attempt: {cached_after_cancel}")
                    else:
                        logger.info(f"Skipping cancellation for {test_client_order_id}, status: {cached_order.get('status') if cached_order else 'N/A'}")
                else:
                    logger.error("Test order placement failed.")

                logger.info("Order tests finished. Waiting 10s for any final WS messages...")
                time.sleep(10)

        except KeyboardInterrupt:
            logger.warning("Test interrupted by user.")
        except Exception as e:
            logger.error(f"An error occurred during OrderManager test: {e}", exc_info=True)
        finally:
            if user_stream_active:
                logger.info("Stopping user stream at the end of OrderManager test.")
                connector.stop_user_stream() # Stop the stream started by the connector directly
            time.sleep(2)
            logger.info("OrderManager test concluded.")
```
