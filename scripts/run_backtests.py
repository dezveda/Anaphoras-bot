import asyncio
import logging
import pandas as pd
import os
import sys

# --- Path Setup ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
# --- End Path Setup ---

try:
    from bot.core.data_fetcher import MarketDataProvider
    from bot.connectors.binance_connector import BinanceAPI
    from bot.core.backtester import BacktestEngine
    from bot.strategies.pivot_strategy import PivotPointStrategy
    from bot.strategies.dca_strategy import AdvancedDCAStrategy
    from bot.strategies.liquidity_strategy import LiquidityPointsStrategy
    from bot.strategies.trend_adaptation_strategy import TrendAdaptationStrategy
    from bot.strategies.indicator_heuristic_strategy import IndicatorHeuristicStrategy
    from bot.core.config_loader import load_api_keys, load_log_level
    from bot.core.logger_setup import setup_logger
except ImportError as e:
    logging.basicConfig(level=logging.INFO)
    logging.error(f"ImportError: {e}. Critical components not found. Ensure you are running from the project root "
                  f"using 'python -m scripts.run_backtests' or that your PYTHONPATH is correctly set.")
    sys.exit(1)


async def main():
    # --- Logger Setup ---
    dotenv_path = os.path.join(PROJECT_ROOT, '.env')
    log_level = load_log_level(env_file_path=dotenv_path)

    log_dir = os.path.join(PROJECT_ROOT, "logs", "backtests")
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    logger = setup_logger(level=log_level, log_file="backtest_runs.log", log_directory=log_dir)
    logger.info("Backtesting script started. Logger configured.")

    # --- API Keys & Connector Setup ---
    api_key, api_secret = load_api_keys(env_file_path=dotenv_path)
    use_testnet = True

    if not api_key or api_key == "YOUR_TESTNET_API_KEY":
        logger.warning("API keys not found or are placeholders. Using connector without API keys for public data.")
        connector = BinanceAPI(testnet=use_testnet)
    else:
        logger.info("API keys loaded. Initializing BinanceConnector for Testnet.")
        connector = BinanceAPI(api_key=api_key, api_secret=api_secret, testnet=use_testnet)

    market_data_provider = MarketDataProvider(binance_connector=connector)
    logger.info("MarketDataProvider and BinanceConnector initialized.")

    # --- Common Backtest Parameters ---
    symbol = "BTCUSDT"
    initial_capital = 10000.0
    commission_rate = 0.0004
    default_start_date = "2023-12-01 00:00:00"
    default_end_date = "2023-12-15 23:59:59"

    # --- IndicatorHeuristicStrategy Backtest ---
    logger.info(f"\n--- Starting Backtest for IndicatorHeuristicStrategy ---")
    heuristic_timeframe = "1h"
    strategy_params_heuristic = {
        'symbol': symbol,
        'trade_timeframe': heuristic_timeframe,
        'klines_buffer_size': 100,
        'rsi_period': 14, 'rsi_oversold': 35, 'rsi_overbought': 65,
        'ema_short_period': 9, 'ema_long_period': 21,
        'score_rsi_oversold': 1, 'score_rsi_overbought': -1,
        'score_ema_bullish_cross': 1, 'score_ema_bearish_cross': -1,
        'buy_score_threshold': 2, 'sell_score_threshold': -2,
        'default_risk_per_trade_perc': 0.01,
        'sl_atr_multiplier': 1.5, 'tp_atr_multiplier': 2.0,
        'atr_period_for_sl_tp': 14,
        'atr_period_for_backtest': 14, # For BacktestEngine to provide ATR
        'asset_quantity_precision': 3, 'asset_price_precision': 2,
        'min_order_qty': 0.001
    }
    backtester_heuristic = BacktestEngine(
        market_data_provider=market_data_provider,
        strategy_class=IndicatorHeuristicStrategy,
        strategy_params=strategy_params_heuristic,
        start_date_str=default_start_date,
        end_date_str=default_end_date,
        initial_capital=initial_capital,
        symbol=symbol,
        timeframe=heuristic_timeframe,
        commission_rate=commission_rate
    )
    heuristic_results_metrics = await backtester_heuristic.run_backtest()
    if heuristic_results_metrics:
        logger.info(f"IndicatorHeuristicStrategy Backtest Performance Metrics: {heuristic_results_metrics}")
        if backtester_heuristic.simulated_trades:
            trades_df_heuristic = pd.DataFrame(backtester_heuristic.simulated_trades)
            logger.info(f"Heuristic Simulated Trades Count: {len(trades_df_heuristic)}")
            # logger.info(f"Heuristic Simulated Trades:\n{trades_df_heuristic.to_string()}") # Can be very verbose
            trades_df_heuristic.to_csv(os.path.join(log_dir, f"heuristic_trades_{symbol}_{heuristic_timeframe}.csv"))
    else:
        logger.error("IndicatorHeuristicStrategy backtest did not return results or failed.")


    # --- [Other strategy tests can be re-enabled here by uncommenting] ---
    # Example: LiquidityPointsStrategy
    # logger.info(f"\n--- Starting Backtest for LiquidityPointsStrategy ---")
    # liquidity_timeframe = "15m"
    # strategy_params_liquidity = {
    #     'symbol': symbol, 'trade_timeframe': liquidity_timeframe,
    #     'swing_point_lookback': 20, 'stop_run_reversal_confirmation_bars': 1,
    #     'default_risk_per_trade_perc': 0.01, 'sl_atr_multiplier': 1.5, 'tp_atr_multiplier': 2.0,
    #     'atr_period_for_sl_tp': 14, 'atr_period_for_backtest': 14,
    #     'asset_quantity_precision': 3, 'asset_price_precision': 2, 'min_order_qty': 0.001
    # }
    # backtester_liquidity = BacktestEngine( market_data_provider, LiquidityPointsStrategy, strategy_params_liquidity,
    #     default_start_date, default_end_date, initial_capital, symbol, liquidity_timeframe, commission_rate)
    # liquidity_results_metrics = await backtester_liquidity.run_backtest()
    # if liquidity_results_metrics: logger.info(f"LiquidityPointsStrategy Metrics: {liquidity_results_metrics}") ...

    # Example: TrendAdaptationStrategy
    # logger.info(f"\n--- Starting Backtest for TrendAdaptationStrategy ---")
    # trend_micro_tf = "4h"
    # strategy_params_trend = { ... } # Define params
    # ... setup and run backtester_trend ...

    logger.info("Backtesting script finished.")

if __name__ == "__main__":
    asyncio.run(main())

```
