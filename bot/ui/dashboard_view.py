# bot/ui/dashboard_view.py
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QGridLayout, QTextEdit, QGroupBox
from PySide6.QtCore import Slot, Qt

class DashboardView(QWidget):
    def __init__(self, backend_controller=None, parent=None): # backend_controller for future interactions
        super().__init__(parent)
        self.backend_controller = backend_controller
        self.logger = getattr(backend_controller, 'logger', logging.getLogger('algo_trader_bot.Dashboard')) # Get logger from backend or default

        self._init_ui()
        self._connect_signals_to_slots() # For UI elements connecting to backend_controller methods
        # Backend signals to UI slots will be connected in gui_launcher.py using the global signals object

    def _init_ui(self):
        self.main_layout = QVBoxLayout(self)

        # --- Status and Control Group ---
        status_control_group = QGroupBox("Bot Control & Status")
        status_control_layout = QGridLayout()

        self.status_label = QLabel("Bot Status: Idle")
        self.status_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        status_control_layout.addWidget(self.status_label, 0, 0, 1, 2) # Span 2 columns

        self.api_connection_label = QLabel("API Connection: Disconnected")
        status_control_layout.addWidget(self.api_connection_label, 1, 0)

        self.start_bot_button = QPushButton("Start Bot")
        status_control_layout.addWidget(self.start_bot_button, 2, 0)
        self.stop_bot_button = QPushButton("Stop Bot")
        self.stop_bot_button.setEnabled(False) # Initially disabled
        status_control_layout.addWidget(self.stop_bot_button, 2, 1)

        status_control_group.setLayout(status_control_layout)
        self.main_layout.addWidget(status_control_group)

        # --- Financial Overview Group ---
        financial_group = QGroupBox("Financial Overview")
        financial_layout = QGridLayout()

        self.balance_label = QLabel("Balance: $0.00")
        financial_layout.addWidget(self.balance_label, 0, 0)
        self.pnl_open_label = QLabel("Open P&L: $0.00")
        financial_layout.addWidget(self.pnl_open_label, 0, 1)
        self.pnl_total_label = QLabel("Total Realized P&L: $0.00") # Realized P&L for the session/day
        financial_layout.addWidget(self.pnl_total_label, 0, 2)

        financial_group.setLayout(financial_layout)
        self.main_layout.addWidget(financial_group)

        # --- Market Info Group (Example for BTCUSDT) ---
        market_info_group = QGroupBox("Market Info (BTCUSDT)")
        market_info_layout = QGridLayout()

        self.btc_price_label = QLabel("Price: $0.00")
        market_info_layout.addWidget(self.btc_price_label, 0, 0)
        self.btc_change_label = QLabel("24h Change: 0.00%")
        market_info_layout.addWidget(self.btc_change_label, 0, 1)
        # Potentially add more market data fields here (e.g., volume, funding rate)

        market_info_group.setLayout(market_info_layout)
        self.main_layout.addWidget(market_info_group)

        # --- Activity Log ---
        log_group = QGroupBox("Activity Log")
        log_layout = QVBoxLayout()
        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setFixedHeight(200) # Initial height, can be adjusted
        log_layout.addWidget(self.log_display)
        log_group.setLayout(log_layout)
        self.main_layout.addWidget(log_group)

        self.main_layout.addStretch(1) # Add stretch at the end to push elements to the top
        self.setLayout(self.main_layout)

    def _connect_signals_to_slots(self):
        # Connect UI element signals (e.g., button clicks) to backend_controller methods
        if self.backend_controller:
            if hasattr(self.backend_controller, 'start_bot_async_wrapper'):
                self.start_bot_button.clicked.connect(self.backend_controller.start_bot_async_wrapper)
            else:
                self.logger.warning("Backend controller does not have 'start_bot_async_wrapper' method.")

            if hasattr(self.backend_controller, 'stop_bot_async_wrapper'):
                self.stop_bot_button.clicked.connect(self.backend_controller.stop_bot_async_wrapper)
            else:
                self.logger.warning("Backend controller does not have 'stop_bot_async_wrapper' method.")
        else:
            self.logger.warning("DashboardView initialized without a backend_controller. UI buttons will not function.")


    # --- Slots for updating UI from backend signals ---
    @Slot(str)
    def update_status_display(self, status_message: str):
        self.status_label.setText(f"Bot Status: {status_message}")
        is_running = status_message.lower() == "running" # Example condition
        self.start_bot_button.setEnabled(not is_running)
        self.stop_bot_button.setEnabled(is_running)
        self.logger.debug(f"Dashboard status updated: {status_message}")

    @Slot(str)
    def update_api_connection_display(self, status: str):
        self.api_connection_label.setText(f"API Connection: {status}")
        self.logger.debug(f"Dashboard API connection updated: {status}")

    @Slot(dict) # Expecting a dict like {'asset': 'USDT', 'total': 1000.0} or just a float
    def update_balance_display(self, balance_data: Any): # Changed to Any to be flexible
        if isinstance(balance_data, dict): # More detailed balance
            usdt_balance = balance_data.get('USDT', {}).get('total', 0.0) # Example structure
            self.balance_label.setText(f"Balance (USDT): ${float(usdt_balance):.2f}")
        elif isinstance(balance_data, (float, int)): # Simple total balance
            self.balance_label.setText(f"Balance: ${float(balance_data):.2f}")
        else:
            self.logger.warning(f"Received balance_data in unexpected format: {balance_data}")


    @Slot(float)
    def update_total_pnl_display(self, total_pnl: float):
        self.pnl_total_label.setText(f"Total Realized P&L: ${total_pnl:.2f}")

    @Slot(float)
    def update_open_pnl_display(self, open_pnl: float):
        self.pnl_open_label.setText(f"Open P&L: ${open_pnl:.2f}")

    @Slot(str, dict) # For market_data_updated signal (symbol, data_dict)
    def update_market_data_display(self, symbol: str, data: dict):
        if symbol == "BTCUSDT": # Example specific update
            self.btc_price_label.setText(f"Price: ${data.get('price', 'N/A')}")
            self.btc_change_label.setText(f"24h Change: {data.get('change', 'N/A')}")
        # Could be extended for a table or dynamic labels if more symbols are shown

    @Slot(str)
    def append_log_message(self, message: str):
        self.log_display.append(message)
        # Optional: Auto-scroll to the bottom
        # self.log_display.verticalScrollBar().setValue(self.log_display.verticalScrollBar().maximum())

