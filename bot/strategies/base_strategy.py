from abc import ABC, abstractmethod
import logging
from typing import Dict, Any, Optional
import asyncio # Added for async helper methods

# Forward declare types for type hinting to avoid circular imports
OrderManager = Any
MarketDataProvider = Any
BasicRiskManager = Any # Added RiskManager type hint

class BaseStrategy(ABC):
    """
    Abstract base class for all trading strategies.
    """
    def __init__(self,
                 strategy_id: str,
                 params: Dict[str, Any],
                 order_manager: OrderManager,
                 market_data_provider: MarketDataProvider,
                 risk_manager: BasicRiskManager, # Added risk_manager
                 logger: Optional[logging.Logger] = None):
        self.strategy_id = strategy_id
        self.params = params
        self.order_manager = order_manager
        self.market_data_provider = market_data_provider
        self.risk_manager = risk_manager # Store risk_manager
        self.logger = logger if logger else logging.getLogger(f"strategy.{strategy_id}")

        self.is_active = False
        # Ensure strategies have a way to know if they are in backtest mode
        # This can be set by BacktestEngine after instantiation.
        self.backtest_mode = False
        self.logger.info(f"Strategy {self.strategy_id} initialized with params: {self.params}")

    def set_backtest_mode(self, mode: bool):
        """Allows the backtester to inform the strategy it's in backtest mode."""
        self.backtest_mode = mode
        self.logger.info(f"Strategy {self.strategy_id} backtest_mode set to {mode}.")


    @abstractmethod
    async def on_kline_update(self, symbol: str, interval: str, kline_data: Dict):
        pass

    @abstractmethod
    async def on_depth_update(self, symbol: str, depth_data: Dict):
        pass

    @abstractmethod
    async def on_trade_update(self, symbol: str, trade_data: Dict):
        pass

    @abstractmethod
    async def on_mark_price_update(self, symbol: str, mark_price_data: Dict):
        pass

    @abstractmethod
    async def on_order_update(self, order_update: Dict):
        pass

    @abstractmethod
    async def start(self):
        self.is_active = True
        self.logger.info(f"BaseStrategy {self.strategy_id}: start() called. Active: {self.is_active}")
        pass

    @abstractmethod
    async def stop(self):
        self.is_active = False
        self.logger.info(f"BaseStrategy {self.strategy_id}: stop() called. Active: {self.is_active}")
        pass

    # --- Optional Helper Methods for Order Management (now async) ---
    async def _place_limit_order(self, symbol: str, side: str, quantity: float, price: float,
                                 positionSide: Optional[str] = None, timeInForce: str = "GTC",
                                 newClientOrderId: Optional[str] = None) -> Optional[Dict]:
        self.logger.info(f"{self.strategy_id}: Placing LIMIT {side} order for {quantity} {symbol} @ {price}")
        try:
            # OrderManager methods are now async
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
                                  newClientOrderId: Optional[str] = None) -> Optional[Dict]:
        self.logger.info(f"{self.strategy_id}: Placing MARKET {side} order for {quantity} {symbol}")
        try:
            order_response = await self.order_manager.place_new_order(
                symbol=symbol, side=side, ord_type="MARKET", quantity=quantity,
                positionSide=positionSide, strategy_id=self.strategy_id,
                newClientOrderId=newClientOrderId
            )
            return order_response
        except Exception as e:
            self.logger.error(f"{self.strategy_id}: Error placing market order: {e}", exc_info=True)
            return None

    async def _cancel_order(self, symbol: str, orderId: Optional[int] = None,
                            origClientOrderId: Optional[str] = None) -> Optional[Dict]:
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
