import logging
import asyncio
from typing import Dict, Type, Any, Optional, Callable

try:
    from bot.strategies.base_strategy import BaseStrategy
    from bot.core.order_executor import OrderManager
    from bot.core.data_fetcher import MarketDataProvider
    from bot.core.risk_manager import BasicRiskManager
    from bot.strategies.pivot_strategy import PivotPointStrategy
    from bot.strategies.dca_strategy import AdvancedDCAStrategy
    from bot.strategies.liquidity_strategy import LiquidityPointsStrategy
    from bot.strategies.trend_adaptation_strategy import TrendAdaptationStrategy
    from bot.strategies.indicator_heuristic_strategy import IndicatorHeuristicStrategy
except ImportError:
    from .base_strategy import BaseStrategy # type: ignore
    import sys, os # type: ignore
    sys.path.append(os.path.join(os.path.dirname(__file__), '../core')) # type: ignore
    OrderManager = type('OrderManager', (), {}) # type: ignore
    MarketDataProvider = type('MarketDataProvider', (), {}) # type: ignore
    BasicRiskManager = type('BasicRiskManager', (), {}) # type: ignore
    # Define TrendAdaptationStrategy as a type for isinstance check, even if it's a mock
    TrendAdaptationStrategy = type('TrendAdaptationStrategy', (BaseStrategy,), {}) # type: ignore
    PivotPointStrategy = type('PivotPointStrategy', (BaseStrategy,), {}) # type: ignore
    AdvancedDCAStrategy = type('AdvancedDCAStrategy', (BaseStrategy,), {}) # type: ignore
    LiquidityPointsStrategy = type('LiquidityPointsStrategy', (BaseStrategy,), {}) # type: ignore
    IndicatorHeuristicStrategy = type('IndicatorHeuristicStrategy', (BaseStrategy,), {}) # type: ignore


