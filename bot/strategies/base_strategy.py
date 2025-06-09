from abc import ABC, abstractmethod
import logging
from typing import Dict, Any, Optional

# Forward declare types for type hinting to avoid circular imports
# These classes are expected to be defined elsewhere.
OrderManager = Any
MarketDataProvider = Any

class BaseStrategy(ABC):
    """
    Abstract base class for all trading strategies.
    """
    def __init__(self,
                 strategy_id: str,
                 params: Dict[str, Any],
                 order_manager: OrderManager, # Actual type: bot.core.order_executor.OrderManager
                 market_data_provider: MarketDataProvider, # Actual type: bot.core.data_fetcher.MarketDataProvider
                 logger: Optional[logging.Logger] = None):
        self.strategy_id = strategy_id
        self.params = params
        self.order_manager = order_manager
        self.market_data_provider = market_data_provider
        self.logger = logger if logger else logging.getLogger(f"strategy.{strategy_id}")

        self.is_active = False
        self.logger.info(f"Strategy {self.strategy_id} initialized with params: {self.params}")

    @abstractmethod
    async def on_kline_update(self, symbol: str, interval: str, kline_data: Dict):
        """
        Called by the StrategyEngine when new kline data is available for a subscribed symbol/interval.
        """
        pass

    @abstractmethod
    async def on_depth_update(self, symbol: str, depth_data: Dict):
        """
        Called by the StrategyEngine when new depth data is available.
        """
        pass

    @abstractmethod
    async def on_trade_update(self, symbol: str, trade_data: Dict):
        """
        Called by the StrategyEngine when a new trade occurs.
        """
        pass

    @abstractmethod
    async def on_mark_price_update(self, symbol: str, mark_price_data: Dict):
        """
        Called by the StrategyEngine when a new mark price update occurs.
        """
        pass

    @abstractmethod
    async def on_order_update(self, order_update: Dict):
        """
        Called by the StrategyEngine when an order update relevant to this strategy occurs.
        The strategy should filter if the order_update is relevant to its own orders.
        """
        pass

    @abstractmethod
    async def start(self):
        """
        Called by the StrategyEngine to start the strategy.
        Strategies should implement logic to subscribe to necessary market data streams here.
        Example:
            self.logger.info(f"Starting strategy {self.strategy_id}")
            # Example subscription:
            # await self.market_data_provider.subscribe_to_kline_stream(
            #     symbol="BTCUSDT",
            #     interval="1m",
            #     callback=lambda data: asyncio.create_task(self.on_kline_update("BTCUSDT", "1m", data))
            # )
            self.is_active = True
            self.logger.info(f"Strategy {self.strategy_id} started.")
        """
        self.is_active = True
        self.logger.info(f"BaseStrategy {self.strategy_id}: start() called.")
        pass

    @abstractmethod
    async def stop(self):
        """
        Called by the StrategyEngine to stop the strategy.
        Strategies should implement logic to unsubscribe from streams and clean up resources.
        Example:
            self.logger.info(f"Stopping strategy {self.strategy_id}")
            # Unsubscribe logic would go here
            self.is_active = False
            self.logger.info(f"Strategy {self.strategy_id} stopped.")
        """
        self.is_active = False
        self.logger.info(f"BaseStrategy {self.strategy_id}: stop() called.")
        pass

    # --- Optional Helper Methods for Order Management ---
    async def _place_limit_order(self, symbol: str, side: str, quantity: float, price: float,
                                 positionSide: Optional[str] = None, timeInForce: str = "GTC") -> Optional[Dict]:
        self.logger.info(f"{self.strategy_id}: Placing LIMIT {side} order for {quantity} {symbol} @ {price}")
        try:
            order_response = await asyncio.to_thread(
                self.order_manager.place_new_order,
                symbol=symbol,
                side=side,
                ord_type="LIMIT",
                quantity=quantity,
                price=price,
                timeInForce=timeInForce,
                positionSide=positionSide,
                strategy_id=self.strategy_id
            )
            return order_response
        except Exception as e:
            self.logger.error(f"{self.strategy_id}: Error placing limit order: {e}", exc_info=True)
            return None

    async def _place_market_order(self, symbol: str, side: str, quantity: float,
                                  positionSide: Optional[str] = None) -> Optional[Dict]:
        self.logger.info(f"{self.strategy_id}: Placing MARKET {side} order for {quantity} {symbol}")
        try:
            order_response = await asyncio.to_thread(
                self.order_manager.place_new_order,
                symbol=symbol,
                side=side,
                ord_type="MARKET",
                quantity=quantity,
                positionSide=positionSide,
                strategy_id=self.strategy_id
            )
            return order_response
        except Exception as e:
            self.logger.error(f"{self.strategy_id}: Error placing market order: {e}", exc_info=True)
            return None

    async def _cancel_order(self, symbol: str, orderId: Optional[int] = None, origClientOrderId: Optional[str] = None) -> Optional[Dict]:
        log_id = orderId if orderId else origClientOrderId
        self.logger.info(f"{self.strategy_id}: Attempting to cancel order {log_id} for {symbol}")
        try:
            cancel_response = await asyncio.to_thread(
                self.order_manager.cancel_existing_order,
                symbol=symbol,
                orderId=orderId,
                origClientOrderId=origClientOrderId
            )
            return cancel_response
        except Exception as e:
            self.logger.error(f"{self.strategy_id}: Error canceling order {log_id}: {e}", exc_info=True)
            return None

    def get_param(self, param_name: str, default: Any = None) -> Any:
        """Helper to get a parameter for this strategy, with a default value."""
        return self.params.get(param_name, default)

```
