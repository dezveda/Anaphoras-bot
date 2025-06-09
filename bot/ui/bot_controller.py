import asyncio
import logging
from PySide6.QtCore import QObject, Slot
from typing import Dict, Optional, Any, List, Type, Tuple
import pandas as pd
import os

try:
    from bot.ui.qt_signals import signals
    from bot.connectors.binance_connector import BinanceAPI
    from bot.core.data_fetcher import MarketDataProvider
    from bot.core.order_executor import OrderManager
    from bot.core.risk_manager import BasicRiskManager
    from bot.strategies.strategy_engine import StrategyEngine
    from bot.strategies.base_strategy import BaseStrategy
    from bot.core.config_loader import ConfigManager # Changed to import ConfigManager class
    from bot.core.backtester import BacktestEngine
except ImportError as e:
    logging.basicConfig(level=logging.ERROR)
    logging.error(f"BotController ImportError: {e}")
    QObject = object # type: ignore
    def Slot(*args, **kwargs): return lambda f: f # type: ignore
    BinanceAPI = MarketDataProvider = OrderManager = BasicRiskManager = StrategyEngine = BaseStrategy = BacktestEngine = ConfigManager = type('MissingType', (), {}) # type: ignore
    class MockSignals: # type: ignore
        def __getattr__(self, name):
            def _emitter(*args, **kwargs): pass
            return _emitter
    signals = MockSignals() # type: ignore


