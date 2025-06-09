import logging
import asyncio
from typing import Dict, Type, Any, Optional

# Assuming BaseStrategy, OrderManager, MarketDataProvider will be correctly imported
# when the whole 'bot' package is structured.
try:
    from bot.strategies.base_strategy import BaseStrategy
    from bot.core.order_executor import OrderManager
    from bot.core.data_fetcher import MarketDataProvider
except ImportError: # Fallback for potential local test scenarios or path issues
    from .base_strategy import BaseStrategy
    # Adjust path if core is not directly accessible like this in tests
    # This might require more robust path handling in a real test setup
    import sys, os
    sys.path.append(os.path.join(os.path.dirname(__file__), '../core'))
    from order_executor import OrderManager
    from data_fetcher import MarketDataProvider


class StrategyEngine:
    def __init__(self,
                 order_manager: OrderManager,
                 market_data_provider: MarketDataProvider,
                 logger_name: str = 'algo_trader_bot'):
        self.order_manager = order_manager
        self.market_data_provider = market_data_provider
        self.logger = logging.getLogger(logger_name)

        self.strategies: Dict[str, BaseStrategy] = {}
        # self.strategy_tasks: Dict[str, asyncio.Task] = {} # For managing async tasks of strategies if needed

        # Register with MarketDataProvider to receive user data (especially order updates)
        # This callback will then distribute to relevant strategies.
        self.market_data_provider.subscribe_to_user_data(
            general_user_data_callback=None, # Or a generic handler if needed
            order_update_callback=self._distribute_order_update_to_strategies
        )
        self.logger.info("StrategyEngine initialized and subscribed to order updates from MarketDataProvider.")


    def load_strategy(self,
                      strategy_class: Type[BaseStrategy],
                      strategy_id: str,
                      params: Dict[str, Any]) -> bool:
        if strategy_id in self.strategies:
            self.logger.warning(f"Strategy with ID '{strategy_id}' already loaded. Skipping.")
            return False

        try:
            # Pass the shared logger instance to the strategy
            strategy_instance = strategy_class(
                strategy_id=strategy_id,
                params=params,
                order_manager=self.order_manager,
                market_data_provider=self.market_data_provider,
                logger=self.logger # Pass the engine's logger or a child logger
            )
            self.strategies[strategy_id] = strategy_instance
            self.logger.info(f"Strategy '{strategy_id}' of type {strategy_class.__name__} loaded successfully.")
            return True
        except Exception as e:
            self.logger.error(f"Failed to load strategy '{strategy_id}': {e}", exc_info=True)
            return False

    async def start_strategy(self, strategy_id: str):
        if strategy_id not in self.strategies:
            self.logger.error(f"Cannot start strategy '{strategy_id}': Not found.")
            return

        strategy = self.strategies[strategy_id]
        if strategy.is_active:
            self.logger.info(f"Strategy '{strategy_id}' is already active.")
            return

        self.logger.info(f"Starting strategy '{strategy_id}'...")
        try:
            await strategy.start() # Strategy's start method should handle its subscriptions
            self.logger.info(f"Strategy '{strategy_id}' started successfully.")
        except Exception as e:
            self.logger.error(f"Error starting strategy '{strategy_id}': {e}", exc_info=True)
            strategy.is_active = False # Ensure it's marked as inactive on error

    async def stop_strategy(self, strategy_id: str):
        if strategy_id not in self.strategies:
            self.logger.error(f"Cannot stop strategy '{strategy_id}': Not found.")
            return

        strategy = self.strategies[strategy_id]
        if not strategy.is_active:
            self.logger.info(f"Strategy '{strategy_id}' is not active.")
            return

        self.logger.info(f"Stopping strategy '{strategy_id}'...")
        try:
            await strategy.stop() # Strategy's stop method should handle unsubscriptions
            self.logger.info(f"Strategy '{strategy_id}' stopped successfully.")
        except Exception as e:
            self.logger.error(f"Error stopping strategy '{strategy_id}': {e}", exc_info=True)
        finally:
             strategy.is_active = False


    async def start_all_strategies(self):
        self.logger.info("Starting all loaded strategies...")
        for strategy_id in self.strategies.keys():
            await self.start_strategy(strategy_id)
        self.logger.info("Finished attempting to start all strategies.")

    async def stop_all_strategies(self):
        self.logger.info("Stopping all active strategies...")
        for strategy_id in self.strategies.keys():
            if self.strategies[strategy_id].is_active:
                await self.stop_strategy(strategy_id)
        self.logger.info("Finished attempting to stop all strategies.")

    def _distribute_order_update_to_strategies(self, order_update_data: Dict):
        """
        Callback for MarketDataProvider's user data stream, specifically for order updates.
        It distributes the order update to all active strategies.
        """
        # This method is called by MarketDataProvider (from a thread)
        # It needs to schedule the async on_order_update method for each strategy
        self.logger.debug(f"StrategyEngine distributing order update: {order_update_data.get('c', order_update_data.get('i'))}")

        # Strategies are responsible for filtering if the update is relevant to them
        for strategy_id, strategy_instance in self.strategies.items():
            if strategy_instance.is_active:
                self.logger.debug(f"Forwarding order update to strategy: {strategy_id}")
                # Use asyncio.create_task if called from an async context,
                # or ensure the strategy's on_order_update is thread-safe / uses run_coroutine_threadsafe
                # For now, assuming this callback itself might not be in an asyncio loop,
                # we might need a way to run the async strategy methods.
                # This is a common challenge with mixed sync/async code.
                # If StrategyEngine methods like start/stop are run in an asyncio loop,
                # then we can use asyncio.create_task.
                # For simplicity now, let's assume the callback should schedule the async method.
                # This part might need an asyncio loop running in the StrategyEngine or main application.
                # For now, let's just call it directly if it were synchronous or handle the async call appropriately.

                # A simple way for now (if an event loop is running in the thread that calls this):
                # asyncio.create_task(strategy_instance.on_order_update(order_update_data))
                # However, MarketDataProvider's user stream callback is run in a sync thread.
                # So, we'd need to use `asyncio.run_coroutine_threadsafe` if strategies are truly async
                # and an event loop is running in the main thread or a dedicated asyncio thread.
                # For now, let's log a placeholder. This needs robust async handling.
                self.logger.info(f"Placeholder: Strategy {strategy_id} would process order update (async call needed).")
                # In a full async app, this would be:
                # loop = asyncio.get_event_loop() # Or a specific loop
                # asyncio.run_coroutine_threadsafe(strategy_instance.on_order_update(order_update_data), loop)


    # Example of how strategies might ask the engine to subscribe them to data
    # This is generally better handled within the strategy's start() method itself.
    # async def request_market_data_subscription(self, strategy_id: str, symbol: str, data_type: str, interval: Optional[str] = None):
    #     strategy = self.strategies.get(strategy_id)
    #     if not strategy:
    #         self.logger.error(f"Strategy {strategy_id} not found for data subscription.")
    #         return

    #     self.logger.info(f"Strategy {strategy_id} requesting {data_type} for {symbol}@{interval if interval else ''}")
    #     if data_type == "kline":
    #         if not interval: self.logger.error("Interval required for kline subscription"); return
    #         # The lambda now correctly captures symbol and interval for this specific subscription
    #         await self.market_data_provider.subscribe_to_kline_stream(
    #             symbol, interval,
    #             lambda k_data, s=symbol, i=interval: asyncio.create_task(strategy.on_kline_update(s, i, k_data))
    #         )
    #     # Add other data types (depth, trade, etc.)
    #     else:
    #         self.logger.warning(f"Data type {data_type} not yet supported for direct engine subscription.")


