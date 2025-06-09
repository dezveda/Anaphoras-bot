import logging
import asyncio
from typing import Dict, Type, Any, Optional

try:
    from bot.strategies.base_strategy import BaseStrategy
    from bot.core.order_executor import OrderManager
    from bot.core.data_fetcher import MarketDataProvider
    from bot.core.risk_manager import BasicRiskManager # Import BasicRiskManager
except ImportError:
    from .base_strategy import BaseStrategy
    import sys, os
    sys.path.append(os.path.join(os.path.dirname(__file__), '../core'))
    from order_executor import OrderManager # type: ignore
    from data_fetcher import MarketDataProvider # type: ignore
    from risk_manager import BasicRiskManager # type: ignore


class StrategyEngine:
    def __init__(self,
                 order_manager: OrderManager,
                 market_data_provider: MarketDataProvider,
                 risk_manager: BasicRiskManager, # Added risk_manager
                 logger_name: str = 'algo_trader_bot'):
        self.order_manager = order_manager
        self.market_data_provider = market_data_provider
        self.risk_manager = risk_manager # Store risk_manager
        self.logger = logging.getLogger(logger_name)

        self.strategies: Dict[str, BaseStrategy] = {}

        # Register _distribute_order_update_to_strategies with MarketDataProvider
        # This method will be called by MDP when any user data event occurs.
        self.market_data_provider.subscribe_to_user_data(
            user_data_event_callback=self._distribute_user_data_to_strategies
        )
        self.logger.info("StrategyEngine initialized and subscribed to user data events from MarketDataProvider.")

    def load_strategy(self,
                      strategy_class: Type[BaseStrategy],
                      strategy_id: str,
                      params: Dict[str, Any]) -> bool:
        if strategy_id in self.strategies:
            self.logger.warning(f"Strategy with ID '{strategy_id}' already loaded. Skipping.")
            return False

        try:
            strategy_instance = strategy_class(
                strategy_id=strategy_id,
                params=params,
                order_manager=self.order_manager,
                market_data_provider=self.market_data_provider,
                risk_manager=self.risk_manager, # Pass risk_manager to strategy
                logger=self.logger
            )
            self.strategies[strategy_id] = strategy_instance
            self.logger.info(f"Strategy '{strategy_id}' of type {strategy_class.__name__} loaded successfully.")
            return True
        except Exception as e:
            self.logger.error(f"Failed to load strategy '{strategy_id}': {e}", exc_info=True)
            return False

    async def start_strategy(self, strategy_id: str):
        # ... (rest of the method remains the same)
        if strategy_id not in self.strategies:
            self.logger.error(f"Cannot start strategy '{strategy_id}': Not found.")
            return

        strategy = self.strategies[strategy_id]
        if strategy.is_active:
            self.logger.info(f"Strategy '{strategy_id}' is already active.")
            return

        self.logger.info(f"Starting strategy '{strategy_id}'...")
        try:
            await strategy.start()
            self.logger.info(f"Strategy '{strategy_id}' started successfully.")
        except Exception as e:
            self.logger.error(f"Error starting strategy '{strategy_id}': {e}", exc_info=True)
            strategy.is_active = False

    async def stop_strategy(self, strategy_id: str):
        # ... (rest of the method remains the same)
        if strategy_id not in self.strategies:
            self.logger.error(f"Cannot stop strategy '{strategy_id}': Not found.")
            return

        strategy = self.strategies[strategy_id]
        if not strategy.is_active:
            self.logger.info(f"Strategy '{strategy_id}' is not active.")
            return

        self.logger.info(f"Stopping strategy '{strategy_id}'...")
        try:
            await strategy.stop()
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
            if self.strategies[strategy_id].is_active: # Check if strategy is active before stopping
                await self.stop_strategy(strategy_id)
        self.logger.info("Finished attempting to stop all strategies.")

    def _distribute_user_data_to_strategies(self, user_data_event: Dict):
        """
        Callback for MarketDataProvider's user data stream.
        It distributes relevant events (like ORDER_TRADE_UPDATE) to all active strategies.
        """
        event_type = user_data_event.get('e')
        if event_type == 'ORDER_TRADE_UPDATE':
            order_data = user_data_event.get('o', {}) # Actual order data is in 'o' field
            self.logger.debug(f"StrategyEngine distributing ORDER_TRADE_UPDATE: ClientOrderID={order_data.get('c')}, OrderID={order_data.get('i')}")

            for strategy_id, strategy_instance in self.strategies.items():
                if strategy_instance.is_active:
                    self.logger.debug(f"Forwarding order update to strategy: {strategy_id}")
                    # Schedule the async on_order_update method.
                    # This assumes an event loop is running in the thread where this callback is executed,
                    # or that the strategy's on_order_update can handle being called from a sync context
                    # if it needs to interact with an asyncio loop (e.g., using asyncio.run_coroutine_threadsafe).
                    # Since MarketDataProvider's user stream runs in a thread that starts its own asyncio loop
                    # for websockets.connect, and this callback is called from there, we can use create_task.
                    try:
                        # This is tricky. The callback from MDP is sync. The strategy method is async.
                        # We need to ensure there's an event loop available for create_task.
                        # The thread started by BinanceConnector for user stream runs an asyncio loop.
                        # This should work if this method is called from that thread's loop.
                        asyncio.create_task(strategy_instance.on_order_update(order_data))
                    except RuntimeError as e:
                        self.logger.error(f"RuntimeError creating task for strategy {strategy_id} on_order_update (is an event loop running in this thread?): {e}")
                        # Fallback or alternative: schedule via a known loop if available
                        # main_loop = asyncio.get_main_loop() # This might not be the right loop
                        # if main_loop.is_running():
                        #    asyncio.run_coroutine_threadsafe(strategy_instance.on_order_update(order_data), main_loop)
                        # else:
                        #    self.logger.error("No running event loop found to schedule strategy.on_order_update")
        # Can add handling for other user data events like ACCOUNT_UPDATE if strategies need them directly


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(module)s - %(funcName)s - %(message)s')
    logger = logging.getLogger('algo_trader_bot')

    # --- Mock Objects ---
    class MockBinanceConnector:
        def __init__(self, api_key=None, api_secret=None, testnet=False):
            self.user_data_control_flag = {}
            self.logger = logging.getLogger('algo_trader_bot.MockConnector')
        async def get_account_balance(self): return [{'asset': 'USDT', 'availableBalance': '10000.0'}]
        def start_user_stream(self, callback): self.logger.info("Mock User Stream Started."); self.user_data_control_flag['keep_running'] = True; return True
        def stop_user_stream(self): self.logger.info("Mock User Stream Stopped."); self.user_data_control_flag['keep_running'] = False
        async def place_order(self, **kwargs): self.logger.info(f"Mock Place Order: {kwargs}"); return {"status": "NEW", "orderId": 123, "clientOrderId": kwargs.get("newClientOrderId")}
        # Add other async methods if strategies call them directly via order_manager

    class MockMarketDataProvider:
        def __init__(self, connector):
            self.binance_connector = connector
            self.logger = logging.getLogger('algo_trader_bot.MockMDP')
            self.user_data_event_callbacks = []
        def subscribe_to_user_data(self, user_data_event_callback: Callable):
            if user_data_event_callback:
                self.user_data_event_callbacks.append(user_data_event_callback)
                self.logger.info(f"MockMDP: Registered user data event callback: {user_data_event_callback.__name__}")
            self.binance_connector.start_user_stream(self._internal_user_data_handler)
        def _internal_user_data_handler(self, data): # Simulates connector calling this
            for cb in self.user_data_event_callbacks: cb(data)
        async def subscribe_to_kline_stream(self, symbol, interval, callback): self.logger.info(f"MockMDP: Kline stream for {symbol} {interval} registered.")

    class MockRiskManager:
        def __init__(self, balance_provider): self.logger = logging.getLogger('algo_trader_bot.MockRM')
        async def calculate_position_size_usd(self, **kwargs): return 100.0 # Fixed USD size
        def calculate_quantity_from_risk_usd(self, **kwargs): return 0.001 # Fixed quantity
        async def validate_order_risk(self, **kwargs): return True # Always valid

    class MyAsyncTestStrategy(BaseStrategy):
        async def on_kline_update(self, symbol: str, interval: str, kline_data: Dict): self.logger.info(f"{self.strategy_id} Kline: {kline_data.get('c')}")
        async def on_depth_update(self, symbol: str, depth_data: Dict): pass
        async def on_trade_update(self, symbol: str, trade_data: Dict): pass
        async def on_mark_price_update(self, symbol: str, mark_price_data: Dict): pass
        async def on_order_update(self, order_update: Dict): self.logger.info(f"{self.strategy_id} Order Update: {order_update.get('c')} -> {order_update.get('X')}")
        async def start(self): await super().start(); self.logger.info(f"{self.strategy_id} started. Params: {self.params}")
        async def stop(self): await super().stop(); self.logger.info(f"{self.strategy_id} stopped.")

    async def main_engine_test():
        connector = MockBinanceConnector()
        mdp = MockMarketDataProvider(connector)
        # OrderManager now expects risk_manager. For this test, can pass a mock.
        # OrderManager's get_available_trading_balance is async.
        order_manager = OrderManager(connector, mdp, risk_manager=None) # type: ignore

        # RiskManager needs an async balance provider. OrderManager.get_available_trading_balance is now async.
        risk_manager = MockRiskManager(order_manager.get_available_trading_balance) # type: ignore
        order_manager.risk_manager = risk_manager # Assign it back if needed, or pass in constructor

        engine = StrategyEngine(order_manager, mdp, risk_manager) # Pass RM here
        engine.load_strategy(MyAsyncTestStrategy, "strat1", {"symbol": "BTCUSDT", "some_param": 50})

        await engine.start_all_strategies()

        logger.info("Simulating order update from MDP to Engine...")
        mock_order_event = {"e": "ORDER_TRADE_UPDATE", "o": {"c": "client_order_id_test", "X": "FILLED", "s": "BTCUSDT"}}
        # Simulate MDP's internal callback calling engine's callback
        # This is how StrategyEngine gets user data events
        engine._distribute_user_data_to_strategies(mock_order_event)

        await asyncio.sleep(1)
        await engine.stop_all_strategies()

    if __name__ == '__main__':
        asyncio.run(main_engine_test())

```
