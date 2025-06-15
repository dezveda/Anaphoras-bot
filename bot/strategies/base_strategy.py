from abc import ABC, abstractmethod
import logging
from typing import Dict, Any, Optional
import asyncio

OrderManager = Any
MarketDataProvider = Any
BasicRiskManager = Any

class BaseStrategy(ABC):
    strategy_type_name: str = "BaseStrategy" # Class variable to identify type

    def __init__(self,
                 strategy_id: str,
                 params: Dict[str, Any],
                 order_manager: OrderManager,
                 market_data_provider: MarketDataProvider,
                 risk_manager: BasicRiskManager,
                 logger: Optional[logging.Logger] = None,
                 strategy_engine_ref: Optional[Any] = None): # Added strategy_engine_ref
        self.strategy_id = strategy_id
        self.strategy_engine_ref = strategy_engine_ref # Store the reference
        # Store strategy_type_name in instance params if not already there from engine
        # This ensures it's available even if strategy is instantiated outside engine
        params_to_store = params.copy()
        if 'strategy_type_name' not in params_to_store:
            params_to_store['strategy_type_name'] = self.__class__.strategy_type_name
        self.params = params_to_store

        self.order_manager = order_manager
        self.market_data_provider = market_data_provider
        self.risk_manager = risk_manager
        self.logger = logger if logger else logging.getLogger(f"strategy.{strategy_id}")

        self.is_active = False
        self.backtest_mode = False
        self.logger.info(f"Strategy [{self.strategy_id} - Type: {self.params['strategy_type_name']}] initialized with params: {self.params}")

    def set_backtest_mode(self, mode: bool):
        self.backtest_mode = mode
        self.logger.info(f"Strategy [{self.strategy_id}] backtest_mode set to {mode}.")

    @staticmethod
    @abstractmethod
    def get_default_params() -> dict:
        """
        Returns a dictionary of default parameters for the strategy.
        Keys are param names, values are dicts with 'type', 'default', 'desc',
        and optionally 'options', 'min', 'max', 'step'.
        """
        return {
            "strategy_specific_param_example": {
                "type": "str", "default": "example_value",
                "desc": "An example strategy-specific parameter.",
                "options": ["example_value", "another_value"]
            }
        }

    @abstractmethod
    async def on_kline_update(self, symbol: str, interval: str, kline_data: Dict): pass
    @abstractmethod
    async def on_depth_update(self, symbol: str, depth_data: Dict): pass
    @abstractmethod
    async def on_trade_update(self, symbol: str, trade_data: Dict): pass
    @abstractmethod
    async def on_mark_price_update(self, symbol: str, mark_price_data: Dict): pass
    @abstractmethod
    async def on_order_update(self, order_update: Dict): pass
    # Optional: if strategies need to react to general account updates (balance changes not tied to own orders)
    # @abstractmethod
    # async def on_account_update(self, account_update_data: Dict): pass


    async def start(self):
        self.is_active = True
        self.logger.info(f"Strategy [{self.strategy_id}] start() called. Active: {self.is_active}, BacktestMode: {self.backtest_mode}")

    async def stop(self):
        self.is_active = False # Set inactive first
        self.logger.info(f"Strategy [{self.strategy_id}] stop() called. Active: {self.is_active}")

    async def on_parameters_updated(self, new_params: Dict[str, Any]):
        """
        Called by StrategyEngine when parameters are updated via UI.
        Strategy should re-initialize relevant attributes if needed.
        """
        self.logger.info(f"[{self.strategy_id}] Parameters updated. New params: {new_params}. Current params were: {self.params}")
        self.params.update(new_params)
        # Re-initialize any attributes that depend on these params
        # Example: self.some_period = int(self.get_param("some_period_name", 20))
        self.logger.info(f"[{self.strategy_id}] Parameters applied. Restart strategy if behavior needs full reset or data subscriptions change.")


    async def _place_limit_order(self, symbol: str, side: str, quantity: float, price: float,
                                 positionSide: Optional[str] = None, timeInForce: str = "GTC",
                                 newClientOrderId: Optional[str] = None) -> Optional[Dict]:
        # ... (implementation remains same)
        self.logger.info(f"{self.strategy_id}: Placing LIMIT {side} order for {quantity} {symbol} @ {price}")
        try:
            order_response = await self.order_manager.place_new_order(
                symbol=symbol, side=side, ord_type="LIMIT", quantity=quantity, price=price,
                timeInForce=timeInForce, positionSide=positionSide, strategy_id=self.strategy_id,
                newClientOrderId=newClientOrderId
            )
            return order_response
        except Exception as e:
            self.logger.error(f"{self.strategy_id}: Error placing limit order: {e}", exc_info=True)
            return None

    async def _place_market_order(self, symbol: str, side: str, quantity: float,
                                  positionSide: Optional[str] = None,
                                  newClientOrderId: Optional[str] = None,
                                  reduceOnly: Optional[bool] = None) -> Optional[Dict]: # Added reduceOnly
        self.logger.info(f"{self.strategy_id}: Placing MARKET {side} order for {quantity} {symbol} ReduceOnly: {reduceOnly}")
        try:
            order_response = await self.order_manager.place_new_order(
                symbol=symbol, side=side, ord_type="MARKET", quantity=quantity,
                positionSide=positionSide, strategy_id=self.strategy_id,
                newClientOrderId=newClientOrderId, reduceOnly=reduceOnly
            )
            return order_response
        except Exception as e:
            self.logger.error(f"{self.strategy_id}: Error placing market order: {e}", exc_info=True)
            return None

    async def _cancel_order(self, symbol: str, orderId: Optional[int] = None,
                            origClientOrderId: Optional[str] = None) -> Optional[Dict]:
        # ... (implementation remains same)
        log_id = orderId or origClientOrderId
        self.logger.info(f"{self.strategy_id}: Attempting to cancel order {log_id} for {symbol}")
        try:
            cancel_response = await self.order_manager.cancel_existing_order(
                symbol=symbol, orderId=orderId, origClientOrderId=origClientOrderId
            )
            return cancel_response
        except Exception as e:
            self.logger.error(f"{self.strategy_id}: Error canceling order {log_id}: {e}", exc_info=True)
            return None

    def get_param(self, param_name: str, default: Any = None) -> Any:
        return self.params.get(param_name, default)

```
