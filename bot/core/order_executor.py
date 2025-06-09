import logging
import time
import uuid # For more unique clientOrderIds
from typing import Dict, Optional, Callable, Any
import asyncio # Added for async methods

try:
    from bot.connectors.binance_connector import BinanceAPI
    from bot.core.data_fetcher import MarketDataProvider
    from bot.core.risk_manager import BasicRiskManager # Import RiskManager
except ImportError:
    from connectors.binance_connector import BinanceAPI # type: ignore
    from core.data_fetcher import MarketDataProvider # type: ignore
    from core.risk_manager import BasicRiskManager # type: ignore


class OrderManager:
    def __init__(self,
                 binance_connector: BinanceAPI,
                 market_data_provider: MarketDataProvider,
                 risk_manager: Optional[BasicRiskManager] = None): # RiskManager added
        self.binance_connector = binance_connector
        self.market_data_provider = market_data_provider
        self.risk_manager = risk_manager # Store RiskManager
        self.logger = logging.getLogger('algo_trader_bot')
        self.active_orders: Dict[str, Dict[str, Any]] = {}

    async def get_available_trading_balance(self, asset: str = 'USDT') -> Optional[float]:
        """
        Asynchronously gets available balance for a specific asset.
        """
        self.logger.debug(f"Fetching available trading balance for {asset} (async).")
        try:
            # BinanceConnector methods are now async
            balances = await self.binance_connector.get_account_balance()
            if balances:
                for balance_asset_info in balances:
                    if balance_asset_info.get('asset') == asset:
                        try:
                            available_balance = float(balance_asset_info.get('availableBalance', 0.0))
                            self.logger.info(f"Async balance fetch for {asset}: {available_balance}")
                            return available_balance
                        except ValueError:
                            self.logger.error(f"Could not parse availableBalance for {asset} from: {balance_asset_info.get('availableBalance')}")
                            return None
                self.logger.warning(f"{asset} balance not found in account balance response.")
                return None # Asset not found
            self.logger.warning("Failed to fetch account balance (async).")
        except Exception as e:
            self.logger.error(f"Error fetching account balance (async): {e}", exc_info=True)
        return None # Fallback if API call fails

    def _generate_client_order_id(self, strategy_id: str = "default") -> str:
        prefix = strategy_id.replace("_", "")[:10]
        timestamp_ms = int(time.time() * 1000)
        return f"{prefix}t{timestamp_ms}"[:36]

    async def place_new_order(self, symbol: str, side: str, ord_type: str, quantity: float,
                              price: Optional[float] = None, timeInForce: Optional[str] = None,
                              reduceOnly: Optional[bool] = None, stopPrice: Optional[float] = None,
                              positionSide: Optional[str] = None, strategy_id: str = "manual",
                              newOrderRespType: str = 'ACK') -> Optional[Dict]:
        client_order_id = self._generate_client_order_id(strategy_id)
        self.logger.info(f"Attempting to place order: ClientOID={client_order_id}, Sym={symbol}, Side={side}, Type={ord_type}, Qty={quantity}, Px={price}, PosSide={positionSide}")

        # Placeholder for actual risk check using self.risk_manager
        # if self.risk_manager:
        #     is_valid = await self.risk_manager.validate_order_risk(...)
        #     if not is_valid:
        #         self.logger.warning(f"Order {client_order_id} rejected by RiskManager.")
        #         return None

        try:
            order_response = await self.binance_connector.place_order(
                symbol=symbol, side=side, ord_type=ord_type, quantity=quantity, price=price,
                timeInForce=timeInForce, reduceOnly=reduceOnly, newClientOrderId=client_order_id,
                stopPrice=stopPrice, positionSide=positionSide, newOrderRespType=newOrderRespType
            )
            if order_response:
                self.logger.info(f"Order Placed API RSP: ClientOID={client_order_id}, OrderID={order_response.get('orderId')}, Status={order_response.get('status')}")
                self.active_orders[client_order_id] = order_response
                if order_response.get('status') in ['FILLED', 'CANCELED', 'EXPIRED', 'REJECTED']:
                    self.logger.info(f"Order {client_order_id} final state from REST: {order_response.get('status')}")
            else: # Should be caught by exception handling in _make_request
                self.logger.error(f"Order placement failed (no response from connector): ClientOID={client_order_id}")
                return None
            return order_response
        except Exception as e:
            self.logger.error(f"Exception placing order ClientOID={client_order_id}: {e}", exc_info=True)
            return None

    async def cancel_existing_order(self, symbol: str, orderId: Optional[int] = None, origClientOrderId: Optional[str] = None) -> Optional[Dict]:
        log_id = orderId or origClientOrderId
        self.logger.info(f"Attempting to cancel order: ID={log_id}, Symbol={symbol}")
        if not orderId and not origClientOrderId:
            self.logger.error("Cannot cancel: orderId or origClientOrderId required."); return None
        try:
            cancel_response = await self.binance_connector.cancel_order(symbol, orderId, origClientOrderId)
            if cancel_response:
                self.logger.info(f"Order Cancel API RSP: ID={log_id}, Status={cancel_response.get('status')}")
                client_oid = cancel_response.get('clientOrderId', origClientOrderId)
                if client_oid and client_oid in self.active_orders:
                    self.active_orders[client_oid].update(cancel_response)
                    if cancel_response.get('status') == 'CANCELED':
                         self.logger.info(f"Order {client_oid} CANCELED, updated in cache.")
            else:
                self.logger.error(f"Order cancel failed (no response from connector): ID={log_id}"); return None
            return cancel_response
        except Exception as e:
            self.logger.error(f"Exception canceling order ID={log_id}: {e}", exc_info=True)
            return None

    def get_order_info_from_active(self, clientOrderId: Optional[str] = None, orderId: Optional[int] = None) -> Optional[Dict]:
        # This method remains synchronous as it queries a local cache
        if clientOrderId and clientOrderId in self.active_orders:
            return self.active_orders[clientOrderId]
        if orderId:
            for order in self.active_orders.values():
                if order.get('orderId') == orderId: return order
        self.logger.debug(f"Order not in active_orders cache: clientOID={clientOrderId}, OID={orderId}")
        return None

    async def update_order_status_from_api(self, symbol: str, orderId: Optional[int] = None, origClientOrderId: Optional[str] = None) -> Optional[Dict]:
        log_id = orderId or origClientOrderId
        self.logger.debug(f"Updating order status from API: ID={log_id}, Symbol={symbol}")
        try:
            status_response = await self.binance_connector.get_order_status(symbol, orderId, origClientOrderId)
            if status_response:
                client_oid = status_response.get('clientOrderId')
                # Update logic based on how orders are primarily keyed in active_orders
                key_to_check = client_oid or origClientOrderId
                if key_to_check and key_to_check in self.active_orders:
                     self.active_orders[key_to_check].update(status_response)
                     self.logger.info(f"Order status from API for {key_to_check}: {status_response.get('status')}")
                elif client_oid: # If not found by primary key but client_oid exists
                     self.active_orders[client_oid] = status_response # Add or update using client_oid from response
                     self.logger.info(f"Order status for {client_oid} (potentially new or re-keyed) updated from API: {status_response.get('status')}")
                else:
                     self.logger.info(f"Order {log_id} status from API: {status_response.get('status')}. Not updated in cache as clientOrderId mapping unclear.")
            return status_response
        except Exception as e:
            self.logger.error(f"Exception fetching order status ID={log_id}: {e}", exc_info=True)
            return None

    def handle_order_update(self, order_data: Dict[str, Any]):
        event_type = order_data.get('e')
        if event_type == 'ORDER_TRADE_UPDATE':
            order_info = order_data.get('o', {})
            client_order_id = order_info.get('c') # clientOrderId from event
            order_id = order_info.get('i')      # Binance orderId
            status = order_info.get('X')
            self.logger.info(f"WS ORDER_UPDATE: ClientOID={client_order_id}, OID={order_id}, Sym={order_info.get('s')}, Status={status}, ExecType={order_info.get('x')}")

            # Prefer clientOrderId if it exists and is one we track, otherwise use Binance orderId as key
            tracked_order_key = None
            if client_order_id in self.active_orders:
                tracked_order_key = client_order_id
            elif str(order_id) in self.active_orders: # If we stored it by orderId string initially
                tracked_order_key = str(order_id)
            else: # Fallback: check if any stored order matches the Binance orderId
                for k, v in self.active_orders.items():
                    if v.get('orderId') == order_id:
                        tracked_order_key = k
                        break

            if tracked_order_key:
                self.active_orders[tracked_order_key].update(order_info)
                self.logger.debug(f"Updated active order {tracked_order_key} via WS: {order_info}")
            else:
                # This order wasn't placed by this OrderManager instance or wasn't found; store by its Binance orderId.
                # This helps track manually placed orders or orders from other sources if needed.
                self.active_orders[str(order_id)] = order_info
                self.logger.info(f"Order OID={order_id} (ClientOID={client_order_id}) added/updated in active_orders via WS as it was not previously tracked by clientOID.")

            if status in ['FILLED', 'CANCELED', 'EXPIRED', 'REJECTED', 'PARTIALLY_FILLED_CANCELED']:
                final_key = tracked_order_key or str(order_id)
                self.logger.info(f"Order {final_key} reached final state via WS: {status}. Consider moving from active_orders.")
        elif event_type == 'ACCOUNT_UPDATE':
            self.logger.info(f"WS ACCOUNT_UPDATE (in OrderManager): {str(order_data)[:300]}")
            # Logic to update available balance for RiskManager could go here if RM doesn't fetch it.
            # For example, find the relevant asset (USDT) and update a shared balance variable/property.
            # for asset_update in order_data.get('a', {}).get('B', []): # Balances
            #     if asset_update.get('a') == 'USDT':
            #         new_balance = float(asset_update.get('wb')) # Wallet Balance
            #         self.logger.info(f"Account Update: USDT Wallet Balance: {new_balance}")
            #         # self.risk_manager.update_balance(new_balance) # If RM supports this
        else:
            self.logger.debug(f"Unhandled user data event in OrderManager: {event_type}")


