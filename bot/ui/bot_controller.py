import asyncio
import logging
from PySide6.QtCore import QObject, Slot
from typing import Dict, Optional, Any, List, Type, Tuple
import pandas as pd
import os
import time # For timestamping position updates for chart

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
        self.current_chart_kline_subscription_id: Optional[str] = None # For live chart updates
        self.subscribed_mark_price_for_pnl = set() # Keep track of symbols subscribed for P&L mark price

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
            if self.order_manager: # Set P&L update callback
                self.order_manager.pnl_update_callback = self.trigger_pnl_emission

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
                 await asyncio.sleep(2) # Give some time for user stream to potentially connect/stabilize
                 await self.update_dashboard_balance()
                 await self.request_positions_update(emit_for_chart=True) # Initial position update for chart and P&L
                 await self._subscribe_to_initial_mark_prices_for_pnl() # Subscribe to mark prices for P&L
            else:
                 self.logger.error("Failed to initiate User Data Stream subscription during setup.")
                 self.signals.api_connection_updated.emit("User Stream Failed")

            # Ensure BTCUSDT mark price is subscribed for the dashboard ticker, independently of P&L subscriptions.
            # If self.handle_btc_mark_price_update also handles P&L, this is fine.
            # Otherwise, ensure a separate call to subscribe to BTCUSDT for P&L if needed.
            if self.market_data_provider and "BTCUSDT" not in self.subscribed_mark_price_for_pnl:
                 await self.market_data_provider.subscribe_to_mark_price_stream(
                     "BTCUSDT",
                     self.handle_mark_price_for_pnl_passthrough # Use generic handler for P&L
                 )
                 self.subscribed_mark_price_for_pnl.add("BTCUSDT") # Track it
                 self.logger.info("Ensured BTCUSDT mark price subscription for dashboard/P&L.")

        except Exception as e:
            self.logger.error(f"Error during backend async setup: {e}", exc_info=True)
            self.signals.status_updated.emit(f"Error: Setup Failed")
            self.signals.api_connection_updated.emit(f"API Error")
            self.signals.log_message_appended.emit(f"Backend setup failed: {e}")
            # Emit error dialog for critical setup failure
            self.signals.error_dialog_requested.emit("Bot Initialization Failed",
                                                     f"Could not complete backend setup. Please check API keys and connectivity. Details: {e}")

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
            try:
                self.logger.info(f"Attempting to load strategy {strategy_id} (Type: {strategy_type_name}) with params: {params_from_ui}")
                success = self.strategy_engine.load_strategy(strategy_class, strategy_id, params_from_ui)
                if success:
                    self.signals.log_message_appended.emit(f"Strategy {strategy_id} ({strategy_type_name}) added.")
                    self.save_persistent_config() # Save after successful addition
                else:
                    self.signals.log_message_appended.emit(f"Failed to load strategy {strategy_id}.")
                    self.signals.error_dialog_requested.emit("Add Strategy Failed", f"Could not load strategy '{strategy_id}'. Check logs.")
                return success
            except Exception as e:
                self.logger.error(f"Exception adding strategy {strategy_id}: {e}", exc_info=True)
                self.signals.error_dialog_requested.emit("Add Strategy Failed", f"Exception while adding '{strategy_id}': {e}")
                return False
        self.signals.log_message_appended.emit(f"Failed to add strategy {strategy_id}. Check ID/type. Type: {strategy_type_name}, ID: {strategy_id}")
        return False

    async def update_strategy_parameters(self, strategy_id: str, params_from_ui: dict) -> bool:
        if not self.strategy_engine:
            self.logger.error("StrategyEngine not initialized for param update.")
            self.signals.error_dialog_requested.emit("Update Failed", "Strategy Engine not available.")
            return False
        try:
            self.logger.info(f"Attempting to update params for strategy {strategy_id}: {params_from_ui}")
            success = self.strategy_engine.update_strategy_parameters(strategy_id, params_from_ui)
            if success:
                self.signals.log_message_appended.emit(f"Params for {strategy_id} updated. Restart strategy if it was active for changes to take full effect.")
                self.save_persistent_config() # Save after successful update
            else:
                self.signals.log_message_appended.emit(f"Failed to update params for {strategy_id}.")
                self.signals.error_dialog_requested.emit("Update Failed", f"Could not update parameters for '{strategy_id}'.")
            return success
        except Exception as e:
            self.logger.error(f"Exception updating strategy params for {strategy_id}: {e}", exc_info=True)
            self.signals.error_dialog_requested.emit("Update Failed", f"Exception while updating '{strategy_id}': {e}")
            return False

    async def remove_strategy_instance(self, strategy_id: str) -> bool:
        if not self.strategy_engine:
            self.logger.error("StrategyEngine not initialized for strategy removal.")
            self.signals.error_dialog_requested.emit("Remove Failed", "Strategy Engine not available.")
            return False
        try:
            self.logger.info(f"Attempting to remove strategy {strategy_id}")
            success = await self.strategy_engine.remove_strategy(strategy_id)
            if success:
                self.signals.log_message_appended.emit(f"Strategy {strategy_id} removed.")
                self.save_persistent_config() # Save after successful removal
            else:
                self.signals.log_message_appended.emit(f"Failed to remove strategy {strategy_id}.")
                self.signals.error_dialog_requested.emit("Remove Failed", f"Could not remove strategy '{strategy_id}'.")
            return success
        except Exception as e:
            self.logger.error(f"Exception removing strategy {strategy_id}: {e}", exc_info=True)
            self.signals.error_dialog_requested.emit("Remove Failed", f"Exception while removing '{strategy_id}': {e}")
            return False

    # Keep other methods like get_historical_klines_for_chart, bot controls, shutdown as they are
    async def get_historical_klines_for_chart(self, symbol: str, timeframe: str, limit: int = 100) -> Optional[pd.DataFrame]:
        if not self.market_data_provider:
            self.logger.warning("MarketDataProvider not available for chart data.")
            self.signals.status_bar_message_updated.emit("Chart data provider unavailable.", 5000)
            return None
        try:
            data = await self.market_data_provider.get_historical_klines(symbol=symbol, interval=timeframe, limit=limit)
            if data is None or data.empty :
                 self.signals.status_bar_message_updated.emit(f"No historical klines returned for {symbol}/{timeframe}.", 5000)
            return data
        except Exception as e:
            self.logger.error(f"Error fetching historical klines for chart: {e}", exc_info=True)
            self.signals.error_dialog_requested.emit("Chart Data Error", f"Failed to load historical klines for {symbol}/{timeframe}: {e}")
            return None

    @Slot()
    def start_bot_async_wrapper(self):
        self.logger.info("UI Action: Start Bot wrapper.")
        if self.loop and self.loop.is_running(): asyncio.create_task(self.start_bot())
        else: self.logger.error("No running event loop for start_bot.")
    async def start_bot(self):
        if self.is_running: self.logger.warning("Bot already running."); self.signals.log_message_appended.emit("Bot is already running."); return
        if not all([self.strategy_engine, self.market_data_provider, self.binance_connector, self.order_manager, self.risk_manager]):
             self.logger.error("Core components not initialized.")
             self.signals.log_message_appended.emit("Error: Bot components not ready.")
             self.signals.error_dialog_requested.emit("Start Bot Failed", "Core components not initialized. Restart the application.")
             return
        try:
            self.logger.info("BotController: Starting bot operations..."); self.is_running = True; self.signals.status_updated.emit("Starting...")
            if self.binance_connector and not self.binance_connector.user_data_control_flag.get('keep_running'):
                self.logger.info("User data stream seems not active, ensuring subscriptions are processed by MDP...")
                # These subscriptions are critical, if they fail, strategies might not work.
                # MarketDataProvider's subscribe methods already log errors.
                # Consider if specific error dialogs are needed here or if User Stream Failed from async_setup is enough.
                self.market_data_provider.subscribe_to_user_data(self.handle_user_data_from_mdp)
                if self.order_manager : self.market_data_provider.subscribe_to_user_data(self.order_manager.handle_order_update)
                if self.strategy_engine : self.market_data_provider.subscribe_to_user_data(self.strategy_engine.handle_user_data_for_strategies)
                await asyncio.sleep(2) # Allow subscriptions to establish

            if self.strategy_engine:
                await self.strategy_engine.start_all_strategies() # This method in SE should handle individual strategy start errors.

            self.signals.status_updated.emit("Running"); self.signals.log_message_appended.emit("Bot and strategies started.")
        except Exception as e:
            self.logger.error(f"Error starting bot operations: {e}", exc_info=True)
            self.signals.status_updated.emit("Error Starting Bot")
            self.signals.error_dialog_requested.emit("Start Bot Failed", f"An error occurred while starting strategies: {e}")
            self.is_running = False # Ensure state is correct

    @Slot()
    def stop_bot_async_wrapper(self):
        self.logger.info("UI Action: Stop Bot wrapper.")
        if self.loop and self.loop.is_running(): asyncio.create_task(self.stop_bot())
        else: self.logger.error("No running event loop for stop_bot.")
    async def stop_bot(self):
        if not self.is_running:
            self.logger.info("Bot not running, no need to stop."); return
        try:
            self.logger.info("BotController: Stopping bot operations..."); self.signals.status_updated.emit("Stopping...")
            if self.strategy_engine:
                await self.strategy_engine.stop_all_strategies() # This method in SE should handle individual strategy stop errors.
            self.is_running = False
            self.signals.status_updated.emit("Stopped"); self.signals.log_message_appended.emit("Bot and strategies stopped.")
        except Exception as e:
            self.logger.error(f"Error stopping bot operations: {e}", exc_info=True)
            self.signals.status_updated.emit("Error Stopping Bot")
            self.signals.error_dialog_requested.emit("Stop Bot Failed", f"An error occurred while stopping strategies: {e}")
            # self.is_running state might be ambiguous here, but usually set false after stop attempt.

    async def shutdown(self):
        try:
            self.logger.info("BotController initiating full shutdown..."); await self.stop_bot()
            if self.market_data_provider:
                await self.market_data_provider.unsubscribe_all_streams()
            self.save_persistent_config() # Save config on graceful shutdown
            self.logger.info("BotController shutdown complete.")
        except Exception as e:
            self.logger.error(f"Error during BotController shutdown: {e}", exc_info=True)
            # Depending on context, an error dialog might be too late or not visible.
            # Logging is primary here.

    # Methods for request_open_orders_update, request_trade_history_update, request_positions_update,
    # cancel_order_ui, close_position_ui, get_loaded_strategies_info etc. from previous steps should be here too.
    async def request_open_orders_update(self):
        if not self.order_manager:
            self.logger.warning("OrderManager not initialized for open orders update.")
            self.signals.status_bar_message_updated.emit("Failed to get open orders: Order Manager unavailable.", 5000)
            return
        try:
            orders = await self.order_manager.get_open_orders_data_for_ui()
            self.signals.open_orders_updated.emit(orders or [])
        except Exception as e:
            self.logger.error(f"Error requesting open orders: {e}", exc_info=True)
            self.signals.error_dialog_requested.emit("Fetch Open Orders Failed", f"Details: {e}")

    async def request_trade_history_update(self, symbol='BTCUSDT', limit=50):
        if not self.order_manager:
            self.logger.warning("OrderManager not initialized for trade history update.")
            self.signals.status_bar_message_updated.emit("Failed to get trade history: Order Manager unavailable.", 5000)
            return
        try:
            history = await self.order_manager.get_trade_history_data_for_ui(symbol, limit)
            self.signals.trade_history_updated.emit(history or [])
        except Exception as e:
            self.logger.error(f"Error requesting trade history: {e}", exc_info=True)
            self.signals.error_dialog_requested.emit("Fetch Trade History Failed", f"Details: {e}")

    async def request_positions_update(self, emit_for_chart=False): # Added emit_for_chart
        if not self.order_manager:
            self.logger.warning("OrderManager not initialized for positions update.")
            self.signals.status_bar_message_updated.emit("Failed to get positions: Order Manager unavailable.", 5000)
            return
        try:
            positions = await self.order_manager.get_position_data_for_ui()
            self.signals.positions_updated.emit(positions or []) # For the table view in OrdersView

            if emit_for_chart and positions:
                # Determine the symbol currently displayed on the chart
                # This assumes self.current_chart_symbol_tf is like ('BTCUSDT', '1h') or None
                chart_symbol = self.current_chart_symbol_tf[0] if self.current_chart_symbol_tf else "BTCUSDT" # Default or error if None

                for pos in positions:
                    if pos.get('symbol') == chart_symbol:
                        quantity = float(pos.get('positionAmt', 0))
                        pos_side = 'FLAT'
                        if quantity > 0: pos_side = 'LONG'
                        elif quantity < 0: pos_side = 'SHORT'

                        pos_data_for_chart = {
                            'symbol': pos.get('symbol'),
                            'entry_price': float(pos.get('entryPrice', 0)),
                            'quantity': quantity, # Already float
                            'side': pos_side,
                            'timestamp': time.time() # Current time for update
                        }
                        self.logger.debug(f"Emitting chart_position_update for {chart_symbol}: {pos_data_for_chart}")
                        self.signals.chart_position_update.emit(pos_data_for_chart)
                        break # Assuming only one position per symbol for chart visualization

        except Exception as e:
            self.logger.error(f"Error requesting positions: {e}", exc_info=True)
            self.signals.error_dialog_requested.emit("Fetch Positions Failed", f"Details: {e}")
            if emit_for_chart: # Clear chart position if fetch fails
                 chart_symbol = self.current_chart_symbol_tf[0] if self.current_chart_symbol_tf else "BTCUSDT"
                 self.signals.chart_position_update.emit({
                     'symbol': chart_symbol, 'side': 'FLAT',
                     'entry_price': 0, 'quantity': 0, 'timestamp': time.time()
                 })


    async def cancel_order_ui(self, order_id_str: str, symbol: str):
        if not self.order_manager:
            self.logger.error("OrderManager not available for order cancellation.")
            self.signals.error_dialog_requested.emit("Cancel Order Failed", "Order Manager not available.")
            return
        try:
            self.logger.info(f"BC: UI cancel order {order_id_str} for {symbol}")
            order_id_int: Optional[int]=None; client_order_id: Optional[str]=None
            if order_id_str.isdigit(): order_id_int = int(order_id_str)
            else: client_order_id = order_id_str
            response = await self.order_manager.cancel_existing_order(symbol=symbol, orderId=order_id_int, origClientOrderId=client_order_id)

            if response and (response.get('status') == 'CANCELED' or response.get('clientOrderId') == client_order_id): # Some cancel calls return limited info
                msg = f"Order {order_id_str} ({symbol}) cancel request processed."
                self.signals.log_message_appended.emit(msg)
            else:
                error_detail = response.get('msg', 'Unknown error from API.') if response else 'No API response.'
                msg = f"Order {order_id_str} ({symbol}) cancel failed: {error_detail}"
                self.signals.log_message_appended.emit(msg)
                self.signals.error_dialog_requested.emit("Cancel Order Failed", f"For order {order_id_str}: {error_detail}")

            if self.loop and self.loop.is_running():
                asyncio.create_task(self.request_open_orders_update())
        except Exception as e:
            self.logger.error(f"Exception canceling order {order_id_str}: {e}", exc_info=True)
            self.signals.error_dialog_requested.emit("Cancel Order Failed", f"Exception for order {order_id_str}: {e}")


    async def close_position_ui(self, symbol: str, position_side_to_close: str):
        if not self.order_manager:
            self.logger.error("OrderManager not available for closing position.")
            self.signals.error_dialog_requested.emit("Close Position Failed", "Order Manager not available.")
            return
        try:
            self.logger.info(f"BC: UI close {position_side_to_close} position for {symbol}")
            response = await self.order_manager.close_position_market(symbol, position_side_to_close)

            if response and (response.get('status') == 'FILLED' or response.get('status') == 'NEW'):
                msg = f"Market close for {position_side_to_close} {symbol} placed."
                self.signals.log_message_appended.emit(msg)
            else:
                error_detail = response.get('msg', 'Unknown error from API.') if response else 'No API response.'
                msg = f"Market close for {position_side_to_close} {symbol} failed: {error_detail}"
                self.signals.log_message_appended.emit(msg)
                self.signals.error_dialog_requested.emit("Close Position Failed", f"For {symbol} ({position_side_to_close}): {error_detail}")

            await asyncio.sleep(1) # Give time for order to potentially process
            if self.loop and self.loop.is_running():
                asyncio.create_task(self.request_positions_update())
                asyncio.create_task(self.request_open_orders_update())
        except Exception as e:
            self.logger.error(f"Exception closing position {symbol} ({position_side_to_close}): {e}", exc_info=True)
            self.signals.error_dialog_requested.emit("Close Position Failed", f"Exception for {symbol} ({position_side_to_close}): {e}")


    # --- Live Kline Data for Chart ---
    async def subscribe_to_chart_klines(self, symbol: str, timeframe: str):
        if not self.market_data_provider:
            self.logger.error("MarketDataProvider not available for chart kline subscription.")
            return

        # Unsubscribe from previous chart kline stream if any
        if self.current_chart_kline_subscription_id:
            self.logger.info(f"Unsubscribing from previous chart kline stream: {self.current_chart_kline_subscription_id}")
            await self.market_data_provider.unsubscribe_from_stream_by_id(self.current_chart_kline_subscription_id)
            self.current_chart_kline_subscription_id = None

        self.logger.info(f"Subscribing to kline stream for chart: {symbol}@{timeframe}")
        # The callback _handle_live_kline_for_ui needs to be defined
        new_sub_id = await self.market_data_provider.subscribe_to_kline_stream(
            symbol, timeframe, self._handle_live_kline_for_ui
        )
        if new_sub_id:
            self.current_chart_kline_subscription_id = new_sub_id
            self.logger.info(f"Successfully subscribed to chart kline stream {symbol}@{timeframe}, ID: {new_sub_id}")
        else:
            self.logger.error(f"Failed to subscribe to chart kline stream {symbol}@{timeframe}")

    async def _handle_live_kline_for_ui(self, raw_ws_message: dict):
        """
        Handles incoming kline data from WebSocket, formats it, and emits a signal for the UI.
        raw_ws_message example:
        {
            "stream": "btcusdt@kline_1m",
            "data": {
                "e": "kline",           // Event type
                "E": 1672515780000,     // Event time
                "s": "BTCUSDT",         // Symbol
                "k": {
                    "t": 1672515720000, // Kline start time (ms)
                    "T": 1672515779999, // Kline close time (ms)
                    "s": "BTCUSDT",     // Symbol
                    "i": "1m",          // Interval
                    "f": 100,           // First trade ID
                    "L": 200,           // Last trade ID
                    "o": "0.0010",      // Open price
                    "c": "0.0020",      // Close price
                    "h": "0.0025",      // High price
                    "l": "0.0015",      // Low price
                    "v": "1000",        // Base asset volume
                    "n": 100,           // Number of trades
                    "x": false,         // Is this kline closed?
                    "q": "1.0000",      // Quote asset volume
                    "V": "500",         // Taker buy base asset volume
                    "Q": "0.500",       // Taker buy quote asset volume
                    "B": "12345"        // Ignore
                }
            }
        }
        """
        try:
            kline_payload = raw_ws_message.get('data', {}).get('k', {})
            if not kline_payload:
                self.logger.warning(f"Received kline WS message with empty payload: {raw_ws_message}")
                return

            ui_kline_data = {
                "symbol": kline_payload.get('s'),
                "interval": kline_payload.get('i'),
                "t": kline_payload.get('t'),      # Kline open time (ms)
                "o": kline_payload.get('o'),
                "h": kline_payload.get('h'),
                "l": kline_payload.get('l'),
                "c": kline_payload.get('c'),
                "v": kline_payload.get('v'),      # Base asset volume
                "T": kline_payload.get('T'),      # Kline close time (ms)
                "x": kline_payload.get('x', False) # Is this kline closed?
            }

            # Basic validation
            if not all([ui_kline_data['symbol'], ui_kline_data['interval'], isinstance(ui_kline_data['t'], (int, float))]):
                self.logger.warning(f"Received incomplete kline data for UI: {ui_kline_data}")
                return

            # self.logger.debug(f"BC Emitting live_kline_updated: S:{ui_kline_data['symbol']} I:{ui_kline_data['interval']} O:{ui_kline_data['o']} C:{ui_kline_data['c']} Closed:{ui_kline_data['x']}")
            self.signals.live_kline_updated.emit(ui_kline_data)

        except Exception as e:
            self.logger.error(f"Error processing live kline for UI: {e}. Message: {raw_ws_message}", exc_info=True)
            self.signals.status_bar_message_updated.emit(f"Error processing live kline for {ui_kline_data.get('s') if ui_kline_data else 'chart'}: {e}", 5000)

    # --- Internal Signal Connections & Handlers ---
    def _connect_internal_signals(self):
        # Example: self.order_manager.signals.order_event.connect(self.handle_order_event_from_om)
        # This method is for internal Qt signals if needed, not for MDP data callbacks.
        pass

    async def handle_user_data_from_mdp(self, user_data_event: Dict):
        # This is a generic handler for various user data events.
        # It could be ORDER_TRADE_UPDATE, ACCOUNT_UPDATE, etc.
        # For BotController, it might update balance or trigger UI refreshes.
        # OrderManager and StrategyEngine also subscribe to user data directly for their specific needs.

        event_type = user_data_event.get('e')
        # self.logger.debug(f"BotController received user_data_event: {event_type}")

        if event_type == 'ACCOUNT_UPDATE':
            await self.update_dashboard_balance()
            # ACCOUNT_UPDATE can signify changes in positions due to liquidation, margin calls, etc.
            # So, triggering a P&L update is reasonable here.
            if self.order_manager and self.loop and self.loop.is_running():
                asyncio.create_task(self.trigger_pnl_emission())


        elif event_type == 'ORDER_TRADE_UPDATE':
            order_data = user_data_event.get('o', user_data_event) # 'o' contains order details

            self.logger.info(f"Order Update: Sym:{order_data.get('s')} Side:{order_data.get('S')} Type:{order_data.get('o')} "
                             f"Status:{order_data.get('X')} Qty:{order_data.get('q')} Filled:{order_data.get('z')} "
                             f"Price:{order_data.get('p')} AvgPx:{order_data.get('ap')} ClientOID:{order_data.get('c')}")

            execution_type = order_data.get('x') # Execution type (e.g., TRADE, CANCELED)
            order_status = order_data.get('X')   # Order status (e.g., FILLED, PARTIALLY_FILLED, CANCELED)

            # Emit trade marker if order is filled (partially or fully)
            if execution_type == 'TRADE' and float(order_data.get('l', 0)) > 0: # 'l' is Last filled quantity
                trade_info = {
                    'symbol': order_data.get('s'),
                    'timestamp': float(order_data.get('T', time.time() * 1000)) / 1000.0, # 'T' is Transaction time
                    'price': float(order_data.get('L')),      # 'L' is Last filled price
                    'side': order_data.get('S'),              # 'S' is Side (BUY/SELL)
                    'quantity': float(order_data.get('l'))    # 'l' is Last filled quantity
                }
                self.logger.debug(f"Emitting chart_new_trade_marker: {trade_info}")
                self.signals.chart_new_trade_marker.emit(trade_info)

            # OrderManager's handle_order_update will call self.trigger_pnl_emission via callback if it's a FILL.
            # For other terminal states, we might also want to update positions for the chart.
            if order_status in ['CANCELED', 'EXPIRED', 'REJECTED'] or \
               (execution_type == 'TRADE' and order_status == 'PARTIALLY_FILLED'): # Keep updating for partial fills
                if self.loop and self.loop.is_running():
                    asyncio.create_task(self.request_positions_update(emit_for_chart=True))

            # Always refresh open orders list on any order update
            if self.loop and self.loop.is_running():
                 asyncio.create_task(self.request_open_orders_update())

    async def update_dashboard_balance(self):
        if self.order_manager:
            try:
                balance_info = await self.order_manager.get_account_balance() # USDT balance
                if balance_info:
                    usdt_balance = next((item['balance'] for item in balance_info if item['asset'] == 'USDT'), None)
                    if usdt_balance is not None:
                        self.signals.usdt_balance_updated.emit(float(usdt_balance))
                        # self.logger.debug(f"Emitted USDT balance update: {usdt_balance}")
            except Exception as e:
                self.logger.error(f"Error updating dashboard balance: {e}", exc_info=True)
                self.signals.status_bar_message_updated.emit(f"Failed to update balance: {e}", 5000)

    def handle_btc_mark_price_update(self, mark_price_data: dict):
        # This handler is specifically for the dashboard's BTCUSDT price ticker.
        # P&L calculations will use handle_mark_price_for_pnl_passthrough.
        payload = mark_price_data.get('data', mark_price_data)
        if payload and payload.get('s') == 'BTCUSDT':
            price_str = payload.get('p', "0.0")
            try:
                price = float(price_str)
                self.signals.btc_mark_price_updated.emit(price) # For dashboard ticker
            except ValueError:
                self.logger.error(f"Could not parse BTC mark price for dashboard ticker: {price_str}")

    async def handle_mark_price_for_pnl_passthrough(self, raw_ws_message: dict):
        """Generic handler for mark price updates for P&L calculation."""
        payload = raw_ws_message.get('data', raw_ws_message) # Handle nested or direct payload
        symbol = payload.get('s')
        mark_price_str = payload.get('p')

        if symbol and mark_price_str and self.order_manager:
            try:
                mark_price = float(mark_price_str)
                self.order_manager.update_mark_price_for_pnl(symbol, mark_price)
                if self.loop and self.loop.is_running():
                    asyncio.create_task(self.trigger_pnl_emission())

                # If this is BTCUSDT, also update the specific dashboard ticker signal
                # This avoids needing two subscriptions if one handler can serve both.
                if symbol == "BTCUSDT":
                    self.signals.btc_mark_price_updated.emit(mark_price)

            except ValueError:
                self.logger.error(f"Could not parse mark price for {symbol} from P&L stream: {mark_price_str}")
        else:
            self.logger.warning(f"Incomplete mark price data for P&L: {payload}")

    async def _subscribe_to_initial_mark_prices_for_pnl(self):
        """Subscribes to mark price streams for symbols with open positions or active strategies."""
        if not self.market_data_provider or not self.order_manager:
            self.logger.warning("MDP or OM not available for initial P&L mark price subscriptions.")
            return

        symbols_to_subscribe = set()
        # Add symbols from active strategies
        if self.strategy_engine:
            for strat_id, strategy_instance in self.strategy_engine.strategies.items():
                if strategy_instance.is_active and hasattr(strategy_instance, 'symbol'):
                    symbols_to_subscribe.add(strategy_instance.symbol)

        # Add symbols from current open positions (if any)
        try:
            positions = await self.order_manager.binance_connector.get_position_information()
            if positions:
                for pos in positions:
                    if float(pos.get('positionAmt', 0)) != 0:
                        symbols_to_subscribe.add(pos.get('symbol'))
        except Exception as e:
            self.logger.error(f"Failed to get positions for P&L mark price subscriptions: {e}")

        # Default to BTCUSDT if no other symbols identified (e.g. for dashboard)
        if not symbols_to_subscribe:
            symbols_to_subscribe.add("BTCUSDT")

        for symbol in symbols_to_subscribe:
            if symbol not in self.subscribed_mark_price_for_pnl:
                self.logger.info(f"Subscribing to mark price for P&L: {symbol}")
                await self.market_data_provider.subscribe_to_mark_price_stream(
                    symbol,
                    self.handle_mark_price_for_pnl_passthrough
                )
                self.subscribed_mark_price_for_pnl.add(symbol)
            else:
                self.logger.debug(f"Already subscribed to mark price for P&L for {symbol}.")

    async def trigger_pnl_emission(self):
        """Fetches P&L data from OrderManager and emits signals."""
        if not self.order_manager:
            self.logger.warning("OrderManager not available for P&L emission.")
            return

        try:
            realized_pnl = self.order_manager.get_session_realized_pnl()
            open_pnl_data = await self.order_manager.calculate_all_open_positions_pnl()
            unrealized_pnl = open_pnl_data.get('total_unrealized', 0.0)

            self.signals.total_pnl_updated.emit(realized_pnl + unrealized_pnl)
            self.signals.open_pnl_updated.emit(unrealized_pnl)
            # self.logger.debug(f"P&L Emitted: Realized={realized_pnl:.2f}, Unrealized={unrealized_pnl:.2f}, Total={realized_pnl + unrealized_pnl:.2f}")
        except Exception as e:
            self.logger.error(f"Error triggering P&L emission: {e}", exc_info=True)

```
