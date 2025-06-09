import logging
import pandas as pd
from typing import Dict, Optional, Any, List
import asyncio

from .base_strategy import BaseStrategy
OrderManager = Any
MarketDataProvider = Any
BasicRiskManager = Any

class AdvancedDCAStrategy(BaseStrategy):
    strategy_type_name: str = "AdvancedDCAStrategy"

    def __init__(self, strategy_id: str, params: Dict[str, Any], order_manager: OrderManager,
                 market_data_provider: MarketDataProvider, risk_manager: BasicRiskManager,
                 logger: Optional[logging.Logger] = None):
        super().__init__(strategy_id, params, order_manager, market_data_provider, risk_manager, logger)

        self.symbol: str = self.get_param('symbol', 'BTCUSDT')
        self.trade_interval: str = self.get_param('trade_timeframe', "1h") # Renamed from trade_interval for consistency

        self.initial_order_type: str = self.get_param('initial_order_type', 'LONG').upper()
        self.base_order_size_usd: float = float(self.get_param('base_order_size_usd', 50.0)) # Min 50 for safety

        self.safety_orders_config: List[Dict[str, float]] = self.get_param('safety_orders', []) # Renamed for clarity
        self.max_safety_orders: int = len(self.safety_orders_config)

        self.take_profit_percentage: float = float(self.get_param('take_profit_percentage', 1.0)) / 100.0 # Convert percentage to decimal

        self.asset_quantity_precision: int = int(self.get_param('asset_quantity_precision', 3))
        self.asset_price_precision: int = int(self.get_param('asset_price_precision', 2))
        self.min_trade_qty: float = float(self.get_param('min_order_qty', 0.001))

        self.active_dca_cycle: bool = False
        self.average_entry_price: Optional[float] = None
        self.total_quantity_asset: float = 0.0
        self.total_cost_usd: float = 0.0
        self.safety_orders_filled_count: int = 0
        self.take_profit_order_id: Optional[str] = None
        self.active_safety_order_ids: List[str] = []

        self.current_mark_price: Optional[float] = None
        self.auto_start_on_first_kline: bool = self.get_param('auto_start_dca_on_first_kline', False)
        self._first_kline_processed: bool = False

        self.logger.info(f"[{self.strategy_id}] {self.strategy_type_name} initialized. Symbol: {self.symbol}, Initial Type: {self.initial_order_type}, Base USD: {self.base_order_size_usd}, SO Configs: {len(self.safety_orders_config)}")

    @staticmethod
    def get_default_params() -> dict:
        return {
            'symbol': {'type': 'str', 'default': 'BTCUSDT', 'desc': 'Trading symbol.'},
            'trade_timeframe': {'type': 'str', 'default': '1h', 'options': ['1m','5m','15m','1h','4h'], 'desc': 'Timeframe for kline data subscription (primarily for mark price in DCA).'},
            'initial_order_type': {'type': 'str', 'default': 'LONG', 'options': ['LONG', 'SHORT'], 'desc': 'Direction of the initial order.'},
            'base_order_size_usd': {'type': 'float', 'default': 50.0, 'min': 5.0, 'step': 1.0, 'desc': 'USD size of the initial (base) order.'},
            'safety_orders': {'type': 'list_of_dict', 'default': [
                {'price_deviation_perc': 1.0, 'size_usd_multiplier': 1.0},
                {'price_deviation_perc': 2.0, 'size_usd_multiplier': 1.5},
                {'price_deviation_perc': 3.0, 'size_usd_multiplier': 2.0},
            ], 'desc': "List of safety order configs [{'price_deviation_perc': % from last, 'size_usd_multiplier': mult of base}]"},
            'take_profit_percentage': {'type': 'float', 'default': 1.0, 'min': 0.1, 'max': 10.0, 'step': 0.1, 'desc': 'Take profit % from average entry price.'},
            'asset_quantity_precision': {'type': 'int', 'default': 3, 'desc': 'Decimal precision for asset quantity.'},
            'asset_price_precision': {'type': 'int', 'default': 2, 'desc': 'Decimal precision for asset price.'},
            'min_order_qty': {'type': 'float', 'default': 0.001, 'desc': 'Minimum order quantity for the symbol.'},
            'auto_start_dca_on_first_kline': {'type': 'bool', 'default': False, 'desc': '(Backtest Only) Auto-start cycle on first kline.'}
        }

    async def start(self):
        # ... (implementation from previous step, ensure super().start() is called and self.strategy_type_name is set)
        self.strategy_type_name = self.__class__.strategy_type_name # Ensure set if not by BaseStrategy
        await super().start()
        if not self.backtest_mode:
            await self.market_data_provider.subscribe_to_kline_stream(
                self.symbol, self.trade_timeframe,
                lambda data: asyncio.create_task(self.on_kline_update(self.symbol, self.trade_timeframe, data))
            )
            await self.market_data_provider.subscribe_to_mark_price_stream(
                self.symbol,
                lambda data: asyncio.create_task(self.on_mark_price_update(self.symbol, data))
            )
        self.logger.info(f"[{self.strategy_id}] {self.strategy_type_name} started. Auto-start: {self.auto_start_on_first_kline}")


    async def stop(self):
        # ... (implementation from previous step, ensure super().stop() is called)
        is_currently_active = self.is_active
        await super().stop()

        if is_currently_active:
            self.logger.info(f"[{self.strategy_id}] {self.strategy_type_name} stopping. Cancelling orders...")
            orders_to_cancel = []
            if self.take_profit_order_id: orders_to_cancel.append(self.take_profit_order_id)
            orders_to_cancel.extend(self.active_safety_order_ids)

            for order_id_to_cancel in orders_to_cancel:
                self.logger.info(f"[{self.strategy_id}] Attempting to cancel order {order_id_to_cancel}")
                try: await self._cancel_order(self.symbol, origClientOrderId=order_id_to_cancel)
                except Exception as e: self.logger.error(f"[{self.strategy_id}] Error cancelling order {order_id_to_cancel} on stop: {e}")

        self._reset_cycle_state()
        self.logger.info(f"[{self.strategy_id}] {self.strategy_type_name} stopped and state reset.")


    async def on_kline_update(self, symbol: str, interval: str, kline_data: Dict):
        # ... (implementation from previous step)
        if not self.is_active or symbol != self.symbol: return
        current_price = float(kline_data['c'])
        if self.backtest_mode and self.auto_start_on_first_kline and not self._first_kline_processed and not self.active_dca_cycle:
            self.logger.info(f"[{self.strategy_id}] Backtest auto-start: Triggering DCA cycle on first kline at price {current_price}")
            await self.start_new_dca_cycle(entry_price_estimate=current_price)
        self._first_kline_processed = True

    async def on_mark_price_update(self, symbol: str, mark_price_data: Dict):
        # ... (implementation from previous step, ensure self.current_mark_price is updated)
        if not self.is_active or symbol != self.symbol: return
        try:
            self.current_mark_price = float(mark_price_data['p'])
        except KeyError: self.logger.error(f"[{self.strategy_id}] Malformed mark price data: {mark_price_data}")
        except ValueError: self.logger.error(f"[{self.strategy_id}] Could not parse mark price: {mark_price_data.get('p')}")


    async def start_new_dca_cycle(self, entry_price_estimate: Optional[float] = None):
        # ... (implementation from previous step, ensure self._reset_cycle_state() is called before starting)
        if self.active_dca_cycle:
            self.logger.warning(f"[{self.strategy_id}] DCA cycle already active."); return

        if entry_price_estimate is None:
            if self.current_mark_price: entry_price_estimate = self.current_mark_price
            else:
                try:
                    mp_data = await self.market_data_provider.binance_connector.get_mark_price(self.symbol) # type: ignore
                    if mp_data and isinstance(mp_data, dict): entry_price_estimate = float(mp_data['markPrice'])
                    elif mp_data and isinstance(mp_data, list):
                         for item in mp_data:
                             if item['symbol'] == self.symbol: entry_price_estimate = float(item['markPrice']); break
                    if not entry_price_estimate: self.logger.error(f"[{self.strategy_id}] No entry price for {self.symbol}."); return
                except Exception as e: self.logger.error(f"[{self.strategy_id}] Error fetching entry price: {e}."); return

        self._reset_cycle_state()
        self.active_dca_cycle = True
        self.logger.info(f"[{self.strategy_id}] Starting new DCA cycle. Type: {self.initial_order_type}, Entry Est: {entry_price_estimate}")
        await self._place_initial_order(entry_price_estimate)


    async def _place_initial_order(self, current_price: float):
        # ... (implementation from previous step, use self.asset_quantity_precision, self.min_trade_qty)
        quantity = round(self.base_order_size_usd / current_price, self.asset_quantity_precision)
        if quantity < self.min_trade_qty:
            self.logger.warning(f"[{self.strategy_id}] Initial qty {quantity} < min {self.min_trade_qty}. Aborting."); self._reset_cycle_state(); return

        side = "BUY" if self.initial_order_type == "LONG" else "SELL"
        pos_side = "LONG" if self.initial_order_type == "LONG" else "SHORT"
        client_oid = self._generate_client_order_id(f"{self.strategy_id}_init")
        order_response = await self._place_market_order(self.symbol, side, quantity, positionSide=pos_side, newClientOrderId=client_oid)
        if not order_response: self._reset_cycle_state()


    async def _place_all_pending_safety_orders(self, last_filled_price: float):
        # ... (implementation from previous step, use self.asset_price_precision, self.asset_quantity_precision, self.min_trade_qty)
        if not self.active_dca_cycle: return
        for old_so_id in self.active_safety_order_ids:
            try: await self._cancel_order(self.symbol, origClientOrderId=old_so_id)
            except Exception as e: self.logger.error(f"[{self.strategy_id}] Error cancelling old SO {old_so_id}: {e}")
        self.active_safety_order_ids = []
        side = "BUY" if self.initial_order_type == "LONG" else "SELL"
        pos_side = "LONG" if self.initial_order_type == "LONG" else "SHORT"

        # Only consider SOs that haven't been filled yet
        start_index = self.safety_orders_filled_count
        for i in range(start_index, self.max_safety_orders):
            so_config = self.safety_orders_config[i]
            deviation = so_config['price_deviation_perc'] / 100.0 # Corrected key

            price_ref = last_filled_price # Deviation from last filled order price
            so_price = round(price_ref * (1 - deviation) if side == "BUY" else price_ref * (1 + deviation), self.asset_price_precision)
            so_quantity_usd = self.base_order_size_usd * so_config['size_usd_multiplier']
            so_quantity_asset = round(so_quantity_usd / so_price, self.asset_quantity_precision) if so_price > 0 else 0

            if so_quantity_asset < self.min_trade_qty: self.logger.warning(f"[{self.strategy_id}] SO {i+1} qty {so_quantity_asset} < min {self.min_trade_qty}. Skip."); continue
            so_client_order_id = self._generate_client_order_id(f"{self.strategy_id}_so{i+1}")
            order_response = await self._place_limit_order(self.symbol, side, so_quantity_asset, so_price, positionSide=pos_side, timeInForce="GTC", newClientOrderId=so_client_order_id)
            if order_response and (order_response.get('orderId') or order_response.get('status') == 'NEW'):
                self.active_safety_order_ids.append(so_client_order_id)
            else: self.logger.error(f"[{self.strategy_id}] Failed to place SO {i+1}: {order_response}")


    async def _place_take_profit_order(self):
        # ... (implementation from previous step, use self.asset_price_precision, self.asset_quantity_precision, self.min_trade_qty)
        if not self.active_dca_cycle or not self.average_entry_price or self.total_quantity_asset == 0: return
        if self.take_profit_order_id:
            try: await self._cancel_order(self.symbol, origClientOrderId=self.take_profit_order_id)
            except Exception as e: self.logger.error(f"[{self.strategy_id}] Error cancelling existing TP: {e}")
            self.take_profit_order_id = None

        tp_price = self.average_entry_price * (1 + self.take_profit_percentage) if self.initial_order_type == "LONG" else self.average_entry_price * (1 - self.take_profit_percentage)
        tp_price = round(tp_price, self.asset_price_precision)
        side = "SELL" if self.initial_order_type == "LONG" else "BUY"
        pos_side = "LONG" if self.initial_order_type == "LONG" else "SHORT"
        tp_client_order_id = self._generate_client_order_id(f"{self.strategy_id}_tp")
        tp_quantity = round(self.total_quantity_asset, self.asset_quantity_precision)
        if tp_quantity < self.min_trade_qty: self.logger.warning(f"[{self.strategy_id}] TP qty {tp_quantity} < min. Cannot place."); return

        order_response = await self._place_limit_order(self.symbol, side, tp_quantity, tp_price, positionSide=pos_side, timeInForce="GTC", reduceOnly=True, newClientOrderId=tp_client_order_id)
        if order_response and (order_response.get('orderId') or order_response.get('status') == 'NEW'): self.take_profit_order_id = tp_client_order_id
        else: self.logger.error(f"[{self.strategy_id}] Failed to place TP order: {order_response}")


    async def on_order_update(self, order_update: Dict):
        # ... (implementation from previous step, ensure it uses self.asset_quantity_precision)
        client_order_id = order_update.get('c')
        if not client_order_id or not client_order_id.startswith(self.strategy_id): return
        order_status = order_update.get('X'); order_id = order_update.get('i')
        filled_qty = float(order_update.get('z', 0.0))
        avg_filled_price = float(order_update.get('ap', 0.0)) if order_update.get('ap') and float(order_update.get('ap',0.0)) > 0 else float(order_update.get('L', 0.0))

        self.logger.info(f"[{self.strategy_id}] Own Order Update: ClientOID={client_order_id}, OID={order_id}, Status={order_status}, FilledQty={filled_qty}, AvgPx={avg_filled_price}")

        is_initial_order_fill = client_order_id.endswith("_init") and not self.active_dca_cycle and self.total_quantity_asset == 0

        if order_status == 'FILLED':
            if is_initial_order_fill :
                self.logger.info(f"[{self.strategy_id}] Initial order {client_order_id} FILLED.")
                self.active_dca_cycle = True
                self.average_entry_price = avg_filled_price; self.total_quantity_asset = filled_qty
                self.total_cost_usd = avg_filled_price * filled_qty; self.safety_orders_filled_count = 0
                await self._place_take_profit_order()
                await self._place_all_pending_safety_orders(last_filled_price=avg_filled_price)
            elif client_order_id in self.active_safety_order_ids:
                self.logger.info(f"[{self.strategy_id}] Safety Order {client_order_id} FILLED.")
                self.safety_orders_filled_count += 1
                self.active_safety_order_ids.remove(client_order_id)
                new_cost = avg_filled_price * filled_qty
                self.total_cost_usd += new_cost
                self.total_quantity_asset = round(self.total_quantity_asset + filled_qty, self.asset_quantity_precision)
                self.average_entry_price = self.total_cost_usd / self.total_quantity_asset if self.total_quantity_asset > 0 else None
                self.logger.info(f"[{self.strategy_id}] After SO: AvgPx={self.average_entry_price}, TotalQty={self.total_quantity_asset}, SOsFilled={self.safety_orders_filled_count}")
                await self._place_take_profit_order()
                await self._place_all_pending_safety_orders(last_filled_price=avg_filled_price) # Re-evaluate/place remaining SOs based on new last_filled_price
            elif client_order_id == self.take_profit_order_id:
                self.logger.info(f"[{self.strategy_id}] Take Profit order {client_order_id} FILLED! Cycle completed.")
                for so_id in self.active_safety_order_ids: # Cancel pending SOs
                    try: await self._cancel_order(self.symbol, origClientOrderId=so_id)
                    except Exception as e: self.logger.error(f"Error cancelling SO {so_id} after TP: {e}")
                self._reset_cycle_state()
        elif order_status in ['CANCELED', 'REJECTED', 'EXPIRED']:
            self.logger.warning(f"[{self.strategy_id}] Order {client_order_id} is {order_status}.")
            if client_order_id == self.take_profit_order_id: self.take_profit_order_id = None
            if client_order_id in self.active_safety_order_ids: self.active_safety_order_ids.remove(client_order_id)
            if is_initial_order_fill: # If initial order fails
                 self.logger.error(f"[{self.strategy_id}] Initial order {client_order_id} failed ({order_status}). Resetting cycle.")
                 self._reset_cycle_state()

    def _reset_cycle_state(self):
        # ... (implementation from previous step)
        self.logger.info(f"[{self.strategy_id}] Resetting DCA cycle state.")
        self.active_dca_cycle = False; self.average_entry_price = None
        self.total_quantity_asset = 0.0; self.total_cost_usd = 0.0
        self.safety_orders_filled_count = 0; self.take_profit_order_id = None
        self.active_safety_order_ids = []; self.current_mark_price = None
        self._first_kline_processed = False

    async def on_depth_update(self, symbol: str, depth_data: Dict): pass
    async def on_trade_update(self, symbol: str, trade_data: Dict): pass
```