async def main_test_async_order_manager(): # Renamed for clarity
    # Setup logger (ensure it's done once)
    logger_instance = logging.getLogger('algo_trader_bot')
    if not logger_instance.hasHandlers():
        try:
            from bot.core.logger_setup import setup_logger
            dotenv_path_for_log = os.path.join(os.path.dirname(__file__), '../../.env')
            load_dotenv(dotenv_path=dotenv_path_for_log)
            log_level_str = os.getenv('LOG_LEVEL', 'DEBUG').upper() # DEBUG for testing
            log_level_int = getattr(logging, log_level_str, logging.DEBUG)
            setup_logger(level=log_level_int)
        except ImportError:
            logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(module)s - %(funcName)s - %(message)s')

    import os
    from dotenv import load_dotenv
    dotenv_path = os.path.join(os.path.dirname(__file__), '../../.env')
    load_dotenv(dotenv_path=dotenv_path)
    API_KEY = os.getenv("BINANCE_TESTNET_API_KEY")
    API_SECRET = os.getenv("BINANCE_TESTNET_API_SECRET")

    if not API_KEY or API_KEY == "YOUR_TESTNET_API_KEY" or not API_SECRET:
        logger_instance.error("Testnet API keys must be set in .env for OrderManager async test.")
        return

    connector = BinanceAPI(api_key=API_KEY, api_secret=API_SECRET, testnet=True)
    mdp = MarketDataProvider(binance_connector=connector) # MDP now takes no order_update_callback in __init__

    # RiskManager needs an async balance provider
    # OrderManager's get_available_trading_balance is now async
    # We need to pass it as a callable to BasicRiskManager.
    # The BasicRiskManager itself needs to be updated to await this.
    # For this test, we'll initialize RM later or mock it if RM is not yet async-ready.

    order_manager = OrderManager(binance_connector=connector, market_data_provider=mdp, risk_manager=None) # RM passed as None for now

    # MDP's subscribe_to_user_data takes a generic callback.
    # OrderManager's handle_order_update is the callback.
    mdp.subscribe_to_user_data(user_data_event_callback=order_manager.handle_order_update)

    test_client_oid_main = None
    try:
        if mdp.binance_connector.user_data_control_flag.get('keep_running'):
            logger_instance.info("--- OrderManager Async Test: Placing & Canceling Order (Testnet) ---")

            balance = await order_manager.get_available_trading_balance()
            logger_instance.info(f"Current USDT balance (async): {balance}")

            resp_place = await order_manager.place_new_order(
                symbol="BTCUSDT", side="BUY", ord_type="LIMIT", quantity=0.001,
                price=20000, timeInForce="GTC", strategy_id="om_async"
            )
            if resp_place:
                test_client_oid_main = resp_place.get('clientOrderId')
                logger_instance.info(f"Async Placed test order: {test_client_oid_main}, Full Response: {resp_place}")
                await asyncio.sleep(5)

                cached_order = order_manager.get_order_info_from_active(clientOrderId=test_client_oid_main)
                logger_instance.info(f"Cached order after place: {cached_order}")

                if cached_order and cached_order.get('status') == 'NEW':
                    resp_cancel = await order_manager.cancel_existing_order("BTCUSDT", origClientOrderId=test_client_oid_main)
                    logger_instance.info(f"Async Cancel response: {resp_cancel}")
                    await asyncio.sleep(3)
                    cached_order_after_cancel = order_manager.get_order_info_from_active(clientOrderId=test_client_oid_main)
                    logger_instance.info(f"Cached order after cancel: {cached_order_after_cancel}")
                else:
                    logger_instance.warning(f"Order {test_client_oid_main} not NEW, skipping cancel. Status: {cached_order.get('status') if cached_order else 'N/A'}")
            else:
                logger_instance.error("Async Test order placement failed.")

            logger_instance.info("Async Order tests finished. Waiting 10s for final WS messages.")
            await asyncio.sleep(10)
        else:
            logger_instance.error("User stream did not start, cannot run full OrderManager async test.")

    except KeyboardInterrupt: logger_instance.info("Async Test interrupted.")
    except Exception as e: logger_instance.error(f"Error in OrderManager async test: {e}", exc_info=True)
    finally:
        if mdp.binance_connector.user_data_control_flag.get('keep_running'):
            logger_instance.info("Stopping user stream via MDP (async test)...")
            mdp.unsubscribe_all_streams()
        await asyncio.sleep(2) # Give time for async tasks to clean up
        logger_instance.info("OrderManager async test concluded.")

if __name__ == '__main__':
    asyncio.run(main_test_async_order_manager())
```
