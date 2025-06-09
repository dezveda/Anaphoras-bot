import asyncio
import logging
import pandas as pd
import os
import sys
from typing import Any # For type hinting if needed

# --- Path Setup ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
# --- End Path Setup ---

try:
    from bot.connectors.binance_connector import BinanceAPI
    from bot.core.data_fetcher import MarketDataProvider
    from bot.core.order_executor import OrderManager
    from bot.core.risk_manager import BasicRiskManager
    from bot.strategies.strategy_engine import StrategyEngine
    from bot.strategies.pivot_strategy import PivotPointStrategy
    from bot.strategies.dca_strategy import AdvancedDCAStrategy
    from bot.strategies.indicator_heuristic_strategy import IndicatorHeuristicStrategy
    # Add other strategies if you want to load them:
    # from bot.strategies.liquidity_strategy import LiquidityPointsStrategy
    # from bot.strategies.trend_adaptation_strategy import TrendAdaptationStrategy
    from bot.core.config_loader import load_api_keys, load_log_level
    from bot.core.logger_setup import setup_logger
except ImportError as e:
    # Basic logging if imports fail early
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    logging.error(f"ImportError: {e}. Critical components not found. "
                  f"Ensure you are running from the project root (e.g., python -m scripts.run_live_bot) "
                  f"or that your PYTHONPATH is correctly set.")
    sys.exit(1)


