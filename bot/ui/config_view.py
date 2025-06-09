import logging
import asyncio
from typing import Dict, Optional, Any, List
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                             QPushButton, QComboBox, QGroupBox, QScrollArea, QFormLayout,
                             QMessageBox, QListWidget, QListWidgetItem, QSplitter,
                             QSpinBox, QDoubleSpinBox, QCheckBox)
from PySide6.QtCore import Slot, Qt, QSize # Added QSize

# For type hinting BotController
BotController = Any

class ConfigView(QWidget):
    def __init__(self, backend_controller: Optional[BotController] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.backend_controller = backend_controller
        self.logger = getattr(backend_controller, 'logger', logging.getLogger('algo_trader_bot')).getChild("ConfigView") # Get child logger

        self.param_input_widgets: Dict[str, QWidget] = {}
        self.current_editing_strategy_id: Optional[str] = None
        self.current_editing_strategy_type_name: Optional[str] = None
        self.current_strategy_params_meta: Optional[Dict[str, Any]] = None

        self._init_ui()
        self._connect_signals()
        self._load_initial_config()

    def _init_ui(self):
        config_tab_main_layout = QVBoxLayout(self)

        top_settings_group = QGroupBox("Bot & API Settings")
        top_settings_outer_layout = QVBoxLayout(top_settings_group)
        top_settings_layout = QVBoxLayout()

        api_keys_group = QGroupBox("API Configuration")
        api_keys_form_layout = QFormLayout(api_keys_group)
        self.testnet_api_key_input = QLineEdit()
        self.testnet_api_secret_input = QLineEdit(); self.testnet_api_secret_input.setEchoMode(QLineEdit.EchoMode.Password)
        api_keys_form_layout.addRow("Testnet API Key:", self.testnet_api_key_input)
        api_keys_form_layout.addRow("Testnet API Secret:", self.testnet_api_secret_input)
        self.mainnet_api_key_input = QLineEdit()
        self.mainnet_api_secret_input = QLineEdit(); self.mainnet_api_secret_input.setEchoMode(QLineEdit.EchoMode.Password)
        api_keys_form_layout.addRow("Mainnet API Key:", self.mainnet_api_key_input)
        api_keys_form_layout.addRow("Mainnet API Secret:", self.mainnet_api_secret_input)
        api_buttons_layout = QHBoxLayout()
        self.save_api_keys_button = QPushButton("Save API Keys"); api_buttons_layout.addWidget(self.save_api_keys_button)
        self.test_connection_button = QPushButton("Test API (Testnet)"); api_buttons_layout.addWidget(self.test_connection_button)
        api_keys_form_layout.addRow(api_buttons_layout)
        top_settings_layout.addWidget(api_keys_group)

        general_settings_group = QGroupBox("General Bot Settings")
        general_settings_form_layout = QFormLayout(general_settings_group)
        self.log_level_combo = QComboBox(); self.log_level_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
        general_settings_form_layout.addRow("Log Level:", self.log_level_combo)
        self.save_general_settings_button = QPushButton("Save General Settings")
        general_settings_form_layout.addRow(self.save_general_settings_button)
        top_settings_layout.addWidget(general_settings_group)

        self.config_status_label = QLabel(""); self.config_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top_settings_layout.addWidget(self.config_status_label)

        self.save_all_config_button = QPushButton("Save All Bot Configuration") # New button
        top_settings_layout.addWidget(self.save_all_config_button, 0, Qt.AlignmentFlag.AlignCenter)


        top_settings_outer_layout.addLayout(top_settings_layout)
        config_tab_main_layout.addWidget(top_settings_group)

        self.strategy_splitter = QSplitter(Qt.Orientation.Horizontal)
        left_panel_widget = QWidget(); left_panel_layout = QVBoxLayout(left_panel_widget)
        loaded_strategies_group = QGroupBox("Strategies Instances")
        loaded_strat_layout = QVBoxLayout(loaded_strategies_group)
        self.loaded_strategies_list = QListWidget(); loaded_strat_layout.addWidget(self.loaded_strategies_list)
        strat_buttons_layout = QHBoxLayout()
        self.edit_strategy_button = QPushButton("View/Edit"); strat_buttons_layout.addWidget(self.edit_strategy_button)
        self.remove_strategy_button = QPushButton("Remove"); strat_buttons_layout.addWidget(self.remove_strategy_button)
        loaded_strat_layout.addLayout(strat_buttons_layout); left_panel_layout.addWidget(loaded_strategies_group)
        add_strategy_group = QGroupBox("Add New Strategy")
        add_strat_form = QFormLayout(add_strategy_group)
        self.new_strategy_type_combo = QComboBox(); add_strat_form.addRow("Type:", self.new_strategy_type_combo)
        self.new_strategy_id_input = QLineEdit(); self.new_strategy_id_input.setPlaceholderText("Unique strategy ID")
        add_strat_form.addRow("ID:", self.new_strategy_id_input)
        self.add_new_strategy_button = QPushButton("Add Instance"); add_strat_form.addRow(self.add_new_strategy_button)
        left_panel_layout.addWidget(add_strategy_group); left_panel_layout.addStretch(1)
        self.strategy_splitter.addWidget(left_panel_widget)

        right_panel_widget = QWidget(); right_panel_layout = QVBoxLayout(right_panel_widget)
        self.details_group_box = QGroupBox("Strategy Parameters")
        details_main_layout = QVBoxLayout(self.details_group_box)
        details_top_layout = QHBoxLayout()
        self.current_editing_label = QLabel("Select or add strategy."); details_top_layout.addWidget(self.current_editing_label, 1)
        self.save_strategy_params_button = QPushButton("Save Param Changes"); self.save_strategy_params_button.setVisible(False)
        details_top_layout.addWidget(self.save_strategy_params_button); details_main_layout.addLayout(details_top_layout)
        self.strategy_params_scroll_area = QScrollArea(); self.strategy_params_scroll_area.setWidgetResizable(True)
        self.strategy_params_widget = QWidget()
        self.strategy_params_form_layout = QFormLayout(self.strategy_params_widget)
        self.strategy_params_scroll_area.setWidget(self.strategy_params_widget)
        details_main_layout.addWidget(self.strategy_params_scroll_area); right_panel_layout.addWidget(self.details_group_box)
        self.strategy_splitter.addWidget(right_panel_widget)
        self.strategy_splitter.setSizes([350, 650])

        config_tab_main_layout.addWidget(self.strategy_splitter)
        self.setLayout(config_tab_main_layout)

    def _connect_signals(self):
        self.save_api_keys_button.clicked.connect(self.handle_save_api_keys)
        self.test_connection_button.clicked.connect(self.handle_test_api_connection)
        self.save_general_settings_button.clicked.connect(self.handle_save_general_settings)
        self.save_all_config_button.clicked.connect(self.handle_save_all_config) # Connect new button
        self.loaded_strategies_list.currentItemChanged.connect(self.on_loaded_strategy_selected)
        self.edit_strategy_button.clicked.connect(self.on_edit_strategy_button_clicked)
        self.remove_strategy_button.clicked.connect(self.handle_remove_strategy)
        self.save_strategy_params_button.clicked.connect(self.handle_save_strategy_params)
        self.new_strategy_type_combo.currentIndexChanged.connect(self.handle_new_strategy_type_selected_for_defaults)
        self.add_new_strategy_button.clicked.connect(self.handle_add_new_strategy)

    def _load_initial_config(self):
        # ... (same as before)
        self.config_status_label.setText("")
        if not self.backend_controller: self.logger.warning("BC not available for config load."); self.config_status_label.setText("Err: Backend N/A"); return
        try:
            if hasattr(self.backend_controller, 'get_general_settings'):
                settings = self.backend_controller.get_general_settings(); self.log_level_combo.setCurrentText(settings.get('log_level', 'INFO'))
            if hasattr(self.backend_controller, 'get_api_keys_config'):
                api_keys_conf = self.backend_controller.get_api_keys_config()
                self.testnet_api_key_input.setText(api_keys_conf.get('testnet_key', '')); self.testnet_api_secret_input.setPlaceholderText("Unchanged")
                self.mainnet_api_key_input.setText(api_keys_conf.get('mainnet_key', '')); self.mainnet_api_secret_input.setPlaceholderText("Unchanged")
            self.refresh_loaded_strategies_list(); self.populate_new_strategy_types_combo()
            self.clear_params_form("Select strategy or add new.")
            self.logger.info("Initial config loaded into ConfigView.")
        except Exception as e: self.logger.error(f"Error loading initial config: {e}", exc_info=True); self.config_status_label.setText(f"Error: {e}")

    def refresh_loaded_strategies_list(self):
        # ... (same as before)
        self.loaded_strategies_list.clear()
        if self.backend_controller and hasattr(self.backend_controller, 'get_loaded_strategies_info'):
            try:
                strategies_info = self.backend_controller.get_loaded_strategies_info()
                for strategy_id, info in strategies_info.items():
                    item_text = f"{strategy_id} ({info.get('type_name', 'Unknown')}) - {'Active' if info.get('is_active') else 'Inactive'}"
                    list_item = QListWidgetItem(item_text); list_item.setData(Qt.ItemDataRole.UserRole, strategy_id)
                    self.loaded_strategies_list.addItem(list_item)
            except Exception as e: self.logger.error(f"Error refreshing strategies list: {e}", exc_info=True)

    def populate_new_strategy_types_combo(self):
        # ... (same as before)
        self.new_strategy_type_combo.clear(); self.new_strategy_type_combo.addItem("")
        if self.backend_controller and hasattr(self.backend_controller, 'get_available_strategy_types_names'):
            try: types = self.backend_controller.get_available_strategy_types_names(); self.new_strategy_type_combo.addItems(types)
            except Exception as e: self.logger.error(f"Error populating strategy types: {e}", exc_info=True)

    def on_edit_strategy_button_clicked(self):
        # ... (same as before)
        current_item = self.loaded_strategies_list.currentItem()
        if current_item: self.on_loaded_strategy_selected(current_item, None)
        else: QMessageBox.information(self, "Edit", "Select a strategy to edit."); self.clear_params_form("Select strategy to edit.")

    def on_loaded_strategy_selected(self, current_item: Optional[QListWidgetItem], previous_item: Optional[QListWidgetItem]):
        # ... (same as before)
        if not current_item or not self.backend_controller : self.clear_params_form("Select strategy."); return
        strategy_id = current_item.data(Qt.ItemDataRole.UserRole)
        try:
            strategies_info = self.backend_controller.get_loaded_strategies_info()
            strategy_info = strategies_info.get(strategy_id)
            if not strategy_info: self.clear_params_form(f"Err: No info for {strategy_id}."); return
            type_name = strategy_info.get('type_name', 'Unknown'); params_meta = self.backend_controller.get_strategy_default_params_by_type_name(type_name)
            self.populate_params_form(params_meta, current_values=strategy_info.get('params',{}), editing_id=strategy_id, type_name=type_name)
        except Exception as e: self.logger.error(f"Err selecting strategy {strategy_id}: {e}", exc_info=True); self.clear_params_form(f"Err loading {strategy_id}")

    def handle_new_strategy_type_selected_for_defaults(self):
        # ... (same as before)
        strategy_type_name = self.new_strategy_type_combo.currentText()
        if not strategy_type_name or not self.backend_controller: self.clear_params_form("Select type for defaults."); return
        try:
            params_meta = self.backend_controller.get_strategy_default_params_by_type_name(strategy_type_name)
            self.populate_params_form(params_meta, editing_id=None, type_name=strategy_type_name)
            self.new_strategy_id_input.setFocus()
        except Exception as e: self.logger.error(f"Err loading defaults for {strategy_type_name}: {e}", exc_info=True); self.clear_params_form(f"Err loading defaults for {strategy_type_name}")

    def clear_params_form(self, message: str):
        # ... (same as before)
        while self.strategy_params_form_layout.count():
            item = self.strategy_params_form_layout.takeAt(0); widget = item.widget()
            if widget: widget.deleteLater()
        self.param_input_widgets.clear(); self.current_editing_strategy_id=None; self.current_editing_strategy_type_name=None
        self.current_strategy_params_meta=None; self.current_editing_label.setText(message); self.save_strategy_params_button.setVisible(False)

    def populate_params_form(self, params_with_meta: Optional[Dict[str, Any]], current_values: Optional[Dict[str, Any]] = None, editing_id: Optional[str] = None, type_name: str = ""):
        # ... (same as before)
        self.clear_params_form("")
        if not params_with_meta: self.current_editing_label.setText(f"No param definition for '{type_name}'."); return
        self.current_editing_strategy_id=editing_id; self.current_editing_strategy_type_name=type_name; self.current_strategy_params_meta = params_with_meta
        self.details_group_box.setTitle(f"Params for '{editing_id}' ({type_name})" if editing_id else f"Defaults for New '{type_name}'")
        self.current_editing_label.setText(f"Editing: {editing_id}" if editing_id else f"New: {type_name} (Defaults Loaded)")
        for name, meta in params_with_meta.items():
            val = current_values.get(name, meta.get('default')) if current_values else meta.get('default')
            lbl_text = meta.get('desc', name).replace('_',' ').title(); lbl = QLabel(lbl_text+":")
            w: QWidget; ptype = meta.get('type','str')
            if ptype=='int': w=QSpinBox(); w.setRange(meta.get('min',-2**31),meta.get('max',2**31-1)); w.setSingleStep(meta.get('step',1)); w.setValue(int(val) if val is not None else 0)
            elif ptype=='float': w=QDoubleSpinBox(); w.setRange(meta.get('min',-1e12),meta.get('max',1e12)); w.setSingleStep(meta.get('step',0.01)); w.setDecimals(meta.get('decimals',4)); w.setValue(float(val) if val is not None else 0.0)
            elif ptype=='bool': w=QCheckBox(); w.setChecked(bool(val) if val is not None else False)
            elif ptype=='str' and 'options' in meta and isinstance(meta['options'],list): w=QComboBox(); w.addItems(meta['options']); w.setCurrentText(str(val) if val is not None else "")
            else: w=QLineEdit(); w.setText(str(val) if val is not None else "")
            self.strategy_params_form_layout.addRow(lbl,w); self.param_input_widgets[name]=w
        self.save_strategy_params_button.setVisible(bool(editing_id))

    def _get_params_from_form(self) -> Optional[Dict[str, Any]]:
        # ... (same as before)
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
                if meta.get('is_list_of_dict', False): # Handle list of dicts (e.g. DCA safety_orders)
                    try: params[name] = json.loads(val) if isinstance(val, str) else val # Expects JSON string
                    except json.JSONDecodeError: self.logger.error(f"Invalid JSON for {name}: {val}"); params[name] = meta.get('default', [])
                elif ptype=='int': params[name]=int(val) if val is not None else meta.get('default',0)
                elif ptype=='float': params[name]=float(val) if val is not None else meta.get('default',0.0)
                elif ptype=='bool': params[name]=bool(val) if val is not None else meta.get('default',False)
                else: params[name]=str(val) if val is not None else meta.get('default',"")
            return params
        except ValueError as ve: self.logger.error(f"Type conversion error: {ve}"); QMessageBox.warning(self,"Param Error",f"Invalid value. Details: {ve}"); return None
        except Exception as e: self.logger.error(f"Error getting params: {e}",exc_info=True); QMessageBox.critical(self,"Error",f"Could not read params: {e}"); return None

    # --- Handler Methods ---
    @Slot()
    def handle_save_all_config(self):
        if self.backend_controller and hasattr(self.backend_controller, 'save_persistent_config'):
            self.logger.info("ConfigView: Save All Configuration button clicked.")
            # BotController.save_persistent_config is sync
            self.backend_controller.save_persistent_config() # type: ignore
            QMessageBox.information(self, "Configuration", "All bot configurations saved.")
            self.config_status_label.setText("All configurations saved.")
        else:
            QMessageBox.warning(self, "Error", "Backend controller not available to save all configurations.")

    # ... (other handlers: handle_save_strategy_params, handle_add_new_strategy, handle_remove_strategy,
    #      handle_save_api_keys, handle_test_api_connection, handle_save_general_settings remain largely the same,
    #      ensure they use asyncio.create_task for async backend calls if controller methods are async)
    @Slot()
    def handle_save_strategy_params(self):
        if not self.current_editing_strategy_id or not self.backend_controller: return
        updated_values = self._get_params_from_form();
        if updated_values is None: return
        async def do_save():
            success = await self.backend_controller.update_strategy_parameters(self.current_editing_strategy_id, updated_values) # type: ignore
            if success: QMessageBox.information(self,"Save Params",f"Params for '{self.current_editing_strategy_id}' saved."); self.refresh_loaded_strategies_list()
            else: QMessageBox.warning(self,"Save Error",f"Failed to save params for '{self.current_editing_strategy_id}'.")
        asyncio.create_task(do_save())
    @Slot()
    def handle_add_new_strategy(self):
        if not self.backend_controller: return
        stype=self.new_strategy_type_combo.currentText(); sid=self.new_strategy_id_input.text().strip()
        if not stype or not sid: QMessageBox.warning(self,"Input Error","Type and ID required."); return
        params_form = self._get_params_from_form()
        if params_form is None: return
        async def do_add():
            success = await self.backend_controller.add_new_strategy_instance(stype, sid, params_form) # type: ignore
            if success: QMessageBox.information(self,"Add Strategy",f"Strategy '{sid}' added."); self.refresh_loaded_strategies_list(); self.new_strategy_id_input.clear()
            else: QMessageBox.warning(self,"Add Error",f"Failed to add '{sid}'.")
        asyncio.create_task(do_add())
    @Slot()
    def handle_remove_strategy(self):
        item = self.loaded_strategies_list.currentItem()
        if not item or not self.backend_controller: return
        sid = item.data(Qt.ItemDataRole.UserRole)
        if QMessageBox.question(self,"Confirm Remove",f"Remove '{sid}'?") == QMessageBox.StandardButton.Yes:
            async def do_remove():
                success = await self.backend_controller.remove_strategy_instance(sid) # type: ignore
                if success: QMessageBox.information(self,"Remove",f"Strategy '{sid}' removed."); self.refresh_loaded_strategies_list(); self.clear_params_form("Select or add.")
                else: QMessageBox.warning(self,"Remove Error",f"Failed to remove '{sid}'.")
            asyncio.create_task(do_remove())
    @Slot()
    def handle_save_api_keys(self):
        if not self.backend_controller : QMessageBox.critical(self, "Error", "Backend N/A."); return
        tn_k=self.testnet_api_key_input.text(); tn_s=self.testnet_api_secret_input.text()
        mn_k=self.mainnet_api_key_input.text(); mn_s=self.mainnet_api_secret_input.text()
        self.backend_controller.save_api_keys(tn_k, tn_s if tn_s else "", mn_k, mn_s if mn_s else "") # Pass empty if placeholder not cleared
        self.config_status_label.setText("API Keys saved. Restart required."); QMessageBox.information(self, "API Keys", "API Keys saved. Restart required.")
    @Slot()
    def handle_test_api_connection(self):
        if not self.backend_controller : QMessageBox.critical(self, "Error", "Backend N/A."); return
        key=self.testnet_api_key_input.text(); secret=self.testnet_api_secret_input.text()
        if not key or not secret: QMessageBox.warning(self, "API Test", "Testnet Key/Secret needed."); return
        self.config_status_label.setText("Testing Testnet API...")
        async def do_test():
            success, message = await self.backend_controller.test_api_connection(key, secret, is_testnet=True) # type: ignore
            self.config_status_label.setText(f"Testnet: {message}");
            if success: QMessageBox.information(self, "API Test", f"Testnet: {message}")
            else: QMessageBox.warning(self, "API Test", f"Testnet: {message}")
        asyncio.create_task(do_test())
    @Slot()
    def handle_save_general_settings(self):
        if not self.backend_controller : QMessageBox.critical(self, "Error", "Backend N/A."); return
        ll = self.log_level_combo.currentText()
        self.backend_controller.save_general_settings({'log_level': ll})
        self.config_status_label.setText("Settings saved. Log level change may require restart.")
        QMessageBox.information(self, "Settings", "Settings saved. Log level change may require restart.")

# if __name__ == '__main__': ...
```
