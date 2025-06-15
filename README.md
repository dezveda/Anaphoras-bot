# Algo Trading Bot for Binance Futures (BTC/USDT)

## Overview

This project is an algorithmic trading bot designed to operate on the Binance Futures market, specifically for the BTC/USDT pair. It provides a graphical user interface (GUI) for monitoring market data, managing strategies, viewing orders and positions, and visualizing performance through charts and backtesting results. The bot supports both live/paper trading on Binance Testnet and Mainnet, as well as historical backtesting of trading strategies.

## Features

*   **Graphical User Interface (GUI)**: Built with PySide6, offering:
    *   **Dashboard**: View bot status, API connection, account balance, overall P&L (realized and unrealized), and live BTC/USDT price.
    *   **Charts**: Candlestick charts with common indicators (SMA, EMA, RSI) and real-time updates. Visualizes executed trades and current position entry points.
    *   **Order & Position Management**: View open orders, trade history, and current positions. Ability to cancel orders and close positions manually.
    *   **Strategy Configuration**: Load, unload, and configure parameters for various trading strategies.
    *   **Backtesting Interface**: Run strategies against historical data, view performance metrics, trade lists, and equity curves.
*   **Multiple Configurable Strategies**: Includes implementations for:
    *   Advanced DCA (Dollar Cost Averaging)
    *   Pivot Points
    *   Liquidity-based (Stop Runs)
    *   Trend Adaptation (identifies market regimes)
    *   Indicator Heuristics (combines RSI and EMA signals, adaptable by trend regime)
*   **Risk Management**: Basic risk management for position sizing based on a percentage of available balance and ATR-based stop-loss.
*   **Backtesting Engine**: Allows testing strategies on historical K-line data, providing metrics like Net P&L, Win Rate, Max Drawdown, Sharpe Ratio, etc.
*   **Real-time Data**: Utilizes Binance WebSockets for live K-lines, mark prices, and user account/order updates. REST API is used for placing orders, fetching historical data, and other account interactions.
*   **Persistence**: Strategy configurations, API keys (in `.env`), and general bot settings (like log level) are persisted across sessions (`bot_config.json`).
*   **Binance Futures Focus**: Primarily designed for BTC/USDT on Binance Futures Testnet, with Mainnet capability (use with caution).

## Tech Stack

*   **Programming Language**: Python 3.9+
*   **GUI Framework**: PySide6
*   **Data Manipulation & Analysis**: pandas, numpy
*   **Charting**: pyqtgraph
*   **API Communication**: websockets (for Binance WebSockets), requests (for REST API)
*   **Configuration**: python-dotenv, JSON
*   **Technical Indicators**: TA-Lib (optional, some indicators are manually calculated)

## Prerequisites

*   **Python**: Version 3.9 or newer.
*   **Binance API Key and Secret**:
    *   For testing, obtain from [Binance Testnet](https://testnet.binancefuture.com/).
    *   For live trading, obtain from your main Binance account (use with extreme caution).
*   **TA-Lib (Technical Analysis Library)**:
    *   Some strategies may rely on TA-Lib. Installing TA-Lib can be challenging, especially on Windows.
    *   **Windows**: Often requires downloading pre-compiled `.whl` files (e.g., from [Christoph Gohlke's Unofficial Python Binaries page](https://www.lfd.uci.edu/~gohlke/pythonlibs/#ta-lib)) and installing via `pip install TA_Lib‑XYZ‑cpXYZ‑cpXYZ‑win_amd64.whl`. You might also need to install Microsoft Visual C++ Build Tools.
    *   **Linux/macOS**: Usually simpler, e.g., `sudo apt-get install libta-lib0 libta-lib-dev` then `pip install TA-Lib`.
    *   **Alternative**: Consider using a Linux environment (like WSL on Windows or a VM) for easier TA-Lib setup if you encounter issues. The bot includes some manually calculated indicators (RSI, EMA) to reduce dependency where possible.

## Setup & Installation

1.  **Clone the Repository**:
    ```bash
    git clone <repository_url>
    cd <repository_directory>
    ```

2.  **Create and Activate a Python Virtual Environment**:
    ```bash
    python -m venv venv
    ```
    *   On Windows: `venv\Scripts\activate`
    *   On macOS/Linux: `source venv/bin/activate`

3.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure API Keys**:
    *   Rename the `.env.example` file in the project root to `.env`.
    *   Open the `.env` file and add your Binance API Key and Secret. For Testnet (recommended for initial use):
        ```env
        BINANCE_TESTNET_API_KEY="YOUR_TESTNET_KEY"
        BINANCE_TESTNET_API_SECRET="YOUR_TESTNET_SECRET"

        # Optionally, for mainnet (USE WITH EXTREME CAUTION):
        # BINANCE_MAINNET_API_KEY="YOUR_MAINNET_KEY"
        # BINANCE_MAINNET_API_SECRET="YOUR_MAINNET_SECRET"

        # Optional: Set default log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        # LOG_LEVEL="INFO"
        ```

5.  **Initial Bot Configuration (`bot_config.json`)**:
    *   The bot uses `bot_config.json` (created in the project root) to store strategy configurations and general settings (like log level if not set in `.env`).
    *   If this file doesn't exist on the first run of the GUI, it will be created with default settings when you save configurations via the GUI.
    *   You can configure strategies, log levels, etc., through the "Settings" tab in the GUI. These settings are saved to `bot_config.json`.

## Running the Bot

Ensure your virtual environment is activated before running the scripts.

*   **GUI Mode (Recommended for Live/Paper Trading and Configuration)**:
    Run from the project root directory:
    ```bash
    python -m scripts.gui_launcher
    ```
    Use the GUI to:
    *   Connect to Testnet (or Mainnet, cautiously).
    *   Load, configure, and save strategies.
    *   Start/Stop the bot for live or paper trading.
    *   Monitor performance and manage trades.

*   **Backtesting Mode**:
    Run from the project root directory:
    ```bash
    python -m scripts.run_backtests
    ```
    This script runs pre-configured backtests defined within it. You can modify `scripts/run_backtests.py` to test different strategies, symbols, timeframes, and parameters. Backtest results, including logs and trade lists, are typically saved in the `logs/backtests/` directory.

## Directory Structure

```
<project_root>/
├── bot/                     # Core bot application logic
│   ├── connectors/          # Binance API communication (REST & WebSocket)
│   ├── core/                # Core components (MarketDataProvider, OrderManager, RiskManager, BacktestEngine, LoggerSetup, ConfigLoader)
│   ├── strategies/          # Trading strategy implementations
│   └── ui/                  # PySide6 GUI components (MainWindow, Views, custom widgets)
├── scripts/                 # Launcher scripts
│   ├── gui_launcher.py      # Launches the main GUI application
│   └── run_backtests.py     # Script for running backtesting sessions
├── logs/                    # Directory for log files (created automatically by logger_setup)
│   ├── gui/                 # Logs from GUI mode
│   └── backtests/           # Logs and results from backtesting runs
├── .env.example             # Example environment file for API keys
├── .env                     # Actual environment file (gitignored)
├── bot_config.json          # Stores strategy configurations and general settings (created/updated by GUI)
├── requirements.txt         # Python dependencies
└── README.md                # This file
```

## Disclaimer

Trading cryptocurrencies involves significant risk. This bot is provided for educational and experimental purposes only. It should be used with extreme caution, especially when interacting with live trading accounts and real funds.

**Always test thoroughly on Binance Testnet before considering any live trading.**

The authors and contributors are not responsible for any financial losses incurred through the use of this software. Use at your own risk.
