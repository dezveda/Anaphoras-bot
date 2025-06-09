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
        self.logger.info(f"Loading chart: {symbol} {timeframe}...")
        async def fetch_and_update():
            try:
                df = await self.backend_controller.get_historical_klines_for_chart(symbol, timeframe, limit=200) # Fetch more for indicators
                self.update_chart_data(df if df is not None else pd.DataFrame(), timeframe)
            except Exception as e: self.logger.error(f"Error fetching/updating chart: {e}", exc_info=True); self.update_chart_data(pd.DataFrame(),timeframe)
        if self.backend_controller.loop and self.backend_controller.loop.is_running(): # type: ignore
            asyncio.create_task(fetch_and_update())
        else: asyncio.run(fetch_and_update())


    def load_initial_chart_data(self): self.handle_load_refresh_chart()

    @Slot(pd.DataFrame, str)
    def update_chart_data(self, klines_df: pd.DataFrame, timeframe_str: str):
        self.logger.debug(f"Updating chart with {len(klines_df)} klines for {timeframe_str}.")
        if self.candlestick_item: self.price_plot.removeItem(self.candlestick_item); self.candlestick_item = None
        self.sma_plot_item.clear(); self.ema_plot_item.clear(); self.rsi_plot_item.clear()

        if klines_df is None or klines_df.empty: self.price_plot.clear(); self.rsi_plot_widget.clear(); return # Clear plots if no data

        # Ensure 'close' column is float for indicator calculations
        klines_df['close'] = klines_df['close'].astype(float)
        # Timestamps for x-axis (epoch seconds)
        x_timestamps = klines_df.index.astype(np.int64) // 10**9 # From DatetimeIndex to epoch seconds

        chart_data = self._prepare_candlestick_data(klines_df, timeframe_str)
        if chart_data:
            self.candlestick_item = CandlestickItem(chart_data)
            self.price_plot.addItem(self.candlestick_item)
        else: self.price_plot.clear()

        # SMA
        if self.sma_checkbox.isChecked() and len(klines_df) >= self.sma_period_spinbox.value():
            period = self.sma_period_spinbox.value()
            sma_series = klines_df['close'].rolling(window=period, min_periods=period).mean()
            self.sma_plot_item.setData(x=x_timestamps, y=sma_series.values)
        # EMA
        if self.ema_checkbox.isChecked() and len(klines_df) >= self.ema_period_spinbox.value():
            period = self.ema_period_spinbox.value()
            ema_series = klines_df['close'].ewm(span=period, adjust=False, min_periods=period).mean()
            self.ema_plot_item.setData(x=x_timestamps, y=ema_series.values)
        # RSI
        if self.rsi_checkbox.isChecked() and len(klines_df) >= self.rsi_period_spinbox.value():
            period = self.rsi_period_spinbox.value()
            delta = klines_df['close'].diff()
            gain = (delta.where(delta > 0, 0.0)).ewm(com=max(1, period - 1), adjust=False, min_periods=max(1,period-1)).mean() # com must be >= 0
            loss = (-delta.where(delta < 0, 0.0)).ewm(com=max(1, period - 1), adjust=False, min_periods=max(1,period-1)).mean()
            rs = gain / (loss + 1e-9) # Avoid division by zero
            rsi_series = 100 - (100 / (1 + rs))
            self.rsi_plot_item.setData(x=x_timestamps, y=rsi_series.values)
            self.rsi_ob_line.setValue(self.rsi_period_spinbox.parent().findChild(QSpinBox, "rsi_ob_level_spinbox").value() if hasattr(self, 'rsi_ob_level_spinbox') else 70) # Example for configurable OB/OS
            self.rsi_os_line.setValue(self.rsi_period_spinbox.parent().findChild(QSpinBox, "rsi_os_level_spinbox").value() if hasattr(self, 'rsi_os_level_spinbox') else 30)


        self.price_plot.autoRange()
        self.rsi_plot_widget.autoRange()


if __name__ == '__main__':
    # ... (Standalone test code from previous step can be adapted)
    pass

```
