import logging
import pandas as pd
from typing import Dict, Optional, Any, List
import asyncio

from .base_strategy import BaseStrategy
# from bot.core.order_executor import OrderManager # Forward declared in BaseStrategy
# from bot.core.data_fetcher import MarketDataProvider # Forward declared in BaseStrategy
# from bot.core.risk_manager import BasicRiskManager # Forward declared in BaseStrategy

class AdvancedDCAStrategy(BaseStrategy):
    def __init__(self, strategy_id: str, params: Dict[str, Any], order_manager: Any,
                 market_data_provider: Any, risk_manager: Any, logger: Optional[logging.Logger] = None):
        super().__init__(strategy_id, params, order_manager, market_data_provider, risk_manager, logger)

        self.symbol = self.get_param('symbol', 'BTCUSDT')
        self.trade_interval = self.get_param('trade_interval', "1h")

        self.initial_order_type = self.get_param('initial_order_type', 'LONG').upper()
        self.base_order_size_usd = float(self.get_param('base_order_size_usd', 100.0))

        self.safety_orders_config: List[Dict[str, float]] = self.get_param('safety_orders_config', [])
        self.max_safety_orders = len(self.safety_orders_config)

        self.take_profit_percentage = float(self.get_param('take_profit_percentage', 0.01))

        self.asset_quantity_precision = int(self.get_param('asset_quantity_precision', 3))
        self.asset_price_precision = int(self.get_param('asset_price_precision', 2))

        self.active_dca_cycle = False
        self.average_entry_price: Optional[float] = None
        self.total_quantity_asset: float = 0.0
        self.total_cost_usd: float = 0.0
        self.safety_orders_placed_count: int = 0 # Counts how many SOs have been successfully FILLED
        self.take_profit_order_id: Optional[str] = None
        self.safety_order_ids: List[str] = [] # clientOrderIds of PLACED (active) safety orders

        self.current_mark_price: Optional[float] = None
        self.logger.info(f"[{self.strategy_id}] AdvancedDCAStrategy initialized. Symbol: {self.symbol}, Initial Type: {self.initial_order_type}, Base USD: {self.base_order_size_usd}, SO Configs: {len(self.safety_orders_config)}")


    async def start(self):
        await super().start()
        if not self.backtest_mode:
            await self.market_data_provider.subscribe_to_kline_stream(
                self.symbol, self.trade_interval,
                lambda data: asyncio.create_task(self.on_kline_update(self.symbol, self.trade_interval, data))
            )
            await self.market_data_provider.subscribe_to_mark_price_stream(
                self.symbol,
                lambda data: asyncio.create_task(self.on_mark_price_update(self.symbol, data))
            )
        # Example: Start a cycle immediately for testing if a param is set
        if self.get_param('auto_start_cycle_on_init', False) and not self.active_dca_cycle:
             # Needs a current price to start, could fetch it or use a param
             # For now, this would require manual triggering via start_new_dca_cycle
             self.logger.info(f"[{self.strategy_id}] Auto-start configured, but requires manual price or signal.")


    async def stop(self):
        # Call super().stop() first to set self.is_active = False
        # This prevents new actions while stopping.
        is_currently_active = self.is_active # Store state before super().stop() potentially changes it
        await super().stop()

        if is_currently_active: # Only attempt to cancel if it was active
            self.logger.info(f"[{self.strategy_id}] AdvancedDCAStrategy stopping. Cancelling pending orders...")
            orders_to_cancel = []
            if self.take_profit_order_id:
                orders_to_cancel.append(self.take_profit_order_id)
            orders_to_cancel.extend(self.safety_order_ids)

            for order_id_to_cancel in orders_to_cancel:
                self.logger.info(f"[{self.strategy_id}] Attempting to cancel order {order_id_to_cancel}")
                try:
                    await self._cancel_order(self.symbol, origClientOrderId=order_id_to_cancel)
                except Exception as e:
                    self.logger.error(f"[{self.strategy_id}] Error cancelling order {order_id_to_cancel} on stop: {e}")

            self._reset_cycle_state() # Reset state after attempting cancellations
        self.logger.info(f"[{self.strategy_id}] AdvancedDCAStrategy stopped.")


    async def on_kline_update(self, symbol: str, interval: str, kline_data: Dict):
        if not self.is_active or symbol != self.symbol: return
        # DCA logic is primarily driven by fills and mark price, not typically new klines unless for initial signal.
        # self.logger.debug(f"[{self.strategy_id}] Kline update (not used for primary DCA logic): {kline_data.get('c')}")
        pass

    async def on_mark_price_update(self, symbol: str, mark_price_data: Dict):
        if not self.is_active or symbol != self.symbol: return
        try:
            self.current_mark_price = float(mark_price_data['p'])
            # self.logger.debug(f"[{self.strategy_id}] Mark price for {symbol}: {self.current_mark_price}")
            # Dynamic SO placement or TP adjustments based on mark price could go here if needed.
            # For now, SOs are pre-placed limit orders, and TP is a limit order.
        except KeyError: self.logger.error(f"[{self.strategy_id}] Malformed mark price data: {mark_price_data}")
        except ValueError: self.logger.error(f"[{self.strategy_id}] Could not parse mark price: {mark_price_data.get('p')}")


    async def start_new_dca_cycle(self, entry_price_estimate: Optional[float] = None):
        if self.active_dca_cycle:
            self.logger.warning(f"[{self.strategy_id}] DCA cycle already active. Cannot start new one."); return

        if entry_price_estimate is None: # Try to get current price if not provided
            if self.current_mark_price: entry_price_estimate = self.current_mark_price
            else: # Fetch if no mark price yet (e.g. just started)
                try:
                    mark_price_data = await self.market_data_provider.binance_connector.get_mark_price(self.symbol)
                    if mark_price_data and isinstance(mark_price_data, dict): # Single symbol returns dict
                        entry_price_estimate = float(mark_price_data['markPrice'])
                    elif mark_price_data and isinstance(mark_price_data, list): # No symbol returns list
                         for item in mark_price_data:
                             if item['symbol'] == self.symbol:
                                 entry_price_estimate = float(item['markPrice'])
                                 break
                    if not entry_price_estimate:
                        self.logger.error(f"[{self.strategy_id}] Could not fetch entry price for {self.symbol}. Cannot start cycle."); return
                except Exception as e:
                    self.logger.error(f"[{self.strategy_id}] Error fetching entry price: {e}. Cannot start cycle."); return

        self.logger.info(f"[{self.strategy_id}] Starting new DCA cycle. Type: {self.initial_order_type}, Entry Est: {entry_price_estimate}")
        self.active_dca_cycle = True # Set active early to prevent re-entry attempts
        await self._place_initial_order(entry_price_estimate)


    async def _place_initial_order(self, current_price: float):
        quantity = round(self.base_order_size_usd / current_price, self.asset_quantity_precision)
        min_qty = float(self.get_param('min_trade_qty', 0.001)) # Example, should be symbol specific
        if quantity < min_qty:
            self.logger.warning(f"[{self.strategy_id}] Initial order qty {quantity} < min {min_qty}. Aborting cycle."); self._reset_cycle_state(); return

        side = "BUY" if self.initial_order_type == "LONG" else "SELL"
        pos_side = "LONG" if self.initial_order_type == "LONG" else "SHORT"

        order_response = await self._place_market_order(self.symbol, side, quantity, positionSide=pos_side)
        # Note: on_order_update will handle the FILLED state from WebSocket.
        # Here, we just log the placement attempt. If it fails immediately, an exception would be caught by caller.
        if order_response:
            self.logger.info(f"[{self.strategy_id}] Initial order placement request sent. ClientOID: {order_response.get('clientOrderId')}")
        else:
            self.logger.error(f"[{self.strategy_id}] Initial order placement request failed.")
            self._reset_cycle_state() # Failed to place, so reset

    async def _place_all_pending_safety_orders(self, last_order_price: float):
        if not self.active_dca_cycle: return

        # Clear any old SO clientOrderIds before placing new ones
        self.safety_order_ids = []

        side = "BUY" if self.initial_order_type == "LONG" else "SELL"
        pos_side = "LONG" if self.initial_order_type == "LONG" else "SHORT"

        # Only place SOs up to max_safety_orders, considering those already filled (safety_orders_placed_count)
        start_so_index = self.safety_orders_placed_count
        for i in range(start_so_index, self.max_safety_orders):
            so_config = self.safety_orders_config[i]
            deviation = so_config['deviation_perc'] / 100.0

            price_ref_for_deviation = last_order_price # Deviation from the price of the *last filled order* (initial or last SO)

            if side == "BUY": so_price = price_ref_for_deviation * (1 - deviation)
            else: so_price = price_ref_for_deviation * (1 + deviation)
            so_price = round(so_price, self.asset_price_precision)

            so_quantity_usd = self.base_order_size_usd * so_config['size_usd_multiplier']
            so_quantity_asset = round(so_quantity_usd / so_price, self.asset_quantity_precision)

            min_qty = float(self.get_param('min_trade_qty', 0.001))
            if so_quantity_asset < min_qty:
                self.logger.warning(f"[{self.strategy_id}] SO {i+1} qty {so_quantity_asset} < min {min_qty}. Skipping."); continue

            so_client_order_id = self._generate_client_order_id(f"{self.strategy_id}_so{i+1}")
            order_response = await self._place_limit_order(
                self.symbol, side, so_quantity_asset, so_price,
                positionSide=pos_side, timeInForce="GTC", newClientOrderId=so_client_order_id
            )
            if order_response and order_response.get('orderId'):
                self.safety_order_ids.append(so_client_order_id)
                self.logger.info(f"[{self.strategy_id}] Safety Order {i+1} placed: ClientOID={so_client_order_id}, Price={so_price}, Qty={so_quantity_asset}")
            else:
                self.logger.error(f"[{self.strategy_id}] Failed to place Safety Order {i+1}: {order_response}")


    async def _place_take_profit_order(self):
        if not self.active_dca_cycle or not self.average_entry_price or self.total_quantity_asset == 0: return

        if self.take_profit_order_id:
            self.logger.info(f"[{self.strategy_id}] Cancelling existing TP {self.take_profit_order_id} before new one.")
            await self._cancel_order(self.symbol, origClientOrderId=self.take_profit_order_id)
            self.take_profit_order_id = None

        tp_price = self.average_entry_price * (1 + self.take_profit_percentage) if self.initial_order_type == "LONG" \
              else self.average_entry_price * (1 - self.take_profit_percentage)
        tp_price = round(tp_price, self.asset_price_precision)

        side = "SELL" if self.initial_order_type == "LONG" else "BUY"
        pos_side = "LONG" if self.initial_order_type == "LONG" else "SHORT"
        tp_client_order_id = self._generate_client_order_id(f"{self.strategy_id}_tp")

        self.logger.info(f"[{self.strategy_id}] Placing TP order: {side} {self.total_quantity_asset} {self.symbol} @ {tp_price}")
        order_response = await self._place_limit_order(
            self.symbol, side, self.total_quantity_asset, tp_price,
            positionSide=pos_side, timeInForce="GTC", reduceOnly=True, newClientOrderId=tp_client_order_id
        )
        if order_response and order_response.get('orderId'):
            self.take_profit_order_id = tp_client_order_id
            self.logger.info(f"[{self.strategy_id}] TP order placed: ClientOID={tp_client_order_id}, OrderID={order_response.get('orderId')}")
        else:
            self.logger.error(f"[{self.strategy_id}] Failed to place TP order: {order_response}")


    async def on_order_update(self, order_update: Dict):
        # Ensure base class processing if any (e.g. logging)
        # await super().on_order_update(order_update)

        client_order_id = order_update.get('c')
        if not client_order_id or not client_order_id.startswith(self.strategy_id):
            # self.logger.debug(f"[{self.strategy_id}] Ignoring order update for unrelated clientOrderId: {client_order_id}")
            return

        order_status = order_update.get('X')
        order_id = order_update.get('i')
        filled_qty = float(order_update.get('z', 0.0))
        avg_filled_price = float(order_update.get('ap', 0.0)) if order_update.get('ap') else float(order_update.get('L', 0.0)) # Use L if ap is 0

        self.logger.info(f"[{self.strategy_id}] Own Order Update: ClientOID={client_order_id}, OID={order_id}, Status={order_status}, FilledQty={filled_qty}, AvgPx={avg_filled_price}")

        if order_status == 'FILLED':
            is_initial_order = not self.active_dca_cycle and self.safety_orders_placed_count == 0 # Heuristic

            if client_order_id == self.take_profit_order_id:
                self.logger.info(f"[{self.strategy_id}] Take Profit order FILLED! Cycle completed.")
                self._reset_cycle_state()
            elif client_order_id in self.safety_order_ids:
                self.logger.info(f"[{self.strategy_id}] Safety Order {client_order_id} FILLED.")
                self.safety_orders_placed_count += 1
                self.safety_order_ids.remove(client_order_id)

                new_cost = avg_filled_price * filled_qty
                self.total_cost_usd += new_cost
                self.total_quantity_asset += filled_qty
                self.average_entry_price = self.total_cost_usd / self.total_quantity_asset if self.total_quantity_asset > 0 else None

                self.logger.info(f"[{self.strategy_id}] After SO fill: New AvgPrice: {self.average_entry_price}, TotalQty: {self.total_quantity_asset}, SOs filled: {self.safety_orders_placed_count}")
                await self._place_take_profit_order() # Update TP with new avg price and total qty
                # Potentially place next tier of SOs if they are dynamic based on last fill (not current design)

            # Check if it's the initial order (might be identified by strategy_id + some suffix, or if no cycle active)
            # This logic relies on the initial order response not being 'FILLED' immediately from REST call
            # and that on_order_update handles the first fill.
            elif not self.active_dca_cycle and self.total_quantity_asset == 0: # Likely initial order
                self.logger.info(f"[{self.strategy_id}] Initial order {client_order_id} FILLED.")
                self.active_dca_cycle = True # Mark cycle active
                self.average_entry_price = avg_filled_price
                self.total_quantity_asset = filled_qty
                self.total_cost_usd = avg_filled_price * filled_qty
                self.safety_orders_placed_count = 0 # Reset for this cycle

                await self._place_take_profit_order()
                await self._place_all_pending_safety_orders(use_last_order_price=avg_filled_price)
            else:
                 self.logger.info(f"[{self.strategy_id}] A tracked order {client_order_id} filled, but not identified as TP, SO, or initial. Current state: active_cycle={self.active_dca_cycle}, total_qty={self.total_quantity_asset}")


        elif order_status in ['CANCELED', 'REJECTED', 'EXPIRED']:
            self.logger.warning(f"[{self.strategy_id}] Order {client_order_id} is {order_status}.")
            if client_order_id == self.take_profit_order_id: self.take_profit_order_id = None
            if client_order_id in self.safety_order_ids: self.safety_order_ids.remove(client_order_id)
            # If many SOs fail, or initial order fails, might need to reset cycle.
            if not self.active_dca_cycle and self.total_quantity_asset == 0 and (client_order_id.endswith("_init") or len(self.safety_order_ids) == 0) : # Heuristic for initial order failing
                 self.logger.error(f"[{self.strategy_id}] Initial order {client_order_id} failed ({order_status}). Resetting cycle.")
                 self._reset_cycle_state()


    def _reset_cycle_state(self):
        self.logger.info(f"[{self.strategy_id}] Resetting DCA cycle state.")
        self.active_dca_cycle = False
        self.average_entry_price = None
        self.total_quantity_asset = 0.0
        self.total_cost_usd = 0.0
        self.safety_orders_placed_count = 0
        self.take_profit_order_id = None
        self.safety_order_ids = []
        self.current_mark_price = None

    async def on_depth_update(self, symbol: str, depth_data: Dict): pass
    async def on_trade_update(self, symbol: str, trade_data: Dict): pass

```
