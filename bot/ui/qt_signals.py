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

    # ChartView live updates
    live_kline_updated = Signal(dict)

    # Error and status bar signals for better UI feedback
    error_dialog_requested = Signal(str, str)  # title, message
    status_bar_message_updated = Signal(str, int) # message, timeout_ms (0 for persistent)

    # Chart specific visualization signals
    chart_new_trade_marker = Signal(dict) # {'symbol': str, 'timestamp': float_epoch_sec, 'price': float, 'side': 'BUY'/'SELL', 'quantity': float}
    chart_position_update = Signal(dict) # {'symbol': str, 'entry_price': float, 'quantity': float, 'side': 'LONG'/'SHORT'/'FLAT', 'timestamp': float_epoch_sec}

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

    # Example usage for new signals
    def handle_error_dialog(title: str, message: str): print(f"UI Slot (Error Dialog): Title='{title}', Msg='{message}'")
    def handle_statusbar_msg(message: str, timeout: int): print(f"UI Slot (StatusBar): Msg='{message}', Timeout={timeout}ms")
    def handle_live_kline(kline_data: dict): print(f"UI Slot (Live Kline): {kline_data.get('s')} {kline_data.get('c')}")
    def handle_trade_marker(trade_info: dict): print(f"UI Slot (Trade Marker): {trade_info}")
    def handle_pos_update(pos_info: dict): print(f"UI Slot (Position Update): {pos_info}")

    signals.error_dialog_requested.connect(handle_error_dialog)
    signals.status_bar_message_updated.connect(handle_statusbar_msg)
    signals.live_kline_updated.connect(handle_live_kline)
    signals.chart_new_trade_marker.connect(handle_trade_marker)
    signals.chart_position_update.connect(handle_pos_update)


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

    signals.error_dialog_requested.emit("Test Error", "This is a test error message.")
    signals.status_bar_message_updated.emit("Test status bar message.", 3000)
    signals.live_kline_updated.emit({'s': 'BTCUSDT', 'c': '50000', 'i': '1m'})
    signals.chart_new_trade_marker.emit({'symbol': 'BTCUSDT', 'timestamp': 1672515780.0, 'price': 25000, 'side': 'BUY', 'quantity': 0.1})
    signals.chart_position_update.emit({'symbol': 'BTCUSDT', 'entry_price': 25000, 'quantity': 0.1, 'side': 'LONG', 'timestamp': 1672515780.0})


    signals.status_updated.disconnect(handle_status)
```
