import sys
import logging
from PySide6.QtWidgets import QApplication, QMainWindow, QTabWidget, QVBoxLayout, QWidget, QLabel, QMessageBox
from PySide6.QtCore import Slot, QMetaObject, Qt, Signal as PySideSignal
from typing import Any, Optional

try:
    from .dashboard_view import DashboardView
    from .config_view import ConfigView
    from .orders_view import OrdersAndPositionsView
    from .chart_view import ChartView # Import ChartView
    from .backtest_view import BacktestView # Import BacktestView
    from .qt_signals import signals
except ImportError as e:
    logging.basicConfig(level=logging.ERROR)
    logging.error(f"MainWindow ImportError: {e}")
    DashboardView = QWidget # type: ignore
    ConfigView = QWidget # type: ignore
    OrdersAndPositionsView = QWidget # type: ignore
    ChartView = QWidget # type: ignore
    BacktestView = QWidget # type: ignore
    class MockSignals: # type: ignore
        def __getattr__(self, name): return type('MockSignal', (PySideSignal,), {'emit': lambda *args: None})()
    signals = MockSignals() # type: ignore


class MainWindow(QMainWindow):
    logger = logging.getLogger('algo_trader_bot.MainWindow')
    aboutToClose = PySideSignal()

    def __init__(self, backend_controller: Optional[Any] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.backend_controller = backend_controller

        self.setWindowTitle("Algo Trading Bot")
        self.setGeometry(100, 100, 1300, 850)

        self.tab_widget = QTabWidget()
        self.setCentralWidget(self.tab_widget)

        self.dashboard_view = DashboardView(backend_controller=self.backend_controller)
        self.tab_widget.addTab(self.dashboard_view, "Dashboard")

        self.config_view = ConfigView(backend_controller=self.backend_controller)
        self.tab_widget.addTab(self.config_view, "Settings")

        self.orders_positions_view = OrdersAndPositionsView(backend_controller=self.backend_controller)
        self.tab_widget.addTab(self.orders_positions_view, "Orders & Positions")

        self.chart_view = ChartView(backend_controller=self.backend_controller) # Create ChartView
        self.tab_widget.addTab(self.chart_view, "Chart") # Add ChartView tab

        self.backtest_view = BacktestView(backend_controller=self.backend_controller) # Create BacktestView
        self.tab_widget.addTab(self.backtest_view, "Backtesting") # Add BacktestView tab

        self._connect_global_signals()

    def _connect_global_signals(self):
        try:
            # DashboardView signals
            signals.status_updated.connect(self.dashboard_view.update_status_display)
            signals.api_connection_updated.connect(self.dashboard_view.update_api_connection_display)
            signals.balance_updated.connect(self.dashboard_view.update_balance_display)
            signals.total_pnl_updated.connect(self.dashboard_view.update_total_pnl_display)
            signals.open_pnl_updated.connect(self.dashboard_view.update_open_pnl_display)
            signals.market_data_updated.connect(self.dashboard_view.update_market_data_display)
            signals.log_message_appended.connect(self.dashboard_view.append_log_message)

            # OrdersAndPositionsView signals
            if hasattr(self.orders_positions_view, 'populate_open_orders_table'):
                 signals.open_orders_updated.connect(self.orders_positions_view.populate_open_orders_table)
            if hasattr(self.orders_positions_view, 'populate_trade_history_table'):
                 signals.trade_history_updated.connect(self.orders_positions_view.populate_trade_history_table)
            if hasattr(self.orders_positions_view, 'populate_positions_table'):
                 signals.positions_updated.connect(self.orders_positions_view.populate_positions_table)

            # BacktestView signals
            if hasattr(self.backtest_view, 'update_progress_bar'):
                signals.backtest_progress_updated.connect(self.backtest_view.update_progress_bar)
            if hasattr(self.backtest_view, 'append_backtest_log'):
                signals.backtest_log_message.connect(self.backtest_view.append_backtest_log)
            if hasattr(self.backtest_view, 'display_backtest_results'): # For summary metrics
                signals.backtest_summary_results_ready.connect(self.backtest_view.display_backtest_results)
            if hasattr(self.backtest_view, 'display_simulated_trades'): # For trades table
                signals.backtest_trades_ready.connect(self.backtest_view.display_simulated_trades)
            if hasattr(self.backtest_view, 'plot_equity_curve'): # For equity curve
                signals.backtest_equity_curve_ready.connect(self.backtest_view.plot_equity_curve)

            # ChartView signals
            if hasattr(self.chart_view, 'handle_live_kline_data'):
                signals.live_kline_updated.connect(self.chart_view.handle_live_kline_data)
            # ChartView visualization signals
            if hasattr(self.chart_view, 'handle_new_trade_marker'):
                signals.chart_new_trade_marker.connect(self.chart_view.handle_new_trade_marker)
            if hasattr(self.chart_view, 'handle_position_update_for_chart'):
                signals.chart_position_update.connect(self.chart_view.handle_position_update_for_chart)

            # MainWindow general feedback signals
            signals.error_dialog_requested.connect(self.show_error_dialog)
            signals.status_bar_message_updated.connect(self.show_status_bar_message)

            self.logger.info("MainWindow connected to global backend signals for all views.")
        except AttributeError as e:
            self.logger.error(f"Error connecting global signals: {e}. View might be missing a slot.", exc_info=True)
        except Exception as e:
            self.logger.error(f"Unexpected error connecting global signals: {e}", exc_info=True)

    def closeEvent(self, event):
        logger_to_use = MainWindow.logger
        logger_to_use.info("Main window closeEvent triggered.")
        self.aboutToClose.emit()
        event.accept()

    @Slot(str, str)
    def show_error_dialog(self, title: str, message: str):
        self.logger.info(f"Displaying error dialog: Title='{title}', Message='{message}'")
        QMessageBox.critical(self, title, message)

    @Slot(str, int)
    def show_status_bar_message(self, message: str, timeout: int = 5000):
        # Ensure status bar is visible (usually is by default if messages are shown)
        # self.statusBar().setVisible(True) # May not be needed
        self.statusBar().showMessage(message, timeout)
        self.logger.debug(f"Status bar message: '{message}', Timeout: {timeout}ms")

if __name__ == '__main__':
    # ... (main test block remains the same) ...
    pass
```