if __name__ == '__main__':
    # This is a very basic test, assuming other components are available and configured.
    # In a real application, these would be initialized and managed by a main bot class.

    # Setup basic logging for the test
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger('algo_trader_bot')

    # Mock objects for dependencies (replace with actual instances in a real app)
    class MockBinanceConnector:
        def __init__(self, api_key=None, api_secret=None, testnet=False):
            self.user_data_control_flag = {} # Simulate this attribute
            self.logger = logging.getLogger('algo_trader_bot.MockConnector')
        def start_user_stream(self, callback): self.logger.info("Mock User Stream Started."); return True
        def stop_user_stream(self): self.logger.info("Mock User Stream Stopped.")
        def start_market_stream(self, stream_names, callback): self.logger.info(f"Mock Market Stream {stream_names} Started."); return "mock_stream_id"
        def stop_market_stream(self, stream_id): self.logger.info(f"Mock Market Stream {stream_id} Stopped.")


    class MockMarketDataProvider:
        def __init__(self, connector):
            self.binance_connector = connector
            self.logger = logging.getLogger('algo_trader_bot.MockMDP')
            self.user_data_callbacks = [] # Simulate this

        def subscribe_to_user_data(self, general_user_data_callback=None, order_update_callback=None):
            if order_update_callback:
                self.user_data_callbacks.append(order_update_callback) # Simplified for test
                self.logger.info(f"MDP: Registered order update callback: {order_update_callback.__name__}")
            # Simulate starting the stream in connector
            self.binance_connector.start_user_stream(self._handle_mock_user_data)

        def _handle_mock_user_data(self, data): # This is what connector's user stream would call
            for cb in self.user_data_callbacks:
                cb(data)

        async def subscribe_to_kline_stream(self, symbol, interval, callback):
            self.logger.info(f"Mock MDP: Subscribed to kline {symbol} {interval}")
            # In real scenario, would use self.binance_connector.start_market_stream
            # and register the callback (passed to _handle_market_message which then calls strategy's on_kline_update)
            pass # For this test, strategy's start will just log.

    # Dummy Strategy for testing
    class MyTestStrategy(BaseStrategy):
        async def on_kline_update(self, symbol: str, interval: str, kline_data: Dict):
            self.logger.info(f"{self.strategy_id}: Received kline for {symbol}@{interval}: C={kline_data.get('c')}")
        async def on_depth_update(self, symbol: str, depth_data: Dict): pass
        async def on_trade_update(self, symbol: str, trade_data: Dict): pass
        async def on_mark_price_update(self, symbol: str, mark_price_data: Dict): pass
        async def on_order_update(self, order_update: Dict):
            self.logger.info(f"{self.strategy_id}: Received order update: {order_update.get('c')}, Status: {order_update.get('X')}")
        async def start(self):
            await super().start() # Call base start
            self.logger.info(f"{self.strategy_id} specific start logic. Subscribing to data...")
            # Example: self.market_data_provider.subscribe_to_kline_stream("BTCUSDT", "1m", self.on_kline_update)
            # For this test, we'll assume subscriptions are managed via MarketDataProvider methods called here.
            # The lambda structure in the original plan for StrategyEngine._subscribe_strategy_to_data
            # is a good way to ensure the strategy's methods are correctly called.
            # Here, we'll just log.
            self.logger.info(f"{self.strategy_id} would subscribe to BTCUSDT@kline_1m now.")
            # await self.market_data_provider.subscribe_to_kline_stream(
            #     "BTCUSDT", "1m",
            #     lambda data: asyncio.create_task(self.on_kline_update("BTCUSDT", "1m", data)) # Correct async call
            # )

        async def stop(self):
            await super().stop() # Call base stop
            self.logger.info(f"{self.strategy_id} specific stop logic. Unsubscribing...")


    async def main_test():
        mock_connector = MockBinanceConnector()
        mock_mdp = MockMarketDataProvider(mock_connector)

        # OrderManager needs a real connector for most ops, but for this test,
        # we are focusing on StrategyEngine interaction with order updates.
        # We can pass the mock_connector to OrderManager for limited testing.
        mock_order_manager = OrderManager(mock_connector, mock_mdp) # type: ignore

        engine = StrategyEngine(mock_order_manager, mock_mdp)

        engine.load_strategy(MyTestStrategy, "test_strat_01", {"param1": 10, "symbol": "BTCUSDT"})

        await engine.start_strategy("test_strat_01")

        # Simulate an order update coming from MarketDataProvider (which got it from BinanceConnector user stream)
        logger.info("\nSimulating an order update distribution...")
        mock_order_event_data = {
            "e": "ORDER_TRADE_UPDATE",
            "T": time.time() * 1000,
            "E": time.time() * 1000,
            "o": {
                "s": "BTCUSDT",
                "c": "test_client_id_123", # clientOrderId
                "i": 12345, # orderId
                "X": "NEW", # status
                "x": "NEW", # execution type
                # ... other fields
            }
        }
        # This callback is registered by StrategyEngine with MDP
        engine._distribute_order_update_to_strategies(mock_order_event_data['o'])

        await asyncio.sleep(2) # Give time for logs

        await engine.stop_strategy("test_strat_01")

    if __name__ == '__main__':
        asyncio.run(main_test())

```
