import logging
import time
import uuid
from typing import Dict, Optional, Callable, Any, List # Added List
import asyncio

try:
    from bot.connectors.binance_connector import BinanceAPI
    from bot.core.data_fetcher import MarketDataProvider
    from bot.core.risk_manager import BasicRiskManager
except ImportError:
    from connectors.binance_connector import BinanceAPI # type: ignore
    from core.data_fetcher import MarketDataProvider # type: ignore
    from core.risk_manager import BasicRiskManager # type: ignore


class OrderManager:
    def __init__(self,
                 binance_connector: BinanceAPI,
                 market_data_provider: MarketDataProvider,
                 risk_manager: Optional[BasicRiskManager] = None):
        self.binance_connector = binance_connector
        self.market_data_provider = market_data_provider # Stored for potential future use (e.g. getting current price for market order SL calc)
        self.risk_manager = risk_manager
        self.logger = logging.getLogger('algo_trader_bot.OrderManager') # More specific logger
        self.active_orders: Dict[str, Dict[str, Any]] = {}

    async def get_available_trading_balance(self, asset: str = 'USDT') -> Optional[float]:
        self.logger.debug(f"Fetching available trading balance for {asset} (async).")
        try:
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
                return None
            self.logger.warning("Failed to fetch account balance (async).")
        except Exception as e:
            self.logger.error(f"Error fetching account balance (async): {e}", exc_info=True)
        return None

    def _generate_client_order_id(self, strategy_id: str = "default") -> str:
        prefix = strategy_id.replace("_", "")[:10]
        timestamp_ms = int(time.time() * 1000)
        return f"{prefix}t{timestamp_ms}"[:36]

    async def place_new_order(self, symbol: str, side: str, ord_type: str, quantity: float,
                              price: Optional[float] = None, timeInForce: Optional[str] = None,
                              reduceOnly: Optional[bool] = None, stopPrice: Optional[float] = None,
                              positionSide: Optional[str] = None, strategy_id: str = "manual",
                              newOrderRespType: str = 'RESULT') -> Optional[Dict]: # Changed default to RESULT
        client_order_id = self._generate_client_order_id(strategy_id)
        self.logger.info(f"Attempting to place order: ClientOID={client_order_id}, Sym={symbol}, Side={side}, Type={ord_type}, Qty={quantity}, Px={price}, PosSide={positionSide}")

        try:
            order_response = await self.binance_connector.place_order(
                symbol=symbol, side=side, ord_type=ord_type, quantity=quantity, price=price,
                timeInForce=timeInForce, reduceOnly=reduceOnly, newClientOrderId=client_order_id,
                stopPrice=stopPrice, positionSide=positionSide, newOrderRespType=newOrderRespType
            )
            if order_response:
                self.logger.info(f"Order Placed API RSP: ClientOID={client_order_id}, OrderID={order_response.get('orderId')}, Status={order_response.get('status')}")
                self.active_orders[client_order_id] = order_response
                # With RESULT or FULL, status might already be final or partially filled.
                # The WebSocket update via handle_order_update will provide the definitive state.
            else:
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
            cancel_response = await self.binance_connector.cancel_order(symbol, orderId=orderId, origClientOrderId=origClientOrderId) # Pass kwargs correctly
            if cancel_response:
                self.logger.info(f"Order Cancel API RSP: ID={log_id}, Status={cancel_response.get('status')}")
                client_oid = cancel_response.get('clientOrderId', origClientOrderId) # Prefer clientOrderId from response
                if client_oid and client_oid in self.active_orders: # If we tracked by clientOrderId
                    self.active_orders[client_oid].update(cancel_response)
                elif str(cancel_response.get('orderId')) in self.active_orders: # If we tracked by stringified orderId
                    self.active_orders[str(cancel_response.get('orderId'))].update(cancel_response)

            else: self.logger.error(f"Order cancel failed (no response from connector): ID={log_id}"); return None
            return cancel_response
        except Exception as e:
            self.logger.error(f"Exception canceling order ID={log_id}: {e}", exc_info=True)
            return None

    def get_order_info_from_active(self, clientOrderId: Optional[str] = None, orderId: Optional[int] = None) -> Optional[Dict]:
        if clientOrderId and clientOrderId in self.active_orders: return self.active_orders[clientOrderId]
        if orderId:
            str_order_id = str(orderId) # Compare with string keys if needed
            if str_order_id in self.active_orders: return self.active_orders[str_order_id]
            for order in self.active_orders.values(): # Fallback search
                if order.get('orderId') == orderId: return order
        return None

    async def update_order_status_from_api(self, symbol: str, orderId: Optional[int] = None, origClientOrderId: Optional[str] = None) -> Optional[Dict]:
        # ... (implementation from previous step is okay) ...
        log_id = orderId or origClientOrderId
        self.logger.debug(f"Updating order status from API: ID={log_id}, Symbol={symbol}")
        try:
            status_response = await self.binance_connector.get_order_status(symbol, orderId=orderId, origClientOrderId=origClientOrderId)
            if status_response:
                client_oid = status_response.get('clientOrderId')
                bin_order_id = str(status_response.get('orderId'))

                key_to_update = None
                if client_oid and client_oid in self.active_orders: key_to_update = client_oid
                elif bin_order_id and bin_order_id in self.active_orders: key_to_update = bin_order_id

                if key_to_update:
                    self.active_orders[key_to_update].update(status_response)
                    self.logger.info(f"Order status from API for {key_to_update}: {status_response.get('status')}")
                else: # If order not in cache, add it using clientOrderId or orderId as key
                    self.active_orders[client_oid or bin_order_id] = status_response
                    self.logger.info(f"Order {client_oid or bin_order_id} added/updated from API poll: {status_response.get('status')}")
            return status_response
        except Exception as e:
            self.logger.error(f"Exception fetching order status ID={log_id}: {e}", exc_info=True)
            return None


    def handle_order_update(self, order_data_event: Dict[str, Any]):
        # This method is called by MarketDataProvider (sync context from a thread)
        # It updates internal state. If it needed to call async methods, it would need scheduling.
        event_type = order_data_event.get('e')
        if event_type == 'ORDER_TRADE_UPDATE':
            order_info = order_data_event.get('o', {})
            client_order_id = order_info.get('c')
            order_id_str = str(order_info.get('i'))
            status = order_info.get('X')
            self.logger.info(f"OM WS ORDER_UPDATE: ClientOID={client_order_id}, OID={order_id_str}, Sym={order_info.get('s')}, Status={status}")

            key_to_update = client_order_id if client_order_id in self.active_orders else None
            if not key_to_update and order_id_str in self.active_orders: # Check if tracked by str(orderId)
                key_to_update = order_id_str

            if key_to_update:
                self.active_orders[key_to_update].update(order_info)
            else: # New order or not tracked by client_order_id, use order_id_str
                self.active_orders[order_id_str] = order_info
                self.logger.info(f"Order OID={order_id_str} (ClientOID={client_order_id}) added/updated in OM active_orders via WS.")

            if status in ['FILLED', 'CANCELED', 'EXPIRED', 'REJECTED', 'PARTIALLY_FILLED_CANCELED']:
                final_key = key_to_update or order_id_str
                self.logger.info(f"Order {final_key} final state via WS: {status}. Consider moving from active_orders.")
        elif event_type == 'ACCOUNT_UPDATE':
            self.logger.debug(f"OM WS ACCOUNT_UPDATE: {str(order_data_event)[:200]}")
            # Balance updates could be processed here to inform RiskManager more proactively if needed.
            # For example, extract 'a' (assets) from data.get('a', {})
            # And update a balance cache or directly call RM method (if RM is thread-safe or call is scheduled)
        # Other events like 'listenKeyExpired' could be handled here too.

    # --- Methods for UI Data Provisioning ---
    async def get_open_orders_data_for_ui(self) -> List[Dict[str, Any]]:
        self.logger.debug("Fetching open orders for UI.")
        try:
            # Fetch all open orders for all symbols (or a specific one if UI supports it)
            open_orders = await self.binance_connector.get_open_orders() # Fetches for all symbols if symbol=None
            if open_orders is None: return [] # Error case

            formatted_orders = []
            for order in open_orders:
                formatted_orders.append({
                    "Symbol": order.get('symbol'), "Order ID": str(order.get('orderId')), "Client ID": order.get('clientOrderId'),
                    "Side": order.get('side'), "Type": order.get('type'), "Price": order.get('price'),
                    "Quantity": order.get('origQty'), "Filled Qty": order.get('executedQty'),
                    "Status": order.get('status'), "Time": order.get('time'), # Already ms timestamp
                    "Position Side": order.get('positionSide', 'N/A')
                })
            return formatted_orders
        except Exception as e:
            self.logger.error(f"Error fetching open orders for UI: {e}", exc_info=True)
            return []

    async def get_trade_history_data_for_ui(self, symbol: str = "BTCUSDT", limit: int = 50) -> List[Dict[str, Any]]:
        self.logger.debug(f"Fetching trade history for {symbol} (limit {limit}) for UI.")
        try:
            # Uses /fapi/v1/userTrades endpoint
            trades = await self.binance_connector.get_my_trades(symbol=symbol, limit=limit)
            if trades is None: return []

            formatted_trades = []
            for trade in trades:
                formatted_trades.append({
                    "Symbol": trade.get('symbol'), "Trade ID": str(trade.get('id')), "Order ID": str(trade.get('orderId')),
                    "Side": trade.get('side'), "Price": trade.get('price'), "Quantity": trade.get('qty'),
                    "Commission": trade.get('commission'), "Comm. Asset": trade.get('commissionAsset'),
                    "Time": trade.get('time'), "Realized P&L": trade.get('realizedPnl', 'N/A')
                })
            return formatted_trades
        except Exception as e:
            self.logger.error(f"Error fetching trade history for UI: {e}", exc_info=True)
            return []

    async def get_position_data_for_ui(self) -> List[Dict[str, Any]]:
        self.logger.debug("Fetching position data for UI.")
        try:
            positions = await self.binance_connector.get_position_information() # Fetches for all symbols
            if positions is None: return []

            formatted_positions = []
            for pos in positions:
                # Filter out positions with zero amount if desired
                if float(pos.get('positionAmt', 0)) != 0:
                    formatted_positions.append({
                        "Symbol": pos.get('symbol'), "Side": pos.get('positionSide'), "Quantity": pos.get('positionAmt'),
                        "Entry Price": pos.get('entryPrice'), "Mark Price": pos.get('markPrice'),
                        "Unrealized P&L": pos.get('unRealizedProfit'),
                        "Liq. Price": pos.get('liquidationPrice', 'N/A'),
                        "Margin": pos.get('isolatedMargin', pos.get('initialMargin', 'N/A')) # Check for isolated vs cross
                    })
            return formatted_positions
        except Exception as e:
            self.logger.error(f"Error fetching position data for UI: {e}", exc_info=True)
            return []

    async def close_position_market(self, symbol: str, position_side_to_close: str) -> Optional[Dict]:
        self.logger.info(f"Attempting to close {position_side_to_close} position for {symbol} with MARKET order.")
        try:
            positions = await self.binance_connector.get_position_information(symbol=symbol)
            if not positions:
                self.logger.warning(f"No position information found for {symbol} to close."); return None

            target_position = None
            for pos in positions:
                if pos.get('symbol') == symbol and pos.get('positionSide', '').upper() == position_side_to_close.upper():
                    target_position = pos
                    break
                # For ONE_WAY mode, positionSide might be BOTH or NONE.
                # If positionSide_to_close is LONG, actual side is BUY. If SHORT, actual side is SELL.
                # positionAmt > 0 for LONG, < 0 for SHORT in ONE_WAY.
                elif pos.get('symbol') == symbol and pos.get('positionSide','').upper() == 'BOTH':
                     pos_amt = float(pos.get('positionAmt',0))
                     if position_side_to_close == 'LONG' and pos_amt > 0: target_position = pos; break
                     if position_side_to_close == 'SHORT' and pos_amt < 0: target_position = pos; break


            if not target_position:
                self.logger.warning(f"No active {position_side_to_close} position found for {symbol} to close."); return None

            quantity_str = target_position.get('positionAmt', "0")
            quantity = abs(float(quantity_str)) # Quantity is absolute for order placement
            if quantity == 0:
                self.logger.info(f"Position for {symbol} side {position_side_to_close} is already zero."); return None

            side_to_execute = "SELL" if position_side_to_close == "LONG" else "BUY"

            self.logger.info(f"Placing reduceOnly MARKET order to close {position_side_to_close} {symbol}: {side_to_execute} {quantity}")
            order_response = await self.place_new_order(
                symbol=symbol, side=side_to_execute, ord_type="MARKET",
                quantity=quantity, reduceOnly=True, positionSide=position_side_to_close, # Ensure positionSide is passed for Hedge Mode
                strategy_id="ui_close"
            )
            return order_response
        except Exception as e:
            self.logger.error(f"Error closing position for {symbol} ({position_side_to_close}): {e}", exc_info=True)
            return None


if __name__ == '__main__':
    # ... (main test block needs to be async and use await for OM methods)
    pass
```
