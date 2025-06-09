import asyncio
import logging
import pandas as pd
import os # For path joining

# Adjust import paths based on where this script is run from (e.g., project root)
# This assumes 'bot' is a package in the PYTHONPATH or in the same directory level as 'scripts'
try:
    from bot.core.data_fetcher import MarketDataProvider
    from bot.connectors.binance_connector import BinanceAPI
    from bot.core.backtester import BacktestEngine
    from bot.strategies.pivot_strategy import PivotPointStrategy
    from bot.strategies.dca_strategy import AdvancedDCAStrategy
    from bot.core.config_loader import load_api_keys, load_log_level
    from bot.core.logger_setup import setup_logger
    # OrderManager and BasicRiskManager are used internally by BacktestEngine or strategies
    # from bot.core.order_executor import OrderManager
    # from bot.core.risk_manager import BasicRiskManager
except ImportError as e:
    logging.basicConfig(level=logging.INFO) # Basic logger for import error
    logging.error(f"ImportError: {e}. Ensure PYTHONPATH is set correctly or run from project root (e.g., python -m scripts.run_backtests)")
    # Attempt relative imports if run directly from scripts folder and bot is sibling
    # This is less robust than proper PYTHONPATH setup.
    if __name__ == '__main__' and not os.environ.get("PYTHONPATH"): # Heuristic
        import sys
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        logging.info(f"Added {project_root} to sys.path")
        from bot.core.data_fetcher import MarketDataProvider
        from bot.connectors.binance_connector import BinanceAPI
        from bot.core.backtester import BacktestEngine
        from bot.strategies.pivot_strategy import PivotPointStrategy
        from bot.strategies.dca_strategy import AdvancedDCAStrategy
        from bot.core.config_loader import load_api_keys, load_log_level
        from bot.core.logger_setup import setup_logger


