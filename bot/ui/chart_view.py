import sys
import logging
from typing import List, Dict, Any, Optional
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton, QCheckBox, QSpinBox # Added QCheckBox, QSpinBox
from PySide6.QtCore import Slot, QDateTime, Qt
import pyqtgraph as pg
import pandas as pd
import numpy as np
import asyncio

# Custom CandlestickItem (simplified version)
class CandlestickItem(pg.GraphicsObject):
    def __init__(self, data: List[Dict[str, Any]]):
        super().__init__()
        self.data = data
        self.generatePicture()

    def generatePicture(self):
        self.picture = pg.QtGui.QPicture()
        if not self.data: return
        p = pg.QtGui.QPainter(self.picture)
        try:
            for candle in self.data:
                x, o, h, l, c = candle['t'], candle['o'], candle['h'], candle['l'], candle['c']
                candle_body_width = candle.get('w', 0.8) * 0.8 # Use 80% of interval for body, rest for spacing

                p.setPen(pg.mkPen('w', width=1))
                p.drawLine(pg.QtCore.QPointF(x, l), pg.QtCore.QPointF(x, h)) # Wick

                brush_color = Qt.green if o <= c else Qt.red
                p.setBrush(pg.mkBrush(brush_color))
                p.setPen(pg.mkPen(brush_color)) # Pen same color as brush for body
                p.drawRect(pg.QtCore.QRectF(x - candle_body_width / 2.0, o, candle_body_width, c - o))
        finally:
            p.end()

    def paint(self, p: pg.QtGui.QPainter, *args):
        if self.picture.isNull(): return
        p.drawPicture(0, 0, self.picture)

    def boundingRect(self) -> pg.QtCore.QRectF:
        if not self.data: return pg.QtCore.QRectF()
        min_t = min(d['t'] - d.get('w', 0.8) / 2.0 for d in self.data)
        max_t = max(d['t'] + d.get('w', 0.8) / 2.0 for d in self.data)
        min_price = min(d['l'] for d in self.data)
        max_price = max(d['h'] for d in self.data)
        return pg.QtCore.QRectF(min_t, min_price, (max_t - min_t), (max_price - min_price))