class StrategyEngine:
    def __init__(self,
                 order_manager: OrderManager,
                 market_data_provider: MarketDataProvider,
                 risk_manager: BasicRiskManager,
                 logger_name: str = 'algo_trader_bot'):
        self.order_manager = order_manager
        self.market_data_provider = market_data_provider
        self.risk_manager = risk_manager
        self.logger = logging.getLogger(logger_name)

        self.strategies: Dict[str, BaseStrategy] = {}
        self.live_trading_mode: bool = False
        self.async_loop: Optional[asyncio.AbstractEventLoop] = None
        self.trend_adapter_instance: Optional[TrendAdaptationStrategy] = None # For TrendAdaptationStrategy
        self.logger.info("StrategyEngine initialized.")

    def get_available_strategy_types(self) -> Dict[str, Type[BaseStrategy]]:
        # Ensure TrendAdaptationStrategy is imported for this method
        from .trend_adaptation_strategy import TrendAdaptationStrategy as TAS_Actual
        # This is a bit of a hack for potential circular deps or just to ensure it's the right type
        # For other strategies, they are already imported at the top.
        return {
            "PivotPointStrategy": PivotPointStrategy,
            "AdvancedDCAStrategy": AdvancedDCAStrategy,
            "LiquidityPointsStrategy": LiquidityPointsStrategy,
            "TrendAdaptationStrategy": TAS_Actual, # Use actual class here
            "IndicatorHeuristicStrategy": IndicatorHeuristicStrategy
        }

    def load_strategy(self,
                      strategy_class: Type[BaseStrategy],
                      strategy_id: str,
                      params: Dict[str, Any]) -> bool:
        if strategy_id in self.strategies:
            self.logger.warning(f"Strategy with ID '{strategy_id}' already loaded. Skipping.")
            return False

        params['strategy_type_name'] = strategy_class.__name__

        try:
            # Pass self (StrategyEngine instance) as strategy_engine_ref
            strategy_instance = strategy_class(
                strategy_id=strategy_id,
                params=params,
                order_manager=self.order_manager,
                market_data_provider=self.market_data_provider,
                risk_manager=self.risk_manager,
                logger=self.logger.getChild(f"strategy.{strategy_id}"),
                strategy_engine_ref=self # Pass reference to self
            )

            # Check if this is an instance of TrendAdaptationStrategy
            # Need to import TrendAdaptationStrategy properly for isinstance to work reliably
            # from .trend_adaptation_strategy import TrendAdaptationStrategy as ActualTAS
            # Using type name check for now if direct import for isinstance is problematic here
            if strategy_class.__name__ == "TrendAdaptationStrategy":
                 if self.trend_adapter_instance:
                     self.logger.warning("Multiple TrendAdaptationStrategy instances loaded. Using the last one.")
                 self.trend_adapter_instance = strategy_instance # type: ignore

            self.strategies[strategy_id] = strategy_instance
            self.logger.info(f"Strategy '{strategy_id}' of type {strategy_class.__name__} loaded.")
            return True
        except Exception as e:
            self.logger.error(f"Failed to load strategy '{strategy_id}': {e}", exc_info=True)
            return False

    def get_trend_adapter(self) -> Optional[TrendAdaptationStrategy]: # Return type is TrendAdaptationStrategy
        return self.trend_adapter_instance


    def get_strategy_parameters(self, strategy_id: str) -> Optional[Dict[str, Any]]:
        # ... (same as before)
        if strategy_id in self.strategies:
            return self.strategies[strategy_id].params
        self.logger.warning(f"Strategy {strategy_id} not found for get_strategy_parameters.")
        return None

    def update_strategy_parameters(self, strategy_id: str, new_params: Dict[str, Any]) -> bool:
        # ... (same as before, consider calling strategy.on_parameters_updated if it exists)
        if strategy_id in self.strategies:
            self.strategies[strategy_id].params.update(new_params)
            if 'strategy_type_name' in new_params: # Should not change but good to preserve
                 self.strategies[strategy_id].params['strategy_type_name'] = new_params['strategy_type_name']
            self.logger.info(f"Parameters for strategy {strategy_id} updated.")
            if self.strategies[strategy_id].is_active and hasattr(self.strategies[strategy_id], 'on_parameters_updated'):
                asyncio.create_task(self.strategies[strategy_id].on_parameters_updated(new_params))
            return True
        self.logger.warning(f"Strategy {strategy_id} not found for update_strategy_parameters.")
        return False

    async def remove_strategy(self, strategy_id: str) -> bool:
        # ... (same as before)
        if strategy_id in self.strategies:
            self.logger.info(f"Removing strategy {strategy_id}...")
            await self.stop_strategy(strategy_id)
            if self.trend_adapter_instance and self.trend_adapter_instance.strategy_id == strategy_id:
                self.trend_adapter_instance = None # Clear if it was the trend adapter
            del self.strategies[strategy_id]
            self.logger.info(f"Strategy {strategy_id} removed.")
            return True
        self.logger.warning(f"Strategy {strategy_id} not found for removal.")
        return False


    async def start_strategy(self, strategy_id: str):
        # ... (same as before)
        if strategy_id not in self.strategies:
            self.logger.error(f"Cannot start strategy '{strategy_id}': Not found.")
            return
        strategy = self.strategies[strategy_id]
        strategy.backtest_mode = not self.live_trading_mode
        if strategy.is_active:
            self.logger.info(f"Strategy '{strategy_id}' is already active.")
            return
        self.logger.info(f"Starting strategy '{strategy_id}' (Live mode: {self.live_trading_mode})...")
        try: await strategy.start()
        except Exception as e: self.logger.error(f"Error starting strategy '{strategy_id}': {e}", exc_info=True)

    async def stop_strategy(self, strategy_id: str):
        # ... (same as before)
        if strategy_id not in self.strategies:
            self.logger.error(f"Cannot stop strategy '{strategy_id}': Not found.")
            return
        strategy = self.strategies[strategy_id]
        # if not strategy.is_active: # Allow stopping even if not marked active, to be safe
        #     self.logger.info(f"Strategy '{strategy_id}' is not active.")
        #     return
        self.logger.info(f"Stopping strategy '{strategy_id}'...")
        try: await strategy.stop()
        except Exception as e: self.logger.error(f"Error stopping strategy '{strategy_id}': {e}", exc_info=True)


    async def start_all_strategies(self):
        # ... (same as before)
        self.logger.info("Starting all loaded strategies...")
        tasks = [self.start_strategy(strategy_id) for strategy_id in self.strategies.keys()]
        await asyncio.gather(*tasks, return_exceptions=True)
        self.logger.info("Finished attempting to start all strategies.")

    async def stop_all_strategies(self):
        # ... (same as before)
        self.logger.info("Stopping all active strategies...")
        tasks = [self.stop_strategy(strategy_id) for strategy_id in list(self.strategies.keys()) if self.strategies[strategy_id].is_active]
        await asyncio.gather(*tasks, return_exceptions=True)
        self.logger.info("Finished attempting to stop all strategies.")

    async def handle_user_data_for_strategies(self, user_data_event: Dict):
        # ... (same as before)
        event_type = user_data_event.get('e')
        tasks_to_await = []
        if event_type == 'ORDER_TRADE_UPDATE':
            order_data = user_data_event.get('o', {})
            self.logger.debug(f"StrategyEngine distributing ORDER_TRADE_UPDATE: ClientOID={order_data.get('c')}")
            for strat in self.strategies.values():
                if strat.is_active: tasks_to_await.append(strat.on_order_update(order_data))
        elif event_type == 'ACCOUNT_UPDATE':
            self.logger.debug(f"StrategyEngine received ACCOUNT_UPDATE.")
            for strat in self.strategies.values():
                if strat.is_active and hasattr(strat, 'on_account_update') and callable(strat.on_account_update):
                    tasks_to_await.append(strat.on_account_update(user_data_event)) # type: ignore
        if tasks_to_await:
            results = await asyncio.gather(*tasks_to_await, return_exceptions=True)
            for i, res in enumerate(results):
                if isinstance(res, Exception): self.logger.error(f"Error in strategy {tasks_to_await[i].__self__.strategy_id} event handler: {res}") # type: ignore


    async def main_loop(self): await super().main_loop() # type: ignore
    async def shutdown(self): await super().shutdown() # type: ignore

if __name__ == '__main__':
    pass
```