class BotController(QObject):
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger('algo_trader_bot.BotController')
        self.signals = signals

        # Determine project root and paths for config files
        project_root_guess = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../'))
        env_file_path = os.path.join(project_root_guess, '.env')
        json_config_path = os.path.join(project_root_guess, 'bot_config.json')

        self.config_manager = ConfigManager(config_file_path=json_config_path, env_file_path=env_file_path)

        self.binance_connector: Optional[BinanceAPI] = None
        self.market_data_provider: Optional[MarketDataProvider] = None
        self.order_manager: Optional[OrderManager] = None
        self.risk_manager: Optional[BasicRiskManager] = None
        self.strategy_engine: Optional[StrategyEngine] = None

        self.bot_status: str = "Uninitialized"
        self.is_running: bool = False
        self.loop: Optional[asyncio.AbstractEventLoop] = None

        log_level_val = self.config_manager.load_log_level_from_env() # Initial log level from .env
        self.current_log_level_str: str = logging.getLevelName(log_level_val)
        self.logger.info(f"BotController instance created. .env path: {self.config_manager.env_file_path}, JSON config path: {self.config_manager.config_file_path}")
        self.load_persistent_config() # Load general settings and strategies early

    async def async_setup(self, use_testnet: bool = True): # API keys now loaded internally via ConfigManager
        self.logger.info(f"BotController: Starting async setup (Testnet: {use_testnet})...")
        self.signals.status_updated.emit("Initializing...")
        try:
            api_key, api_secret = self.config_manager.load_api_keys(use_testnet=use_testnet)
            if not api_key or not api_secret:
                self.logger.error(f"API key/secret not found for {'Testnet' if use_testnet else 'Mainnet'}. Check .env file.")
                self.signals.api_connection_updated.emit("API Keys Missing")
                self.signals.status_updated.emit("Error: API Keys Missing")
                return

            self.binance_connector = BinanceAPI(api_key=api_key, api_secret=api_secret, testnet=use_testnet)
            server_time_resp = await self.binance_connector.get_server_time()
            self.logger.info(f"Binance API connection successful. Server time: {server_time_resp.get('serverTime')}")
            self.signals.api_connection_updated.emit("API Connected")

            self.market_data_provider = MarketDataProvider(self.binance_connector)
            self.order_manager = OrderManager(self.binance_connector, self.market_data_provider, risk_manager=None)
            self.risk_manager = BasicRiskManager(
                account_balance_provider_fn=self.order_manager.get_available_trading_balance,
                default_risk_per_trade_perc=0.01 # This can be overridden by loaded config
            )
            self.order_manager.risk_manager = self.risk_manager
            self.strategy_engine = StrategyEngine(self.order_manager, self.market_data_provider, self.risk_manager)
            self.strategy_engine.live_trading_mode = True # Default to live for BotController

            self._connect_internal_signals()
            # Reload strategies from config AFTER all components are initialized
            self.load_persistent_config() # This will load and potentially log strategies

            self.logger.info("BotController: Core components initialized.")
            self.signals.status_updated.emit("Initialized / Idle")
            self.signals.log_message_appended.emit("Bot backend initialized successfully.")

            if self.market_data_provider.subscribe_to_user_data(self.handle_user_data_from_mdp):
                 self.logger.info("User Data Stream subscription initiated by BotController setup.")
                 await asyncio.sleep(2); await self.update_dashboard_balance() # Initial balance update
            else:
                 self.logger.error("Failed to initiate User Data Stream subscription during setup.")
                 self.signals.api_connection_updated.emit("User Stream Failed")
            if self.market_data_provider:
                await self.market_data_provider.subscribe_to_mark_price_stream("BTCUSDT", self.handle_btc_mark_price_update)
        except Exception as e:
            self.logger.error(f"Error during backend async setup: {e}", exc_info=True)
            self.signals.status_updated.emit(f"Error: Setup Failed"); self.signals.api_connection_updated.emit(f"API Error")
            self.signals.log_message_appended.emit(f"Backend setup failed: {e}")

    def load_persistent_config(self):
        self.logger.info("BotController: Loading persistent configuration...")
        app_config = self.config_manager.load_app_config()
        if app_config:
            general_settings = app_config.get('general_settings', {})
            self.current_log_level_str = general_settings.get('log_level', self.current_log_level_str)
            # Note: Actual logger level update needs call to setup_logger or logger.setLevel
            self.logger.info(f"Loaded general settings. Log level from config: {self.current_log_level_str}")
            # Apply other general settings if any

            if self.strategy_engine: # Ensure strategy engine is initialized
                loaded_strategies_config = app_config.get('strategies', {})
                if not loaded_strategies_config:
                     self.logger.info("No strategies found in configuration file.")
                else:
                    self.logger.info(f"Found {len(loaded_strategies_config)} strategies in configuration.")

                for strategy_id, config_item in loaded_strategies_config.items():
                    strategy_type_name = config_item.get('type_name')
                    params = config_item.get('params')
                    strategy_class = self.strategy_engine.get_available_strategy_types().get(strategy_type_name) # type: ignore
                    if strategy_class and params:
                        self.logger.debug(f"Loading strategy {strategy_id} (type: {strategy_type_name}) from config with params: {params}")
                        self.strategy_engine.load_strategy(strategy_class, strategy_id, params)
                    else:
                        self.logger.warning(f"Could not load strategy {strategy_id} from config: Type '{strategy_type_name}' not found or params missing.")
            else:
                self.logger.warning("StrategyEngine not available for loading persistent strategy configs.")
            self.signals.log_message_appended.emit("Loaded configuration from file.")
        else:
            self.signals.log_message_appended.emit("No configuration file found or error loading. Using defaults.")


    def save_persistent_config(self):
        self.logger.info("BotController: Saving persistent configuration...")
        if not self.config_manager or not self.strategy_engine:
            self.logger.error("ConfigManager or StrategyEngine not available. Cannot save config.")
            return

        general_settings = {'log_level': self.current_log_level_str} # Add other general settings here

        strategies_config = {}
        for strategy_id, strategy_instance in self.strategy_engine.strategies.items():
            strategies_config[strategy_id] = {
                'type_name': strategy_instance.params.get('strategy_type_name', strategy_instance.__class__.__name__), # Ensure type_name is in params
                'params': strategy_instance.params
            }

        app_config_to_save = {'general_settings': general_settings, 'strategies': strategies_config}
        self.config_manager.save_app_config(app_config_to_save)
        self.signals.log_message_appended.emit("Current configuration saved.")


    # --- Config Methods for UI ---
    def get_general_settings(self) -> dict:
        # This now primarily returns current state; loading happens at init or refresh
        # Persistent log level is in self.current_log_level_str after load_persistent_config
        return {'log_level': self.current_log_level_str}

    def save_general_settings(self, settings: dict): # Called by UI
        new_log_level = settings.get('log_level')
        if new_log_level and new_log_level != self.current_log_level_str:
            self.current_log_level_str = new_log_level # Update in-memory state
            # Actual saving to file now happens via save_persistent_config
            self.save_persistent_config()
            self.signals.log_message_appended.emit(f"Log level set to {new_log_level} and config saved. Restart required to apply log level globally.")
        else:
            self.signals.log_message_appended.emit("No changes in general settings or log level.")


    def get_api_keys_config(self) -> dict: # For UI to display non-sensitive parts
        if not self.config_manager: return {'testnet_key': '', 'mainnet_key': ''}
        tn_key, _ = self.config_manager.load_api_keys(use_testnet=True)
        mn_key, _ = self.config_manager.load_api_keys(use_testnet=False)
        return {'testnet_key': tn_key or '', 'mainnet_key': mn_key or ''}

    def save_api_keys(self, testnet_key: str, testnet_secret: str, mainnet_key: str, mainnet_secret: str): # Called by UI
        if not self.config_manager: self.logger.error("ConfigManager not available for saving API keys."); return
        self.logger.info(f"BotController: UI request to save API keys.")
        changes_made = False
        if testnet_key is not None and (testnet_key or testnet_secret): # Save if key is provided or secret is to be updated/cleared
            if self.config_manager.save_api_key_to_env("BINANCE_TESTNET_API_KEY", testnet_key or ""): changes_made = True
            if testnet_secret: # Only save secret if field was not empty
                 if self.config_manager.save_api_key_to_env("BINANCE_TESTNET_API_SECRET", testnet_secret): changes_made = True
        if mainnet_key is not None and (mainnet_key or mainnet_secret):
            if self.config_manager.save_api_key_to_env("BINANCE_MAINNET_API_KEY", mainnet_key or ""): changes_made = True
            if mainnet_secret:
                 if self.config_manager.save_api_key_to_env("BINANCE_MAINNET_API_SECRET", mainnet_secret): changes_made = True

        if changes_made: self.signals.log_message_appended.emit("API keys updated in .env. Restart required.")
        else: self.signals.log_message_appended.emit("No changes to API keys were saved (or fields were empty).")


    # ... (rest of BotController methods: test_api_connection, strategy management, UI requests, bot control, shutdown)
    # ... These should use self.strategy_engine, self.order_manager etc. as they are now initialized in async_setup.
    # ... Ensure all `async def` methods are awaited correctly if called from other async methods.
    # ... Ensure UI wrappers correctly use asyncio.create_task(self.actual_async_method())

    # (Keep existing methods for test_api_connection, strategy management, UI requests, bot control, shutdown)
    # Ensure they use the initialized components. For example, in add_new_strategy_instance:
    async def add_new_strategy_instance(self, strategy_type_name: str, strategy_id: str, params_from_ui: dict) -> bool:
        if not self.strategy_engine: self.logger.error("StrategyEngine not initialized."); return False
        # ... rest of the method
        # After successful load:
        # self.save_persistent_config() # Save config after adding a strategy
        # ...
        strategy_class = self.strategy_engine.get_available_strategy_types().get(strategy_type_name)
        if strategy_class and strategy_id and strategy_id not in self.strategy_engine.strategies:
            self.logger.info(f"Attempting to load strategy {strategy_id} (Type: {strategy_type_name}) with params: {params_from_ui}")
            success = self.strategy_engine.load_strategy(strategy_class, strategy_id, params_from_ui)
            if success:
                self.signals.log_message_appended.emit(f"Strategy {strategy_id} ({strategy_type_name}) added.")
                self.save_persistent_config() # Save after successful addition
            else: self.signals.log_message_appended.emit(f"Failed to load strategy {strategy_id}.")
            return success
        self.signals.log_message_appended.emit(f"Failed to add strategy {strategy_id}. Check ID/type. Type: {strategy_type_name}, ID: {strategy_id}")
        return False


    async def update_strategy_parameters(self, strategy_id: str, params_from_ui: dict) -> bool:
        if not self.strategy_engine: self.logger.error("StrategyEngine not initialized."); return False
        self.logger.info(f"Attempting to update params for strategy {strategy_id}: {params_from_ui}")
        success = self.strategy_engine.update_strategy_parameters(strategy_id, params_from_ui)
        if success:
            self.signals.log_message_appended.emit(f"Params for {strategy_id} updated. Restart strategy if it was active for changes to take full effect.")
            self.save_persistent_config() # Save after successful update
        else: self.signals.log_message_appended.emit(f"Failed to update params for {strategy_id}.")
        return success

    async def remove_strategy_instance(self, strategy_id: str) -> bool:
        if not self.strategy_engine: self.logger.error("StrategyEngine not initialized."); return False
        self.logger.info(f"Attempting to remove strategy {strategy_id}")
        success = await self.strategy_engine.remove_strategy(strategy_id)
        if success:
            self.signals.log_message_appended.emit(f"Strategy {strategy_id} removed.")
            self.save_persistent_config() # Save after successful removal
        else: self.signals.log_message_appended.emit(f"Failed to remove strategy {strategy_id}.")
        return success

    # Keep other methods like get_historical_klines_for_chart, bot controls, shutdown as they are
    async def get_historical_klines_for_chart(self, symbol: str, timeframe: str, limit: int = 100) -> Optional[pd.DataFrame]:
        if not self.market_data_provider: self.logger.warning("MarketDataProvider not available for chart data."); return None
        try: return await self.market_data_provider.get_historical_klines(symbol=symbol, interval=timeframe, limit=limit)
        except Exception as e: self.logger.error(f"Error in get_historical_klines_for_chart: {e}", exc_info=True); return None
    @Slot()
    def start_bot_async_wrapper(self):
        self.logger.info("UI Action: Start Bot wrapper.")
        if self.loop and self.loop.is_running(): asyncio.create_task(self.start_bot())
        else: self.logger.error("No running event loop for start_bot.")
    async def start_bot(self):
        if self.is_running: self.logger.warning("Bot already running."); self.signals.log_message_appended.emit("Bot is already running."); return
        if not all([self.strategy_engine, self.market_data_provider, self.binance_connector, self.order_manager, self.risk_manager]):
             self.logger.error("Core components not initialized."); self.signals.log_message_appended.emit("Error: Bot components not ready."); return
        self.logger.info("BotController: Starting bot operations..."); self.is_running = True; self.signals.status_updated.emit("Starting...")
        if self.binance_connector and not self.binance_connector.user_data_control_flag.get('keep_running'):
            self.logger.info("User data stream seems not active, ensuring subscriptions are processed by MDP...")
            self.market_data_provider.subscribe_to_user_data(self.handle_user_data_from_mdp)
            if self.order_manager : self.market_data_provider.subscribe_to_user_data(self.order_manager.handle_order_update)
            if self.strategy_engine : self.market_data_provider.subscribe_to_user_data(self.strategy_engine.handle_user_data_for_strategies)
            await asyncio.sleep(2)
        if self.strategy_engine: await self.strategy_engine.start_all_strategies()
        self.signals.status_updated.emit("Running"); self.signals.log_message_appended.emit("Bot and strategies started.")
    @Slot()
    def stop_bot_async_wrapper(self):
        self.logger.info("UI Action: Stop Bot wrapper.")
        if self.loop and self.loop.is_running(): asyncio.create_task(self.stop_bot())
        else: self.logger.error("No running event loop for stop_bot.")
    async def stop_bot(self):
        if not self.is_running: self.logger.info("Bot not running."); return
        self.logger.info("BotController: Stopping bot operations..."); self.signals.status_updated.emit("Stopping...")
        if self.strategy_engine: await self.strategy_engine.stop_all_strategies()
        self.is_running = False
        self.signals.status_updated.emit("Stopped"); self.signals.log_message_appended.emit("Bot and strategies stopped.")
    async def shutdown(self):
        self.logger.info("BotController initiating full shutdown..."); await self.stop_bot()
        if self.market_data_provider: await self.market_data_provider.unsubscribe_all_streams()
        self.save_persistent_config() # Save config on graceful shutdown
        self.logger.info("BotController shutdown complete.")
    # Methods for request_open_orders_update, request_trade_history_update, request_positions_update,
    # cancel_order_ui, close_position_ui, get_loaded_strategies_info etc. from previous steps should be here too.
    # They are mostly okay, ensure they use the initialized components.
    async def request_open_orders_update(self):
        if not self.order_manager: self.logger.warning("OM not init for open orders."); return
        orders = await self.order_manager.get_open_orders_data_for_ui()
        self.signals.open_orders_updated.emit(orders or [])
    async def request_trade_history_update(self, symbol='BTCUSDT', limit=50):
        if not self.order_manager: self.logger.warning("OM not init for trade history."); return
        history = await self.order_manager.get_trade_history_data_for_ui(symbol, limit)
        self.signals.trade_history_updated.emit(history or [])
    async def request_positions_update(self):
        if not self.order_manager: self.logger.warning("OM not init for positions."); return
        positions = await self.order_manager.get_position_data_for_ui()
        self.signals.positions_updated.emit(positions or [])
    async def cancel_order_ui(self, order_id_str: str, symbol: str):
        if not self.order_manager: self.logger.error("OM not available."); return
        self.logger.info(f"BC: UI cancel order {order_id_str} for {symbol}")
        order_id_int: Optional[int]=None; client_order_id: Optional[str]=None
        if order_id_str.isdigit(): order_id_int = int(order_id_str)
        else: client_order_id = order_id_str
        response = await self.order_manager.cancel_existing_order(symbol=symbol, orderId=order_id_int, origClientOrderId=client_order_id)
        msg=f"Order {order_id_str} ({symbol}) "; msg += "cancelled." if response and response.get('status')=='CANCELED' else f"cancel failed: {response.get('msg') if response else 'No API response'}"
        self.signals.log_message_appended.emit(msg)
        if self.loop and self.loop.is_running(): asyncio.create_task(self.request_open_orders_update())
    async def close_position_ui(self, symbol: str, position_side_to_close: str):
        if not self.order_manager: self.logger.error("OM not available."); return
        self.logger.info(f"BC: UI close {position_side_to_close} position for {symbol}")
        response = await self.order_manager.close_position_market(symbol, position_side_to_close)
        msg=f"Market close for {position_side_to_close} {symbol} "; msg += "placed." if response and (response.get('status')=='FILLED' or response.get('status')=='NEW') else f"failed: {response.get('msg') if response else 'No API response'}"
        self.signals.log_message_appended.emit(msg); await asyncio.sleep(1)
        if self.loop and self.loop.is_running(): asyncio.create_task(self.request_positions_update()); asyncio.create_task(self.request_open_orders_update())

```
