import logging
import asyncio
from typing import Dict, Optional, Any, List
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
                             QLabel, QComboBox, QPushButton, QDateEdit, QDoubleSpinBox,
                             QSpinBox, QFormLayout, QTextEdit, QProgressBar, QScrollArea,
                             QMessageBox) # Added QMessageBox
from PySide6.QtCore import Slot, QDateTime, Qt, QDate

# For type hinting BotController
BotController = Any

class BacktestView(QWidget):
    def __init__(self, backend_controller: Optional[BotController] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.backend_controller = backend_controller
        self.logger = getattr(backend_controller, 'logger', logging.getLogger('algo_trader_bot.BacktestView')).getChild("BacktestView")

        self.param_input_widgets: Dict[str, QWidget] = {}
        self.current_strategy_params_meta: Optional[Dict[str, Any]] = None

        self._init_ui()
        self._connect_signals()
        self._load_initial_data()

    def _init_ui(self):
        self.main_layout = QVBoxLayout(self)

        # --- Configuration Group ---
        config_group = QGroupBox("Backtest Configuration")
        config_grid_layout = QGridLayout(config_group) # Use QGridLayout for more control

        # Left side of config (Inputs)
        inputs_form_layout = QFormLayout()
        self.strategy_type_combo = QComboBox()
        inputs_form_layout.addRow(QLabel("Strategy Type:"), self.strategy_type_combo)

        self.start_date_edit = QDateEdit(QDateTime.currentDateTime().addMonths(-1).date()) # Default to 1 month ago
        self.start_date_edit.setCalendarPopup(True)
        inputs_form_layout.addRow(QLabel("Start Date:"), self.start_date_edit)

        self.end_date_edit = QDateEdit(QDateTime.currentDateTime().date()) # Default to today
        self.end_date_edit.setCalendarPopup(True)
        inputs_form_layout.addRow(QLabel("End Date:"), self.end_date_edit)

        self.timeframe_combo = QComboBox()
        self.timeframe_combo.addItems(['1m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '12h', '1d']) # Common timeframes
        self.timeframe_combo.setCurrentText('1h')
        inputs_form_layout.addRow(QLabel("Timeframe:"), self.timeframe_combo)

        self.initial_capital_spinbox = QDoubleSpinBox()
        self.initial_capital_spinbox.setRange(1.0, 1_000_000_000.0); self.initial_capital_spinbox.setValue(10000.0)
        self.initial_capital_spinbox.setPrefix("$ "); self.initial_capital_spinbox.setDecimals(2)
        inputs_form_layout.addRow(QLabel("Initial Capital:"), self.initial_capital_spinbox)

        self.commission_rate_spinbox = QDoubleSpinBox()
        self.commission_rate_spinbox.setRange(0.0, 1.0); self.commission_rate_spinbox.setValue(0.04)
        self.commission_rate_spinbox.setSuffix(" %"); self.commission_rate_spinbox.setDecimals(4)
        inputs_form_layout.addRow(QLabel("Commission Rate (%):"), self.commission_rate_spinbox)

        config_grid_layout.addLayout(inputs_form_layout, 0, 0)

        # Right side of config (Strategy Parameters - Dynamic)
        self.strategy_params_group = QGroupBox("Strategy Parameters")
        self.strategy_params_form_layout = QFormLayout(self.strategy_params_group)
        strategy_params_scroll = QScrollArea()
        strategy_params_scroll.setWidgetResizable(True)
        strategy_params_scroll.setWidget(self.strategy_params_group)
        config_grid_layout.addWidget(strategy_params_scroll, 0, 1) # Add to grid

        config_grid_layout.setColumnStretch(1, 1) # Allow strategy params to take more space

        self.main_layout.addWidget(config_group)

        # --- Control and Progress Group ---
        control_progress_group = QGroupBox("Control & Progress")
        control_progress_layout = QVBoxLayout(control_progress_group)
        self.start_backtest_button = QPushButton("Start Backtest")
        control_progress_layout.addWidget(self.start_backtest_button)
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        # self.progress_bar.setVisible(False) # Optionally hide until backtest starts
        control_progress_layout.addWidget(self.progress_bar)
        self.main_layout.addWidget(control_progress_group)

        # --- Results Group ---
        results_group = QGroupBox("Backtest Results")
        results_layout = QVBoxLayout(results_group)
        self.results_summary_text = QTextEdit()
        self.results_summary_text.setReadOnly(True)
        self.results_summary_text.setFixedHeight(200) # Adjust as needed
        results_layout.addWidget(self.results_summary_text)
        self.main_layout.addWidget(results_group)

        self.main_layout.addStretch(1)
        self.setLayout(self.main_layout)

    def _connect_signals(self):
        self.strategy_type_combo.currentTextChanged.connect(self.on_strategy_type_selected_for_backtest)
        self.start_backtest_button.clicked.connect(self.handle_start_backtest)

    def _load_initial_data(self):
        if self.backend_controller and hasattr(self.backend_controller, 'get_available_strategy_types_names'):
            try:
                strategy_types = self.backend_controller.get_available_strategy_types_names()
                self.strategy_type_combo.addItems([""] + strategy_types) # Add blank initial item
                if strategy_types: # Auto-select first strategy to load its params
                    # self.on_strategy_type_selected_for_backtest(strategy_types[0]) # This might be too soon if backend not fully ready
                    pass # User will select
                self.logger.info("BacktestView: Strategy types loaded for combo box.")
            except Exception as e:
                self.logger.error(f"Error loading strategy types for backtest view: {e}", exc_info=True)
        else:
            self.logger.warning("Backend controller not available for loading strategy types in BacktestView.")

    @Slot(str)
    def on_strategy_type_selected_for_backtest(self, strategy_type_name: str):
        self.clear_strategy_params_form()
        if not strategy_type_name: return # Blank selected

        if self.backend_controller and hasattr(self.backend_controller, 'get_strategy_default_params_by_type_name'):
            try:
                params_with_meta = self.backend_controller.get_strategy_default_params_by_type_name(strategy_type_name)
                self.populate_strategy_params_form(params_with_meta)
                self.logger.debug(f"Populated params form for strategy type: {strategy_type_name}")
            except Exception as e:
                self.logger.error(f"Error populating params for strategy type {strategy_type_name}: {e}", exc_info=True)
        else:
            self.logger.warning("Backend controller not available for populating strategy params.")

    def clear_strategy_params_form(self):
        while self.strategy_params_form_layout.count():
            child = self.strategy_params_form_layout.takeAt(0)
            if child.widget(): child.widget().deleteLater()
        self.param_input_widgets.clear()
        self.current_strategy_params_meta = None


    def populate_strategy_params_form(self, params_with_meta: Optional[Dict[str, Any]]):
        self.clear_strategy_params_form()
        if not params_with_meta:
            self.strategy_params_form_layout.addRow(QLabel("No parameters defined for this strategy type."))
            return

        self.current_strategy_params_meta = params_with_meta
        for param_name, meta in params_with_meta.items():
            current_val = meta.get('default')
            desc = meta.get('desc', param_name)
            label_text = f"{meta.get('label', desc.replace('_', ' ').title())}:" # Use meta label or prettify name
            label = QLabel(label_text)

            widget: QWidget
            param_type = meta.get('type', 'str')

            if param_type == 'int':
                widget = QSpinBox(); widget.setRange(meta.get('min', -2**31), meta.get('max', 2**31-1))
                widget.setSingleStep(meta.get('step',1)); widget.setValue(int(current_val) if current_val is not None else 0)
            elif param_type == 'float':
                widget = QDoubleSpinBox(); widget.setRange(meta.get('min', -1e12), meta.get('max', 1e12))
                widget.setSingleStep(meta.get('step',0.01)); widget.setDecimals(meta.get('decimals',4))
                widget.setValue(float(current_val) if current_val is not None else 0.0)
            elif param_type == 'bool':
                widget = QCheckBox(); widget.setChecked(bool(current_val) if current_val is not None else False)
            elif param_type == 'str' and 'options' in meta and isinstance(meta['options'], list):
                widget = QComboBox(); widget.addItems(meta['options'])
                if current_val is not None: widget.setCurrentText(str(current_val))
            else: # Default to string/QLineEdit
                widget = QLineEdit();
                if current_val is not None: widget.setText(str(current_val))

            self.strategy_params_form_layout.addRow(label, widget)
            self.param_input_widgets[param_name] = widget

    def _get_strategy_params_from_form(self) -> Optional[Dict[str, Any]]:
        if not self.current_strategy_params_meta: return None
        params: Dict[str,Any]={};
        try:
            for name,widget in self.param_input_widgets.items():
                meta=self.current_strategy_params_meta.get(name,{}); ptype=meta.get('type','str')
                val: Any = None
                if isinstance(widget,QLineEdit): val=widget.text()
                elif isinstance(widget,QSpinBox): val=widget.value()
                elif isinstance(widget,QDoubleSpinBox): val=widget.value()
                elif isinstance(widget,QCheckBox): val=widget.isChecked()
                elif isinstance(widget,QComboBox): val=widget.currentText()

                if ptype=='int': params[name]=int(val) if val is not None else meta.get('default',0)
                elif ptype=='float': params[name]=float(val) if val is not None else meta.get('default',0.0)
                elif ptype=='bool': params[name]=bool(val) if val is not None else meta.get('default',False)
                # For list_of_dict (like DCA safety_orders), this needs special handling (e.g. JSON string input)
                # For now, assuming simple types from get_default_params.
                else: params[name]=str(val) if val is not None else meta.get('default',"")
            return params
        except ValueError as ve: self.logger.error(f"Type conversion error: {ve}"); QMessageBox.warning(self,"Param Error",f"Invalid value. Details: {ve}"); return None
        except Exception as e: self.logger.error(f"Error getting params: {e}",exc_info=True); QMessageBox.critical(self,"Error",f"Could not read params: {e}"); return None

    @Slot()
    def handle_start_backtest(self):
        if not self.backend_controller or not hasattr(self.backend_controller, 'run_backtest_from_ui'):
            QMessageBox.critical(self, "Error", "Backend controller not available or misconfigured."); return

        strategy_type_name = self.strategy_type_combo.currentText()
        if not strategy_type_name: QMessageBox.warning(self, "Config Error", "Please select a strategy type."); return

        strategy_custom_params = self._get_strategy_params_from_form()
        if strategy_custom_params is None: return # Error message already shown

        backtest_config = {
            'strategy_type_name': strategy_type_name,
            'start_date': self.start_date_edit.date().toString("yyyy-MM-dd") + " 00:00:00", # Use QDate.toString()
            'end_date': self.end_date_edit.date().toString("yyyy-MM-dd") + " 23:59:59",
            'timeframe': self.timeframe_combo.currentText(),
            'initial_capital': self.initial_capital_spinbox.value(),
            'commission_rate': self.commission_rate_spinbox.value(), # Already in % form, will be /100 in controller
            'strategy_params': strategy_custom_params,
            'symbol': strategy_custom_params.get('symbol', 'BTCUSDT') # Get symbol from strategy params or default
        }

        self.logger.info(f"Starting backtest with config: {backtest_config}")
        self.start_backtest_button.setEnabled(False)
        self.progress_bar.setVisible(True); self.progress_bar.setValue(0)
        self.results_summary_text.clear()
        self.results_summary_text.append("Backtest starting...")

        # Call backend controller's async method
        asyncio.create_task(self.backend_controller.run_backtest_from_ui(backtest_config)) # type: ignore

    @Slot(int)
    def update_progress_bar(self, value: int):
        self.progress_bar.setValue(value)

    @Slot(dict)
    def display_backtest_results(self, results: dict):
        self.results_summary_text.append("\n--- Backtest Performance Metrics ---")
        for key, value in results.items():
            if isinstance(value, float):
                self.results_summary_text.append(f"{key.replace('_',' ').title()}: {value:.2f}")
            else:
                self.results_summary_text.append(f"{key.replace('_',' ').title()}: {value}")

        self.start_backtest_button.setEnabled(True)
        if self.progress_bar.value() < 100 : self.progress_bar.setValue(100) # Mark as complete
        # Could hide progress_bar again: self.progress_bar.setVisible(False)
        # Or if trades data is part of results, populate a table here.

    @Slot(str)
    def append_backtest_log(self, message: str):
        self.results_summary_text.append(message) # Append detailed log messages

if __name__ == '__main__':
    sys._called_from_test = False # type: ignore
    logging.basicConfig(level=logging.DEBUG)
    app = QApplication(sys.argv)

    class DummyBackendForBacktestView(QObject): # type: ignore
        def __init__(self): super().__init__(); self.logger = logging.getLogger("DummyBTBackend"); self.loop = asyncio.get_event_loop()
        def get_available_strategy_types_names(self): return ["MyStrategy1", "MyStrategy2"]
        def get_strategy_default_params_by_type_name(self, type_name):
            if type_name == "MyStrategy1": return {'paramA': {'type':'int', 'default':10, 'desc':'Param A'}}
            return {}
        async def run_backtest_from_ui(self, config):
            self.logger.info(f"DummyBackend: run_backtest_from_ui called with {config['strategy_type_name']}")
            # Simulate signals
            from bot.ui.qt_signals import signals # Assuming global signals
            signals.backtest_log_message.emit(f"Backtest for {config['strategy_type_name']} started (simulated).")
            for i in range(1, 11): await asyncio.sleep(0.2); signals.backtest_progress_updated.emit(i * 10)
            signals.backtest_results_ready.emit({'total_pnl': 123.45, 'num_trades': 5, 'win_rate': 60.0})

    backend = DummyBackendForBacktestView()
    window = BacktestView(backend_controller=backend) # type: ignore
    window.setWindowTitle("Backtest View Standalone Test"); window.setGeometry(50, 50, 700, 800); window.show()
    sys.exit(app.exec())

```