async def main():
    # --- Logger Setup ---
    dotenv_path = os.path.join(PROJECT_ROOT, '.env') # Assuming .env is in project root
    log_level_from_env = load_log_level(env_file_path=dotenv_path)

    log_dir = os.path.join(PROJECT_ROOT, "logs", "live") # Separate log dir for live runs
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    logger = setup_logger(level=log_level_from_env, log_file="live_bot_activity.log", log_directory=log_dir)
    logger.info("Live Trading Bot script started. Logger configured.")
    logger.info(f"Log level set to: {logging.getLevelName(logger.level)}")


    # --- Load API Keys ---
    # For live/paper trading, use_testnet should be True for paper trading on Testnet
    # and False for actual live trading on Mainnet (USE WITH EXTREME CAUTION).
    USE_TESTNET_CONFIG = True # Set to False for Mainnet live trading

    api_key, api_secret = load_api_keys(env_file_path=dotenv_path, use_testnet=USE_TESTNET_CONFIG)

    if not api_key or not api_secret:
        logger.error(f"API key or secret not found for {'Testnet' if USE_TESTNET_CONFIG else 'Mainnet'}. Please check your .env file. Exiting.")
        return
    logger.info(f"API keys loaded for {'Testnet' if USE_TESTNET_CONFIG else 'Mainnet'}.")

    # --- Initialize Core Components ---
    binance_connector = BinanceAPI(api_key=api_key, api_secret=api_secret, testnet=USE_TESTNET_CONFIG)
    market_data_provider = MarketDataProvider(binance_connector=binance_connector)

    # OrderManager needs an async balance provider. Its get_available_trading_balance is async.
    # RiskManager needs an async balance provider.
    # We need to ensure OrderManager is fully initialized before its balance provider method is passed.
    # Temporary solution: Initialize RM with a placeholder, then update.
    # Or, ensure OM is fully ready.

    # Instantiate OrderManager first, then RiskManager using OM's async method
    order_manager = OrderManager(
        binance_connector=binance_connector,
        market_data_provider=market_data_provider,
        risk_manager=None # Risk manager will be set after its own initialization
    )

    risk_manager = BasicRiskManager(
        account_balance_provider_fn=order_manager.get_available_trading_balance, # Pass the async method
        default_risk_per_trade_perc=0.01 # Example: 1% risk per trade
    )
    order_manager.risk_manager = risk_manager # Now set the risk_manager for order_manager

    strategy_engine = StrategyEngine(
        order_manager=order_manager,
        market_data_provider=market_data_provider,
        risk_manager=risk_manager,
        logger_name='algo_trader_bot' # Main logger
    )
    strategy_engine.live_trading_mode = True # IMPORTANT: Set to live mode

    logger.info("Core components (Connector, MDP, OrderManager, RiskManager, StrategyEngine) initialized.")

    # --- Register Callbacks for User Data Stream ---
    # MarketDataProvider will call these when user data events are received.
    # OrderManager needs order updates to manage its active_orders.
    # StrategyEngine needs order updates to forward to strategies.
    market_data_provider.subscribe_to_user_data(user_data_event_callback=order_manager.handle_order_update)
    market_data_provider.subscribe_to_user_data(user_data_event_callback=strategy_engine.handle_user_data_for_strategies)
    logger.info("OrderManager and StrategyEngine subscribed to user data updates from MarketDataProvider.")

    # --- Load Strategies into Engine ---
    logger.info("Loading strategies...")
    try:
        pivot_params = {
            'symbol': 'BTCUSDT',
            'pivot_period_tf': '1D',
            'trade_timeframe': '15m', # Strategy will subscribe to 15m klines
            'default_risk_per_trade_perc': 0.005, # Risk 0.5% for pivot strategy
            'stop_loss_atr_multiplier': 1.5,
            'take_profit_atr_multiplier': 2.5,
            'atr_period_for_sl_tp': 20, # ATR period for SL/TP calculations
            'asset_quantity_precision': 3,
            'asset_price_precision': 2,
            'min_order_qty': 0.001
        }
        strategy_engine.load_strategy(PivotPointStrategy, "PivotStrategy_BTC_15m", pivot_params)

        # heuristic_params = {
        #     'symbol': 'ETHUSDT', 'trade_timeframe': '1h', 'klines_buffer_size': 50,
        #     'rsi_period': 14, 'rsi_oversold': 30, 'rsi_overbought': 70,
        #     'ema_short_period': 10, 'ema_long_period': 20,
        #     'score_rsi_oversold': 1, 'score_rsi_overbought': -1,
        #     'score_ema_bullish_cross': 1, 'score_ema_bearish_cross': -1,
        #     'buy_score_threshold': 2, 'sell_score_threshold': -2,
        #     'default_risk_per_trade_perc': 0.01, 'sl_atr_multiplier': 2, 'tp_atr_multiplier': 3,
        #     'atr_period_for_sl_tp': 14, 'asset_quantity_precision': 3, 'asset_price_precision': 2,
        #     'min_order_qty': 0.01 # For ETH
        # }
        # strategy_engine.load_strategy(IndicatorHeuristicStrategy, "Heuristic_ETH_1h", heuristic_params)

    except Exception as e_load:
        logger.error(f"Error loading strategies: {e_load}", exc_info=True)
        return # Exit if strategies can't be loaded

    # --- Start Bot Operations ---
    logger.info("Starting User Data Stream for live balance and order updates...")
    # The MarketDataProvider's subscribe_to_user_data method now handles starting the stream if not already active.
    # We have already called it for order_manager and strategy_engine.
    # Ensure it's robust enough to only start once or handle multiple calls.
    # For clarity, we can check if it's running or rely on its internal logic.
    # Let's assume it's started by the first call to subscribe_to_user_data.
    # We might need an explicit start if no callbacks were registered yet but stream is desired.
    # The current MDP.subscribe_to_user_data starts it if not running.

    # Allow some time for user stream to connect and potentially receive initial data (e.g., balance)
    # before strategies try to use balance-dependent logic (like RiskManager).
    logger.info("Waiting for 5 seconds for user stream to establish and initial data...")
    await asyncio.sleep(5)

    logger.info("Starting all loaded strategies...")
    await strategy_engine.start_all_strategies() # This will trigger strategies to subscribe to market data.

    logger.info("Bot is running. Press Ctrl+C to stop.")
    try:
        # Keep the main script alive. Strategies run in their own tasks via WebSocket callbacks.
        # StrategyEngine might have its own main_loop for periodic tasks if needed.
        # For now, an event-driven approach is primary.
        while True:
            await asyncio.sleep(60) # Wake up periodically for potential health checks, etc.
            logger.debug("Main loop heartbeat. Bot is running...")
            # Add any periodic health checks or tasks here if necessary
            # For example, check status of WebSocket connections in BinanceConnector
            if not market_data_provider.binance_connector.user_data_control_flag.get('keep_running'):
                logger.error("User data stream seems to have stopped unexpectedly. Shutting down.")
                break
            # Check market data streams too if possible

    except KeyboardInterrupt:
        logger.info("Shutdown signal (KeyboardInterrupt) received...")
    except Exception as e_main_loop:
        logger.error(f"Exception in main bot loop: {e_main_loop}", exc_info=True)
    finally:
        logger.info("Initiating shutdown sequence...")
        await strategy_engine.shutdown() # Stops all strategies

        # MarketDataProvider's unsubscribe_all_streams also stops the user stream via BinanceConnector
        await market_data_provider.unsubscribe_all_streams()

        # Final cleanup for BinanceConnector resources (e.g. session) if any explicit close needed.
        # (requests.Session is usually closed when the object is garbage collected or via context manager)
        # If BinanceConnector had an explicit async close for its session:
        # await binance_connector.close_session()

        logger.info("Bot shut down gracefully.")

if __name__ == "__main__":
    asyncio.run(main())

```
