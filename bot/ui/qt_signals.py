# bot/ui/qt_signals.py
from PySide6.QtCore import QObject, Signal
from typing import List, Dict, Any # For type hinting list[dict]

class BackendSignals(QObject):
    # Signals from backend to UI
    status_updated = Signal(str)
    log_message_appended = Signal(str)
    api_connection_updated = Signal(str)
    balance_updated = Signal(float)
    total_pnl_updated = Signal(float)
    open_pnl_updated = Signal(float)
    market_data_updated = Signal(str, dict)

    open_orders_updated = Signal(list) # List[Dict[str, Any]]
    trade_history_updated = Signal(list) # List[Dict[str, Any]]
    positions_updated = Signal(list) # List[Dict[str, Any]]

    order_update_event = Signal(dict)
    strategy_status_updated = Signal(str, str)

    # Backtest signals
    backtest_progress_updated = Signal(int)
    backtest_log_message = Signal(str)
    backtest_summary_results_ready = Signal(dict) # For summary performance metrics
    backtest_trades_ready = Signal(list)      # For the list of simulated trades
    backtest_equity_curve_ready = Signal(list) # For equity curve data points

    def __init__(self):
        super().__init__()

signals = BackendSignals()

if __name__ == '__main__':
    def handle_status(status_msg: str): print(f"UI Slot (Status): {status_msg}")
    def handle_log(log_msg: str): print(f"UI Slot (Log): {log_msg}")
    def handle_balance(balance_val: float): print(f"UI Slot (Balance): {balance_val}")
    def handle_open_orders(orders: list): print(f"UI Slot (Open Orders): {len(orders)} orders")
    def handle_bt_prog(prog: int): print(f"UI Slot (BT Progress): {prog}%")
    def handle_bt_log(msg: str): print(f"UI Slot (BT Log): {msg}")
    def handle_bt_summary_res(res: dict): print(f"UI Slot (BT Summary Results): {res}")
    def handle_bt_trades(trades: list): print(f"UI Slot (BT Trades): {len(trades)} trades")
    def handle_bt_equity(equity: list): print(f"UI Slot (BT Equity): {len(equity)} points")


    signals.status_updated.connect(handle_status)
    signals.log_message_appended.connect(handle_log)
    signals.balance_updated.connect(handle_balance)
    signals.open_orders_updated.connect(handle_open_orders)
    signals.backtest_progress_updated.connect(handle_bt_prog)
    signals.backtest_log_message.connect(handle_bt_log)
    signals.backtest_summary_results_ready.connect(handle_bt_summary_res)
    signals.backtest_trades_ready.connect(handle_bt_trades)
    signals.backtest_equity_curve_ready.connect(handle_bt_equity)

    signals.status_updated.emit("Bot Initializing...")
    signals.balance_updated.emit(10000.0)
    signals.log_message_appended.emit("Test log message from backend.")
    signals.open_orders_updated.emit([{'id':1, 'symbol':'BTCUSDT'}, {'id':2, 'symbol':'ETHUSDT'}])
    signals.status_updated.emit("Bot Running")

    signals.backtest_log_message.emit("Backtest starting...")
    signals.backtest_progress_updated.emit(50)
    signals.backtest_summary_results_ready.emit({'pnl': 100, 'trades': 5})
    signals.backtest_trades_ready.emit([{'symbol':'BTCUSDT', 'pnl': 50}, {'symbol':'BTCUSDT', 'pnl': 50}])
    signals.backtest_equity_curve_ready.emit([{'ts':1, 'bal':100},{'ts':2, 'bal':110}])


    signals.status_updated.disconnect(handle_status)
```