class ChartView(QWidget):
    def __init__(self, backend_controller: Optional[Any] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.backend_controller = backend_controller
        self.logger = getattr(backend_controller, 'logger', logging.getLogger('algo_trader_bot_ui')).getChild("ChartView")

        self._init_ui()
        self._connect_signals()
        self.candlestick_data_for_plotting: List[Dict[str, Any]] = []
        self.current_chart_symbol_tf: Optional[Tuple[str, str]] = None # e.g. ('BTCUSDT', '1h')

        self.trade_markers_plot: Optional[pg.ScatterPlotItem] = None
        self.position_line: Optional[pg.InfiniteLine] = None
        # self.position_fill_item = None # Deferred
        # self.load_initial_chart_data() # Called from gui_launcher after window is shown

    def _init_ui(self):
        self.main_layout = QVBoxLayout(self)

        # --- Top Controls Layout ---
        top_controls_layout = QHBoxLayout()
        self.symbol_label = QLabel("Symbol: BTCUSDT (Fixed)")
        top_controls_layout.addWidget(self.symbol_label)
        top_controls_layout.addWidget(QLabel("Timeframe:"))
        self.timeframe_combo = QComboBox()
        self.timeframe_combo.addItems(['1m', '5m', '15m', '30m', '1h', '4h', '1d'])
        self.timeframe_combo.setCurrentText('1h')
        top_controls_layout.addWidget(self.timeframe_combo)
        self.load_chart_button = QPushButton("Load/Refresh Chart")
        top_controls_layout.addWidget(self.load_chart_button)
        top_controls_layout.addStretch()
        self.main_layout.addLayout(top_controls_layout)

        # --- Indicator Controls Layout ---
        indicator_controls_layout = QHBoxLayout()
        self.sma_checkbox = QCheckBox("SMA"); indicator_controls_layout.addWidget(self.sma_checkbox)
        self.sma_period_spinbox = QSpinBox(); self.sma_period_spinbox.setRange(1,200); self.sma_period_spinbox.setValue(20); indicator_controls_layout.addWidget(self.sma_period_spinbox)

        self.ema_checkbox = QCheckBox("EMA"); indicator_controls_layout.addWidget(self.ema_checkbox)
        self.ema_period_spinbox = QSpinBox(); self.ema_period_spinbox.setRange(1,200); self.ema_period_spinbox.setValue(50); indicator_controls_layout.addWidget(self.ema_period_spinbox)

        self.rsi_checkbox = QCheckBox("RSI"); indicator_controls_layout.addWidget(self.rsi_checkbox)
        self.rsi_period_spinbox = QSpinBox(); self.rsi_period_spinbox.setRange(2,100); self.rsi_period_spinbox.setValue(14); indicator_controls_layout.addWidget(self.rsi_period_spinbox)
        indicator_controls_layout.addStretch()
        self.main_layout.addLayout(indicator_controls_layout)


        # --- Plotting Area ---
        pg.setConfigOptions(antialias=True, background='k', foreground='w')
        self.plot_widget_layout = pg.GraphicsLayoutWidget()
        self.main_layout.addWidget(self.plot_widget_layout)

        # Price Plot
        self.price_plot = self.plot_widget_layout.addPlot(row=0, col=0)
        self.price_plot.showGrid(x=True, y=True, alpha=0.3)
        self.price_plot.setLabel('left', "Price (USDT)")
        self.date_axis = pg.DateAxisItem(orientation='bottom')
        self.price_plot.setAxisItems({'bottom': self.date_axis})
        self.candlestick_item: Optional[CandlestickItem] = None

        # Add ScatterPlotItem for trade markers
        self.trade_markers_plot = pg.ScatterPlotItem(name="Trades", pxMode=False) # pxMode=False for scalable symbols
        self.price_plot.addItem(self.trade_markers_plot)

        self.sma_plot_item = self.price_plot.plot(pen='y', name='SMA')
        self.ema_plot_item = self.price_plot.plot(pen='c', name='EMA')

        # RSI Plot (below price plot)
        self.plot_widget_layout.nextRow() # Move to the next row in the layout
        self.rsi_plot_widget = self.plot_widget_layout.addPlot(row=1, col=0) # Explicitly use name for plot item
        self.rsi_plot_widget.setLabel('left', "RSI")
        self.rsi_plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.rsi_plot_widget.setXLink(self.price_plot) # Link X axes
        self.rsi_plot_widget.setLimits(yMin=0, yMax=100)
        self.rsi_plot_item = self.rsi_plot_widget.plot(pen='m', name='RSI')
        self.rsi_ob_line = pg.InfiniteLine(pos=70, angle=0, movable=False, pen=pg.mkPen('w', style=Qt.PenStyle.DotLine)) # Corrected Qt.DotLine
        self.rsi_os_line = pg.InfiniteLine(pos=30, angle=0, movable=False, pen=pg.mkPen('w', style=Qt.PenStyle.DotLine)) # Corrected Qt.DotLine
        self.rsi_plot_widget.addItem(self.rsi_ob_line)
        self.rsi_plot_widget.addItem(self.rsi_os_line)

        # Set relative heights for price and RSI plots
        self.plot_widget_layout.ci.layout.setRowStretchFactor(0, 3) # Price plot takes 3/4 of space
        self.plot_widget_layout.ci.layout.setRowStretchFactor(1, 1) # RSI plot takes 1/4 of space

        self.chart_status_label = QLabel("Load chart data.") # Status label for chart
        self.main_layout.addWidget(self.chart_status_label, 0, Qt.AlignmentFlag.AlignCenter)


    def _connect_signals(self):
        self.load_chart_button.clicked.connect(self.handle_load_refresh_chart)
        self.timeframe_combo.currentTextChanged.connect(self.handle_load_refresh_chart)
        # Connect indicator controls to refresh chart
        self.sma_checkbox.clicked.connect(self.handle_load_refresh_chart)
        self.sma_period_spinbox.valueChanged.connect(self.handle_load_refresh_chart)
        self.ema_checkbox.clicked.connect(self.handle_load_refresh_chart)
        self.ema_period_spinbox.valueChanged.connect(self.handle_load_refresh_chart)
        self.rsi_checkbox.clicked.connect(self.handle_load_refresh_chart)
        self.rsi_period_spinbox.valueChanged.connect(self.handle_load_refresh_chart)

    def _get_candle_width_seconds(self, timeframe_str: str) -> float:
        # ... (implementation from previous step)
        if 'm' in timeframe_str: return int(timeframe_str.replace('m', '')) * 60 * 0.8
        elif 'h' in timeframe_str: return int(timeframe_str.replace('h', '')) * 3600 * 0.8
        elif 'd' in timeframe_str.lower(): return int(timeframe_str.lower().replace('d', '')) * 86400 * 0.8
        return 3600 * 0.8

    def _prepare_candlestick_data(self, klines_df: pd.DataFrame, timeframe_str: str) -> List[Dict[str, Any]]:
        # ... (implementation from previous step)
        chart_data = [];
        if klines_df is None or klines_df.empty: return chart_data
        candle_width_secs = self._get_candle_width_seconds(timeframe_str)
        if not isinstance(klines_df.index, pd.DatetimeIndex):
            self.logger.warning("Kline DF index not DatetimeIndex."); return []
        for idx_timestamp, row in klines_df.iterrows():
            chart_data.append({'t': idx_timestamp.timestamp(), 'o': float(row['open']), 'h': float(row['high']),
                               'l': float(row['low']), 'c': float(row['close']), 'w': candle_width_secs})
        return chart_data


    @Slot()
    def handle_load_refresh_chart(self):
        # ... (implementation from previous step)
        if not self.backend_controller or not hasattr(self.backend_controller, 'get_historical_klines_for_chart'):
            self.logger.warning("Backend controller not available for chart data."); self.update_chart_data(pd.DataFrame(), self.timeframe_combo.currentText()); return

        symbol = "BTCUSDT"; timeframe = self.timeframe_combo.currentText()
        self.current_chart_symbol_tf = (symbol, timeframe) # Store current chart focus
        self.chart_status_label.setText(f"Loading {symbol} {timeframe}...")
        self.logger.info(f"Loading chart: {symbol} {timeframe}...")

        async def fetch_and_update():
            try:
                df = await self.backend_controller.get_historical_klines_for_chart(symbol, timeframe, limit=200)
                self.update_chart_data(df if df is not None else pd.DataFrame(), timeframe)
                # After historical data is loaded and plotted, subscribe to live updates
                if hasattr(self.backend_controller, 'subscribe_to_chart_klines'):
                    await self.backend_controller.subscribe_to_chart_klines(symbol, timeframe)
                self.chart_status_label.setText(f"Displaying {symbol} {timeframe} - Live")
            except Exception as e:
                self.logger.error(f"Error fetching/updating chart: {e}", exc_info=True)
                self.update_chart_data(pd.DataFrame(), timeframe)
                self.chart_status_label.setText(f"Error loading {symbol} {timeframe}")

        if self.backend_controller.loop and self.backend_controller.loop.is_running(): # type: ignore
            asyncio.create_task(fetch_and_update())
        # else: asyncio.run(fetch_and_update()) # Avoid asyncio.run if loop might be managed elsewhere

    def load_initial_chart_data(self): self.handle_load_refresh_chart()

    def _plot_indicators(self, klines_df_for_indicators: pd.DataFrame):
        self.sma_plot_item.clear(); self.ema_plot_item.clear(); self.rsi_plot_item.clear()
        if klines_df_for_indicators is None or klines_df_for_indicators.empty:
            return

        # Ensure 'close' column is float
        klines_df_for_indicators['close'] = klines_df_for_indicators['close'].astype(float)

        # X-axis data (timestamps in epoch seconds)
        # Ensure index is DatetimeIndex before converting
        if not isinstance(klines_df_for_indicators.index, pd.DatetimeIndex):
            self.logger.warning("Indicator klines_df index is not DatetimeIndex. Cannot plot indicators.")
            # Attempt to convert if 'timestamp' column exists (e.g. from self.candlestick_data_for_plotting)
            if 'timestamp' in klines_df_for_indicators.columns:
                 klines_df_for_indicators['timestamp'] = pd.to_datetime(klines_df_for_indicators['timestamp'])
                 klines_df_for_indicators = klines_df_for_indicators.set_index('timestamp')
            else: # If no 'timestamp' column, try to infer from a 't' column (epoch seconds)
                if 't' in klines_df_for_indicators.columns: # 't' would be epoch seconds from candlestick_data_for_plotting
                    klines_df_for_indicators.index = pd.to_datetime(klines_df_for_indicators['t'], unit='s')
                else: # Cannot determine timestamps for indicators
                    return

        x_timestamps = klines_df_for_indicators.index.astype(np.int64) // 10**9

        # SMA
        if self.sma_checkbox.isChecked() and len(klines_df_for_indicators) >= self.sma_period_spinbox.value():
            period = self.sma_period_spinbox.value()
            sma_series = klines_df_for_indicators['close'].rolling(window=period, min_periods=period).mean()
            self.sma_plot_item.setData(x=x_timestamps, y=sma_series.values)
        # EMA
        if self.ema_checkbox.isChecked() and len(klines_df_for_indicators) >= self.ema_period_spinbox.value():
            period = self.ema_period_spinbox.value()
            ema_series = klines_df_for_indicators['close'].ewm(span=period, adjust=False, min_periods=period).mean()
            self.ema_plot_item.setData(x=x_timestamps, y=ema_series.values)
        # RSI
        if self.rsi_checkbox.isChecked() and len(klines_df_for_indicators) >= self.rsi_period_spinbox.value() + 1: # Need one more for diff
            period = self.rsi_period_spinbox.value()
            delta = klines_df_for_indicators['close'].diff()
            gain = (delta.where(delta > 0, 0.0)).ewm(com=max(1, period - 1), adjust=False, min_periods=max(1,period-1)).mean()
            loss = (-delta.where(delta < 0, 0.0)).ewm(com=max(1, period - 1), adjust=False, min_periods=max(1,period-1)).mean()
            rs = gain / (loss + 1e-9)
            rsi_series = 100 - (100 / (1 + rs))
            self.rsi_plot_item.setData(x=x_timestamps, y=rsi_series.values)
            # Configurable OB/OS levels for RSI (example, assuming spinboxes exist or using fixed values)
            # self.rsi_ob_line.setValue(getattr(self, 'rsi_ob_level_spinbox', QSpinBox(value=70)).value())
            # self.rsi_os_line.setValue(getattr(self, 'rsi_os_level_spinbox', QSpinBox(value=30)).value())
            self.rsi_ob_line.setValue(70)
            self.rsi_os_line.setValue(30)


    @Slot(pd.DataFrame, str)
    def update_chart_data(self, klines_df: pd.DataFrame, timeframe_str: str):
        self.logger.debug(f"Updating chart with {len(klines_df)} klines for {timeframe_str}.")

        self.candlestick_data_for_plotting.clear() # Clear existing live data buffer

        # Clear previous plot items related to data
        if self.candlestick_item:
            self.price_plot.removeItem(self.candlestick_item)
            self.candlestick_item = None
        if self.trade_markers_plot:
            self.trade_markers_plot.clear() # Clear trade markers
        if self.position_line:
            self.price_plot.removeItem(self.position_line)
            self.position_line = None
        # if self.position_fill_item: # If implementing fill
        #     self.price_plot.removeItem(self.position_fill_item)
        #     self.position_fill_item = None

        if klines_df is None or klines_df.empty:
            # self.price_plot.clear() # This would also remove indicator lines if not careful
            self._plot_indicators(pd.DataFrame()) # Clear indicators
            self.chart_status_label.setText(f"No data for {self.current_chart_symbol_tf[0]} {self.current_chart_symbol_tf[1]}")
            return

        self.candlestick_data_for_plotting = self._prepare_candlestick_data(klines_df, timeframe_str)

        if self.candlestick_data_for_plotting:
            self.candlestick_item = CandlestickItem(self.candlestick_data_for_plotting)
            self.price_plot.addItem(self.candlestick_item)
        else:
            self.price_plot.clear() # Should not happen if klines_df was not empty

        self._plot_indicators(klines_df) # Plot indicators based on the full historical DataFrame

        self.price_plot.autoRange()
        self.rsi_plot_widget.autoRange()
        self.chart_status_label.setText(f"Displaying {self.current_chart_symbol_tf[0]} {self.current_chart_symbol_tf[1]} - Historical ({len(klines_df)})")


    @Slot(dict)
    def handle_live_kline_data(self, kline_data: dict):
        # kline_data is ui_kline_data from BotController (timestamps in ms)
        # Example: {"symbol": "BTCUSDT", "interval": "1m", "t": 1672515720000, "o": "0.0010", ... "x": false}

        if not self.current_chart_symbol_tf:
            # self.logger.debug("Live kline received but no chart symbol/tf selected.")
            return

        chart_symbol, chart_tf = self.current_chart_symbol_tf
        if kline_data['symbol'] != chart_symbol or kline_data['interval'] != chart_tf:
            # self.logger.debug(f"Live kline for {kline_data['symbol']}/{kline_data['interval']} ignored, chart is {chart_symbol}/{chart_tf}")
            return

        # self.logger.debug(f"ChartView received live kline: S:{kline_data['symbol']} I:{kline_data['interval']} O:{kline_data['o']} C:{kline_data['c']} Closed:{kline_data['x']}")

        kline_open_time_sec = kline_data['t'] / 1000.0
        # is_closed = kline_data['x'] # We can use this if we want to treat closed/unclosed differently

        new_candle_plot_data = {
            't': kline_open_time_sec,
            'o': float(kline_data['o']), 'h': float(kline_data['h']),
            'l': float(kline_data['l']), 'c': float(kline_data['c']),
            'w': self._get_candle_width_seconds(kline_data['interval'])
        }

        if not self.candlestick_data_for_plotting:
            self.candlestick_data_for_plotting.append(new_candle_plot_data)
        else:
            last_plotted_candle_t = self.candlestick_data_for_plotting[-1]['t']
            if kline_open_time_sec == last_plotted_candle_t: # Update current (last) candle
                self.candlestick_data_for_plotting[-1] = new_candle_plot_data
            elif kline_open_time_sec > last_plotted_candle_t: # New candle
                self.candlestick_data_for_plotting.append(new_candle_plot_data)
                # Optional: Limit buffer size
                max_live_candles = 300 # Keep roughly same as historical load
                if len(self.candlestick_data_for_plotting) > max_live_candles:
                    self.candlestick_data_for_plotting = self.candlestick_data_for_plotting[-max_live_candles:]
            else: # Old kline, should not happen with live stream under normal circumstances
                self.logger.warning(f"Received old kline in live update: OpenTime {kline_open_time_sec} vs LastPlotted {last_plotted_candle_t}")
                return # Don't update chart with out-of-order old data

        if self.candlestick_item:
            self.candlestick_item.data = self.candlestick_data_for_plotting # Update data in item
            self.candlestick_item.generatePicture() # Regenerate picture
            # self.candlestick_item.update() # Trigger repaint via paint method
            self.candlestick_item.informViewBoundsChanged() # More robust way to signal update
            self.price_plot.update() # Try updating the plot view directly

        # Update indicators using a DataFrame derived from the current candlestick_data_for_plotting
        if self.candlestick_data_for_plotting:
            # Construct DataFrame for indicators
            # Column names must match what _plot_indicators expects (e.g., 'open', 'high', 'low', 'close', and a DatetimeIndex)
            live_df_for_indicators = pd.DataFrame([{
                'timestamp': pd.to_datetime(cd['t'], unit='s'), # Convert epoch seconds back to Datetime
                'open': cd['o'], 'high': cd['h'], 'low': cd['l'], 'close': cd['c']
            } for cd in self.candlestick_data_for_plotting])

            if not live_df_for_indicators.empty:
                live_df_for_indicators = live_df_for_indicators.set_index('timestamp')
                # Plot indicators using the tail of the data to keep it responsive
                self._plot_indicators(live_df_for_indicators.tail(200))

        # self.price_plot.autoRange() # Auto-range can be jumpy on live updates
        # self.rsi_plot_widget.autoRange() # Consider conditional auto-range or manual range updates

    @Slot(dict)
    def handle_new_trade_marker(self, trade_info: dict):
        if not self.current_chart_symbol_tf or \
           trade_info['symbol'] != self.current_chart_symbol_tf[0] or \
           not self.trade_markers_plot:
            return

        timestamp = trade_info['timestamp'] # Epoch seconds
        price = trade_info['price']
        side = trade_info['side'] # 'BUY' or 'SELL'

        # symbol_char = 't1' if side == 'BUY' else 't2' # Triangle up/down
        # pg.graphicsItems.ScatterPlotItem.Symbols uses different keys
        symbol_char = 's' if side == 'BUY' else 's' # Square for buy, 'd' for sell diamond
        color = pg.mkBrush('g') if side == 'BUY' else pg.mkBrush('r')
        border_pen = pg.mkPen('w', width=1)
        size = 12

        # self.logger.debug(f"Adding trade marker: TS {timestamp}, Px {price}, Side {side}")
        self.trade_markers_plot.addPoints([{'pos': (timestamp, price),
                                            'symbol': symbol_char,
                                            'brush': color,
                                            'pen': border_pen,
                                            'size': size,
                                            'data': trade_info}]) # Store original info if needed

    @Slot(dict)
    def handle_position_update_for_chart(self, pos_data: dict):
        if not self.current_chart_symbol_tf or \
           pos_data['symbol'] != self.current_chart_symbol_tf[0]:
            return

        # Clear previous position line and fill
        if self.position_line:
            self.price_plot.removeItem(self.position_line)
            self.position_line = None
        # if self.position_fill_item: # If implementing fill
        #     self.price_plot.removeItem(self.position_fill_item)
        #     self.position_fill_item = None

        if pos_data['side'] != 'FLAT' and pos_data['entry_price'] > 0:
            entry_price = pos_data['entry_price']
            pos_side_label = pos_data['side']
            self.logger.info(f"Displaying position line for {pos_data['symbol']} {pos_side_label} @ {entry_price}")

            self.position_line = pg.InfiniteLine(
                pos=entry_price,
                angle=0,
                movable=False,
                pen=pg.mkPen('y', style=Qt.PenStyle.DashLine, width=2), # Corrected Qt.DashLine
                label=f"{pos_side_label} Entry: {entry_price:.{self.price_plot.axes['left']['item'].tickFormatters[0][1] if self.price_plot.axes['left']['item'].tickFormatters else 2}f}" # Dynamic precision
            )
            self.price_plot.addItem(self.position_line)

            # Optional: P&L Fill (deferred for simplicity)
            # ...

if __name__ == '__main__':
    # ... (Standalone test code from previous step can be adapted)
    pass

```
