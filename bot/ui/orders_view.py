import logging
import asyncio
from typing import List, Dict, Any, Optional

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QTabWidget, QTableWidget,
                             QTableWidgetItem, QPushButton, QHBoxLayout, QHeaderView,
                             QAbstractItemView, QMessageBox)
from PySide6.QtCore import Slot, Qt

# For type hinting BotController
BotController = Any

class OrdersAndPositionsView(QWidget):
    def __init__(self, backend_controller: Optional[BotController] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.backend_controller = backend_controller
        self.logger = getattr(backend_controller, 'logger', logging.getLogger('algo_trader_bot.OrdersView')).getChild("OrdersView")

        self._init_ui()
        self._configure_tables()
        self._connect_signals() # Connect UI element signals to internal handlers

        # Initial data load will be triggered by gui_launcher after UI is shown
        # or if a "connect" button is used. For now, can call manually for testing if needed.
        # self.load_initial_data()

    def _init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.tabs = QTabWidget()

        # --- Open Orders Tab ---
        self.open_orders_widget = QWidget()
        open_orders_layout = QVBoxLayout(self.open_orders_widget)
        self.open_orders_table = QTableWidget()
        open_orders_buttons_layout = QHBoxLayout()
        self.refresh_open_orders_button = QPushButton("Refresh Open Orders")
        self.cancel_selected_button = QPushButton("Cancel Selected Order")
        open_orders_buttons_layout.addWidget(self.refresh_open_orders_button)
        open_orders_buttons_layout.addWidget(self.cancel_selected_button)
        open_orders_buttons_layout.addStretch()
        open_orders_layout.addLayout(open_orders_buttons_layout)
        open_orders_layout.addWidget(self.open_orders_table)
        self.tabs.addTab(self.open_orders_widget, "Open Orders")

        # --- Trade History Tab ---
        self.trade_history_widget = QWidget()
        trade_history_layout = QVBoxLayout(self.trade_history_widget)
        self.trade_history_table = QTableWidget()
        trade_history_buttons_layout = QHBoxLayout()
        self.refresh_trade_history_button = QPushButton("Refresh Trade History")
        trade_history_buttons_layout.addWidget(self.refresh_trade_history_button)
        trade_history_buttons_layout.addStretch()
        trade_history_layout.addLayout(trade_history_buttons_layout)
        trade_history_layout.addWidget(self.trade_history_table)
        self.tabs.addTab(self.trade_history_widget, "Trade History")

        # --- Positions Tab ---
        self.positions_widget = QWidget()
        positions_layout = QVBoxLayout(self.positions_widget)
        self.positions_table = QTableWidget()
        positions_buttons_layout = QHBoxLayout()
        self.refresh_positions_button = QPushButton("Refresh Positions")
        self.close_selected_position_button = QPushButton("Close Selected Position (Market)")
        positions_buttons_layout.addWidget(self.refresh_positions_button)
        positions_buttons_layout.addWidget(self.close_selected_position_button)
        positions_buttons_layout.addStretch()
        positions_layout.addLayout(positions_buttons_layout)
        positions_layout.addWidget(self.positions_table)
        self.tabs.addTab(self.positions_widget, "Current Positions")

        self.main_layout.addWidget(self.tabs)
        self.setLayout(self.main_layout)

    def _configure_tables(self):
        # Open Orders Table
        self.open_orders_table.setColumnCount(11)
        self.open_orders_table.setHorizontalHeaderLabels([
            "Symbol", "Order ID", "Client ID", "Side", "Type", "Price",
            "Quantity", "Filled Qty", "Status", "Time", "Position Side"
        ])
        self._apply_common_table_settings(self.open_orders_table)

        # Trade History Table
        self.trade_history_table.setColumnCount(10)
        self.trade_history_table.setHorizontalHeaderLabels([
            "Symbol", "Trade ID", "Order ID", "Side", "Price", "Quantity",
            "Commission", "Comm. Asset", "Time", "Realized P&L"
        ])
        self._apply_common_table_settings(self.trade_history_table)

        # Positions Table
        self.positions_table.setColumnCount(8)
        self.positions_table.setHorizontalHeaderLabels([
            "Symbol", "Side", "Quantity", "Entry Price", "Mark Price",
            "Unrealized P&L", "Liq. Price", "Margin"
        ])
        self._apply_common_table_settings(self.positions_table)

    def _apply_common_table_settings(self, table: QTableWidget):
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.setAlternatingRowColors(True)
        table.setSortingEnabled(True) # Allow column sorting

    def _connect_signals(self):
        self.refresh_open_orders_button.clicked.connect(self.handle_refresh_open_orders)
        self.refresh_trade_history_button.clicked.connect(self.handle_refresh_trade_history)
        self.refresh_positions_button.clicked.connect(self.handle_refresh_positions)
        self.cancel_selected_button.clicked.connect(self.handle_cancel_selected_order)
        self.close_selected_position_button.clicked.connect(self.handle_close_selected_position)

        # Connections to global signals (signals.open_orders_updated, etc.)
        # will be done in gui_launcher.py or MainWindow, where this view is instantiated.

    def load_initial_data(self):
        """Called to load initial data for all tables when view becomes active or bot starts."""
        self.logger.info("OrdersAndPositionsView: Loading initial data.")
        self.handle_refresh_open_orders()
        self.handle_refresh_trade_history()
        self.handle_refresh_positions()

    @Slot()
    def handle_refresh_open_orders(self):
        if self.backend_controller and hasattr(self.backend_controller, 'request_open_orders_update'):
            self.logger.info("Refreshing open orders...")
            asyncio.create_task(self.backend_controller.request_open_orders_update()) # type: ignore
        else: self.logger.warning("Backend controller not available for refreshing open orders.")

    @Slot()
    def handle_refresh_trade_history(self):
        if self.backend_controller and hasattr(self.backend_controller, 'request_trade_history_update'):
            self.logger.info("Refreshing trade history...")
            # TODO: Add symbol selection for trade history if needed, for now default
            asyncio.create_task(self.backend_controller.request_trade_history_update(symbol="BTCUSDT", limit=50)) # type: ignore
        else: self.logger.warning("Backend controller not available for refreshing trade history.")

    @Slot()
    def handle_refresh_positions(self):
        if self.backend_controller and hasattr(self.backend_controller, 'request_positions_update'):
            self.logger.info("Refreshing positions...")
            asyncio.create_task(self.backend_controller.request_positions_update()) # type: ignore
        else: self.logger.warning("Backend controller not available for refreshing positions.")

    @Slot()
    def handle_cancel_selected_order(self):
        selected_rows = self.open_orders_table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.information(self, "Cancel Order", "Please select an order to cancel.")
            return
        # Assuming Order ID is in the second column (index 1), Symbol in first (index 0)
        order_id_item = self.open_orders_table.item(selected_rows[0].row(), 1)
        symbol_item = self.open_orders_table.item(selected_rows[0].row(), 0)

        if order_id_item and symbol_item:
            order_id_str = order_id_item.text()
            symbol_str = symbol_item.text()
            self.logger.info(f"Requesting cancellation for order ID: {order_id_str} on symbol {symbol_str}")
            if self.backend_controller and hasattr(self.backend_controller, 'cancel_order_ui'):
                 asyncio.create_task(self.backend_controller.cancel_order_ui(order_id=order_id_str, symbol=symbol_str)) # type: ignore
            else: self.logger.warning("Backend controller not available for cancelling order.")
        else:
            QMessageBox.warning(self, "Cancel Order Error", "Could not retrieve order ID or symbol from selected row.")


    @Slot()
    def handle_close_selected_position(self):
        selected_rows = self.positions_table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.information(self, "Close Position", "Please select a position to close.")
            return
        # Assuming Symbol is in column 0, Side in column 1
        symbol_item = self.positions_table.item(selected_rows[0].row(), 0)
        side_item = self.positions_table.item(selected_rows[0].row(), 1) # e.g. "LONG" or "SHORT"

        if symbol_item and side_item:
            symbol_str = symbol_item.text()
            position_side_str = side_item.text().upper() # Ensure it's "LONG" or "SHORT"

            self.logger.info(f"Requesting to close {position_side_str} position for symbol {symbol_str}")
            if self.backend_controller and hasattr(self.backend_controller, 'close_position_ui'):
                asyncio.create_task(self.backend_controller.close_position_ui(symbol=symbol_str, position_side_to_close=position_side_str)) # type: ignore
            else: self.logger.warning("Backend controller not available for closing position.")
        else:
            QMessageBox.warning(self, "Close Position Error", "Could not retrieve symbol or side from selected row.")


    def _populate_table(self, table: QTableWidget, data: List[Dict[str, Any]], headers: List[str]):
        table.setRowCount(0) # Clear existing rows
        table.setColumnCount(len(headers)) # Ensure column count matches headers
        table.setHorizontalHeaderLabels(headers)

        if not data:
            # self.logger.debug(f"No data to populate {table.objectName() if table.objectName() else 'table'}.")
            return

        table.setRowCount(len(data))
        for row_idx, row_data in enumerate(data):
            for col_idx, header in enumerate(headers):
                # Map header to potential keys in data (case-insensitive, flexible)
                # This is a simple direct mapping. Real data might need more complex parsing.
                item_value = "N/A"
                if header in row_data: item_value = str(row_data[header])
                elif header.lower() in row_data: item_value = str(row_data[header.lower()])
                elif header.replace(" ", "").lower() in row_data: item_value = str(row_data[header.replace(" ", "").lower()])

                # Specific formatting for certain fields
                if header in ["Time", "Entry Time", "Close Time"] and item_value != "N/A":
                    try: # Assuming timestamp in ms
                        item_value = QDateTime.fromMSecsSinceEpoch(int(item_value)).toUTC().toString("yyyy-MM-dd HH:mm:ss")
                    except ValueError: pass # Keep as string if not a valid timestamp

                table.setItem(row_idx, col_idx, QTableWidgetItem(item_value))
        table.resizeColumnsToContents()

    @Slot(list)
    def populate_open_orders_table(self, orders_data: List[Dict[str, Any]]):
        headers = ["Symbol", "Order ID", "Client ID", "Side", "Type", "Price", "Quantity", "Filled Qty", "Status", "Time", "Position Side"]
        # Example data keys from Binance: symbol, orderId, clientOrderId, side, type, price, origQty, executedQty, status, time, positionSide
        self._populate_table(self.open_orders_table, orders_data, headers)
        self.logger.info(f"Open orders table populated with {len(orders_data)} orders.")

    @Slot(list)
    def populate_trade_history_table(self, history_data: List[Dict[str, Any]]):
        headers = ["Symbol", "Trade ID", "Order ID", "Side", "Price", "Quantity", "Commission", "Comm. Asset", "Time", "Realized P&L"]
        # Example data keys: symbol, id, orderId, side, price, qty, commission, commissionAsset, time, realizedPnl
        self.logger.info(f"Trade history table received {len(history_data)} trades. Headers: {headers}")
        self._populate_table(self.trade_history_table, history_data, headers)


    @Slot(list)
    def populate_positions_table(self, positions_data: List[Dict[str, Any]]):
        headers = ["Symbol", "Side", "Quantity", "Entry Price", "Mark Price", "Unrealized P&L", "Liq. Price", "Margin"]
        # Example data keys: symbol, positionSide, positionAmt, entryPrice, markPrice, unRealizedProfit, liquidationPrice, isolatedMargin / margin (depends on mode)
        self._populate_table(self.positions_table, positions_data, headers)
        self.logger.info(f"Positions table populated with {len(positions_data)} positions.")


if __name__ == '__main__':
    import sys
    from PySide6.QtWidgets import QApplication
    logging.basicConfig(level=logging.DEBUG)

    app = QApplication(sys.argv)
    # Dummy backend for testing UI elements functionality
    class DummyOrdersBackend(QObject):
        def __init__(self): super().__init__(); self.logger = logging.getLogger("DummyOrdersBackend")
        @Slot()
        def request_open_orders_update(self): self.logger.info("DummyBackend: request_open_orders_update called")
        @Slot()
        def request_trade_history_update(self, symbol, limit): self.logger.info(f"DummyBackend: request_trade_history_update for {symbol} limit {limit} called")
        @Slot()
        def request_positions_update(self): self.logger.info("DummyBackend: request_positions_update called")
        @Slot(str, str)
        def cancel_order_ui(self, order_id, symbol): self.logger.info(f"DummyBackend: cancel_order_ui for {order_id} on {symbol} called")
        @Slot(str, str)
        def close_position_ui(self, symbol, side): self.logger.info(f"DummyBackend: close_position_ui for {symbol} side {side} called")

    dummy_backend = DummyOrdersBackend()
    view = OrdersAndPositionsView(backend_controller=dummy_backend)
    view.setWindowTitle("Orders and Positions View Test")
    view.resize(800, 600)
    view.show()

    # Simulate some data population
    test_open_orders = [
        {'symbol': 'BTCUSDT', 'orderId': 123, 'clientOrderId': 'abc', 'side': 'BUY', 'type': 'LIMIT', 'price': '30000', 'origQty': '0.001', 'executedQty': '0', 'status': 'NEW', 'time': str(int(time.time()*1000)), 'positionSide': 'BOTH'},
        {'symbol': 'ETHUSDT', 'orderId': 124, 'clientOrderId': 'def', 'side': 'SELL', 'type': 'LIMIT', 'price': '2000', 'origQty': '0.01', 'executedQty': '0', 'status': 'NEW', 'time': str(int(time.time()*1000)), 'positionSide': 'SHORT'},
    ]
    view.populate_open_orders_table(test_open_orders)

    test_positions = [
        {'symbol': 'BTCUSDT', 'positionSide': 'LONG', 'positionAmt': '0.002', 'entryPrice': '29500', 'markPrice': '30000', 'unRealizedProfit': '10.00', 'liquidationPrice': '25000', 'isolatedMargin': '59.00'},
    ]
    view.populate_positions_table(test_positions)

    sys.exit(app.exec())

```