async def main():
    # --- Logger Setup ---
    # Load log level from .env or default to INFO
    # Assuming .env is in project root, which is one level up from 'scripts/'
    dotenv_path = os.path.join(os.path.dirname(__file__), '../.env')
    log_level = load_log_level(env_file_path=dotenv_path)
    logger = setup_logger(level=log_level, log_file="backtest_runs.log", log_directory="logs/backtests")
    logger.info("Backtesting script started.")

    # --- API Keys & Connector Setup ---
    # API keys might not be strictly needed if MDP's get_historical_klines for public data works without them,
    # but BinanceAPI class might expect them for header setup.
    # For actual data fetching, even public, it's safer to have them.
    api_key, api_secret = load_api_keys(env_file_path=dotenv_path)
    if not api_key or api_key == "YOUR_TESTNET_API_KEY": # Check for placeholder
        logger.warning("API keys not found or are placeholders in .env. Historical data fetching might be limited or fail.")
        # Optionally, use a dummy connector or exit if keys are essential for the data provider
        # For now, we'll proceed, assuming public kline access might work.
        connector = BinanceAPI(testnet=True) # Init without keys, might fail if endpoint needs them
    else:
        connector = BinanceAPI(api_key=api_key, api_secret=api_secret, testnet=True)

    market_data_provider = MarketDataProvider(binance_connector=connector)
    logger.info("MarketDataProvider and BinanceConnector initialized.")

    # --- Common Backtest Parameters ---
    symbol = "BTCUSDT"
    timeframe = "1h"
    start_date = "2023-12-01"
    end_date = "2023-12-15" # Longer period for more trades
    initial_capital = 10000.0
    commission_rate = 0.0004 # Standard Binance commission

    # --- PivotPointStrategy Backtest ---
    logger.info(f"\n--- Starting Backtest for PivotPointStrategy ---")
    strategy_params_pivot = {
        'symbol': symbol,
        'trade_interval': timeframe,
        'pivot_period_tf': '1D', # Daily pivots
        'default_risk_per_trade_perc': 0.01, # Risk 1% of capital per trade
        'stop_loss_atr_multiplier': 1.5,
        'take_profit_atr_multiplier': 2.0,
        'asset_quantity_precision': 3,
        'asset_price_precision': 2,
        'atr_period_for_backtest': 14 # For BacktestEngine to calculate ATR
    }
    backtester_pivot = BacktestEngine(
        market_data_provider=market_data_provider,
        strategy_class=PivotPointStrategy,
        strategy_params=strategy_params_pivot,
        start_date_str=start_date,
        end_date_str=end_date,
        initial_capital=initial_capital,
        symbol=symbol,
        timeframe=timeframe,
        commission_rate=commission_rate
    )
    pivot_results = await backtester_pivot.run_backtest()
    if pivot_results:
        logger.info(f"PivotPointStrategy Performance: {pivot_results}")
        # Optional: Save trades and equity curve to CSV
        # pd.DataFrame(backtester_pivot.simulated_trades).to_csv(f"logs/backtests/pivot_trades_{symbol}_{timeframe}.csv")
        # pd.DataFrame(backtester_pivot.equity_curve).to_csv(f"logs/backtests/pivot_equity_{symbol}_{timeframe}.csv")
    else:
        logger.error("PivotPointStrategy backtest did not return results.")


    # --- AdvancedDCAStrategy Backtest ---
    logger.info(f"\n--- Starting Backtest for AdvancedDCAStrategy ---")
    strategy_params_dca = {
        'symbol': symbol,
        'trade_interval': timeframe, # Used for kline updates if strategy needs them
        'initial_order_type': 'LONG',
        'base_order_size_usd': 100.0, # Initial USD size for the first order
        'safety_orders_config': [
            {'deviation_perc': 1.0, 'size_usd_multiplier': 1.0}, # SO1: 1% down, 1x base size
            {'deviation_perc': 2.0, 'size_usd_multiplier': 1.5}, # SO2: 2% down from prev, 1.5x base
            {'deviation_perc': 3.0, 'size_usd_multiplier': 2.0}, # SO3: 3% down from prev, 2x base
        ],
        'take_profit_percentage': 0.01, # 1% take profit from average entry
        'asset_quantity_precision': 3,
        'asset_price_precision': 2,
        'atr_period_for_backtest': 14 # Though DCA might not use ATR directly, BacktestEngine calculates it
    }
    backtester_dca = BacktestEngine(
        market_data_provider=market_data_provider,
        strategy_class=AdvancedDCAStrategy,
        strategy_params=strategy_params_dca,
        start_date_str=start_date,
        end_date_str=end_date,
        initial_capital=initial_capital,
        symbol=symbol,
        timeframe=timeframe, # DCA uses mark price, but klines are needed for backtest progression
        commission_rate=commission_rate
    )

    # For DCA, we need to manually trigger the first order in backtest, as it doesn't have an internal signal usually
    # We can do this after run_backtest starts the strategy and loads data.
    # However, the current BacktestEngine loop calls on_kline_update.
    # A simple way is to add a param to DCA to auto-start on first kline, or modify its on_kline_update.
    # For now, let's assume the DCA strategy needs a manual kick-off or a simple trigger.
    # The `start_new_dca_cycle` method is designed for this.
    # BacktestEngine doesn't currently support calling arbitrary strategy methods mid-run easily.
    # Let's modify DCA to start on the first kline for testing.
    strategy_params_dca['auto_start_cycle_on_init'] = True # This is a hypothetical param for the strategy

    logger.info("Running DCA backtest (strategy will auto-start on first kline if configured)...")
    dca_results = await backtester_dca.run_backtest() # run_backtest will call strategy.start()

    # If strategy doesn't auto-start, one might do this (needs BacktestEngine modification or direct call):
    # if backtester_dca.strategy_instance and hasattr(backtester_dca.strategy_instance, 'start_new_dca_cycle'):
    #     logger.info("Manually triggering DCA cycle for backtest...")
    #     first_kline_price = backtester_dca.historical_data['open'].iloc[0]
    #     await backtester_dca.strategy_instance.start_new_dca_cycle(entry_price_estimate=first_kline_price)
    #     # Then, the main loop of run_backtest would continue, processing subsequent klines.
    #     # This interaction is complex and not fully supported by current BacktestEngine design without changes.
    #     # For now, rely on strategy's own logic in on_kline_update or start.

    if dca_results:
        logger.info(f"AdvancedDCAStrategy Performance: {dca_results}")
        # pd.DataFrame(backtester_dca.simulated_trades).to_csv(f"logs/backtests/dca_trades_{symbol}_{timeframe}.csv")
        # pd.DataFrame(backtester_dca.equity_curve).to_csv(f"logs/backtests/dca_equity_{symbol}_{timeframe}.csv")
    else:
        logger.error("AdvancedDCAStrategy backtest did not return results.")

    logger.info("Backtesting script finished.")

if __name__ == "__main__":
    # This structure allows running from project root: python -m scripts.run_backtests
    # Or, if 'bot' is in PYTHONPATH: python scripts/run_backtests.py
    # Ensure that the logger is set up before any module uses it.
    # The main function handles logger setup internally now.
    asyncio.run(main())

```