# Example for standalone testing of the view
if __name__ == '__main__':
    import sys
    from PySide6.QtWidgets import QApplication
    import logging # Import logging for the test

    logging.basicConfig(level=logging.DEBUG) # Basic logger for test

    app = QApplication(sys.argv)

    # Create a dummy backend controller for testing signals
    class DummyUIControllerSignals(QObject): # Must be a QObject for signals
        status_updated = Signal(str)
        log_message_appended = Signal(str)
        balance_updated = Signal(float) # Simplified for test
        market_data_updated = Signal(str, dict)

        def __init__(self):
            super().__init__()
            self.logger = logging.getLogger('algo_trader_bot.DummyBackend') # For test

        def start_bot_async_wrapper(self):
            self.logger.info("Dummy Start Bot called")
            self.status_updated.emit("Simulating Start...")
            self.log_message_appended.emit("Attempting to start bot (simulated).")
            # Simulate some updates
            self.balance_updated.emit(9950.75)
            self.market_data_updated.emit("BTCUSDT", {"price": "29500.00", "change": "+0.50%"})
            self.status_updated.emit("Running (Simulated)")


        def stop_bot_async_wrapper(self):
            self.logger.info("Dummy Stop Bot called")
            self.status_updated.emit("Simulating Stop...")
            self.log_message_appended.emit("Attempting to stop bot (simulated).")
            self.status_updated.emit("Stopped (Simulated)")


    dummy_backend = DummyUIControllerSignals()
    dashboard = DashboardView(backend_controller=dummy_backend) # Pass dummy backend

    # Connect global signals (if they were used by backend) to dashboard slots for testing
    # In a real app, this is done in gui_launcher.py
    dummy_backend.status_updated.connect(dashboard.update_status_display)
    dummy_backend.log_message_appended.connect(dashboard.append_log_message)
    dummy_backend.balance_updated.connect(dashboard.update_balance_display)
    dummy_backend.market_data_updated.connect(dashboard.update_market_data_display)


    dashboard.setWindowTitle("Dashboard View Test")
    dashboard.resize(600, 400)
    dashboard.show()

    # Simulate some backend updates
    dummy_backend.status_updated.emit("Initializing...")
    dummy_backend.log_message_appended.emit("Dashboard test started.")
    dummy_backend.balance_updated.emit(10000.0)
    dummy_backend.market_data_updated.emit("BTCUSDT", {"price": "29000.00", "change": "-1.20%"})


    sys.exit(app.exec())

```
