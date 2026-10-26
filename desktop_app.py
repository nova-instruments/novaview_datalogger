"""Interface desktop do novaview_datalogger_v1 (Qt Widgets + PyQtGraph)."""
from __future__ import annotations

import os
os.environ.setdefault('PYQTGRAPH_QT_LIB', 'PySide6')

from pathlib import Path
from datetime import datetime, timezone
import logging
import sys

import numpy as np
import pandas as pd
from PySide6.QtCore import (QAbstractTableModel, QDateTime, QModelIndex, QObject, QEvent,
                            QRunnable, QThreadPool, QTimer, Qt, Signal, Slot, QLocale)
from PySide6.QtGui import QAction, QColor, QIcon, QPalette, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox,
    QDateTimeEdit, QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QProgressBar, QPushButton, QScrollArea, QLayout, QSizePolicy,
    QStackedWidget, QTabWidget, QTableView, QVBoxLayout, QWidget)
import pyqtgraph as pg

import datalogger_core as core
from data_service import (Dataset, ALARM_FILTER_OPTIONS, alarm_history, filter_records,
                          load_dataset, parse_temperature_bound, detect_equipment_profile)


STYLE = '''
QWidget { font-family: 'Segoe UI'; font-size: 13px; color: #18304c; }
QMainWindow, QStackedWidget, QTabWidget::pane { background: #f3f6fa; }
QFrame#header, QFrame#card, QFrame#panelControls { background: white; border: 1px solid #dce5ef; border-radius: 10px; }
QFrame#panelMetric { background: #f4f8fb; border: 1px solid #e3ebf2; border-radius: 8px; }
QWidget#periodFilters { background: transparent; border: none; }
QLabel#panelMetricValue { font-size: 22px; font-weight: 700; color: #0d9488; }
QScrollArea#panelControlsScroll { background: transparent; border: none; }
QLabel#title { font-size: 26px; font-weight: 700; color: #0b1e3a; }
QLabel#subtitle { color: #62748b; }
QLabel#value { font-size: 26px; font-weight: 700; color: #0d9488; }
QLabel#deviceSerial { font-size: 20px; font-weight: 600; color: #0b1e3a; padding: 4px 0; }
QPushButton { background: white; border: 1px solid #ccd8e5; border-radius: 6px; padding: 9px 16px; }
QPushButton:hover { background: #e9f4f6; border-color: #0d9488; }
QPushButton#primary { color: white; background: #0d9488; border: none; }
QPushButton:disabled { color: #99a6b6; background: #e9eef4; }
QLineEdit, QDateTimeEdit, QComboBox { background: white; border: 1px solid #ccd8e5; border-radius: 5px; padding: 7px; }
QDateTimeEdit { padding: 6px 30px 6px 10px; }
QDateTimeEdit QLineEdit { background: transparent; border: none; padding: 0; }
QDateTimeEdit::drop-down { subcontrol-origin: border; subcontrol-position: top right; width: 26px; border: none; border-left: 1px solid #ccd8e5; border-top-right-radius: 5px; border-bottom-right-radius: 5px; background: #eef3f8; }
QDateTimeEdit::down-arrow { image: url("__CALENDAR_ARROW__"); width: 10px; height: 6px; }
QTabBar::tab { padding: 12px 28px; background: #e8eef5; margin-right: 4px; }
QTabBar::tab:selected { color: #0d9488; background: white; font-weight: 700; }
QTableView { background: white; alternate-background-color: #f5f8fb; border: 1px solid #dce5ef; gridline-color: #e8eef5; selection-background-color: #d3efec; selection-color: #18304c; }
QHeaderView::section { background: #eaf0f7; border: none; padding: 8px; font-weight: 600; }
QProgressBar { border: none; background: #e8eef5; max-height: 5px; }
QProgressBar::chunk { background: #0d9488; }
QScrollArea, QWidget#series { background: white; border: none; }
QCheckBox { spacing: 7px; padding: 5px; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #94a3b8; border-radius: 3px; background: white; }
QCheckBox::indicator:checked { background: #0d9488; border: 2px solid #0b786f; }
'''.replace('__CALENDAR_ARROW__', (core.APP_BASE_DIR / 'img' / 'calendar-chevron.svg').as_posix())


def light_palette():
    palette = QPalette()
    for role, color in {
        QPalette.ColorRole.Window: '#f3f6fa',
        QPalette.ColorRole.WindowText: '#18304c',
        QPalette.ColorRole.Base: '#ffffff',
        QPalette.ColorRole.AlternateBase: '#f5f8fb',
        QPalette.ColorRole.Text: '#18304c',
        QPalette.ColorRole.Button: '#ffffff',
        QPalette.ColorRole.ButtonText: '#18304c',
        QPalette.ColorRole.Highlight: '#0d9488',
        QPalette.ColorRole.HighlightedText: '#ffffff',
        QPalette.ColorRole.ToolTipBase: '#ffffff',
        QPalette.ColorRole.ToolTipText: '#18304c',
    }.items():
        palette.setColor(role, QColor(color))
    return palette


class LocalDateAxis(pg.DateAxisItem):
    def __init__(self):
        super().__init__(utcOffset=0)

    def tickStrings(self, values, scale, spacing):
        pattern = ('yyyy' if spacing >= 31536000 else 'MM/yyyy' if spacing >= 2419200
                   else 'dd/MM' if spacing >= 86400 else 'HH:mm' if spacing >= 60 else 'HH:mm:ss')
        result = []
        for value in values:
            try:
                date = datetime.fromtimestamp(float(value), timezone.utc)
                result.append(QLocale('pt_BR').toString(QDateTime(date), pattern))
            except (ValueError, OverflowError, OSError):
                result.append('')
        return result


class DataFrameModel(QAbstractTableModel):
    """Qt solicita somente as células visíveis, sem materializar itens por linha."""
    def __init__(self, frame=None, parent=None, *, alignment=None):
        super().__init__(parent)
        self.frame = frame if frame is not None else pd.DataFrame()
        self.sort_column = None
        self.sort_order = Qt.SortOrder.AscendingOrder
        self.alignment = alignment

    def set_frame(self, frame):
        if self.sort_column in frame.columns:
            frame = frame.sort_values(self.sort_column, ascending=self.sort_order == Qt.SortOrder.AscendingOrder, kind='stable', na_position='last')
        self.beginResetModel()
        self.frame = frame.reset_index(drop=True)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.frame)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.frame.columns)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        value = self.frame.iat[index.row(), index.column()]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            if pd.isna(value):
                return ''
            if isinstance(value, (pd.Timestamp, datetime)):
                return core.format_datetime(value)
            if isinstance(value, (float, np.floating)):
                return core.format_metric(float(value))
            return str(value)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if self.alignment is not None:
                return self.alignment
            if isinstance(value, (int, float, np.number)):
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            return str(self.frame.columns[section]) if orientation == Qt.Orientation.Horizontal else str(section + 1)
        return None

    def sort(self, column, order=Qt.SortOrder.AscendingOrder):
        if 0 <= column < self.columnCount():
            self.sort_column = self.frame.columns[column]
            self.sort_order = order
            self.set_frame(self.frame)


class JobSignals(QObject):
    result = Signal(object)
    error = Signal(str)
    finished = Signal()


class Job(QRunnable):
    def __init__(self, function):
        super().__init__()
        self.function = function
        self.signals = JobSignals()

    @Slot()
    def run(self):
        try:
            self.signals.result.emit(self.function())
        except Exception as error:
            logging.exception('Falha em operação do NovaView')
            self.signals.error.emit(str(error))
        finally:
            self.signals.finished.emit()


def time_values(values):
    # Datas já convertidas para São Paulo no core: preserva o relógio exibido.
    return pd.DatetimeIndex(values).as_unit('ns').asi8 / 1e9


def prepare_chart(frame, columns, low_limit=core.TEMP_LOW_ALARM_LIMIT,
                  high_limit=core.TEMP_HIGH_ALARM_LIMIT):
    time_col = core.get_main_time_column(frame)
    if not time_col or not columns:
        return None
    ordered = frame.dropna(subset=[time_col]).sort_values(time_col)
    x = time_values(ordered[time_col])
    series = [(col, pd.to_numeric(ordered[col], errors='coerce').to_numpy(dtype=float)) for col in columns]
    reference = 'Tprincipal' if 'Tprincipal' in columns else columns[0]
    areas = core.build_temperature_trend_areas(ordered, time_col, reference)
    fills = []
    for area, group in areas.groupby('Area', sort=False):
        xs, ys = [], []
        for _, segment in group.groupby('Segmento', sort=False):
            xs.extend(time_values(segment['DataHora']))
            ys.extend(segment['Temperatura'])
            xs.append(np.nan)
            ys.append(np.nan)
        fills.append((area, np.asarray(xs), np.asarray(ys, dtype=float)))
    durations = core.compute_temperature_segment_durations(ordered, time_col, reference)
    records = filter_records(ordered, low_limit=low_limit, high_limit=high_limit).reset_index(drop=True)
    return x, series, fills, durations, records


class TemperatureChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.hint = QLabel('Importe os dados para visualizar o gráfico.')
        layout.addWidget(self.hint)
        self.main = pg.PlotWidget(axisItems={'bottom': LocalDateAxis()})
        self.main.setBackground('w')
        self.main.showGrid(x=True, y=True, alpha=0.15)
        self.main.setMenuEnabled(False)
        self.main.setMouseEnabled(x=True, y=True)
        self.main.getViewBox().setMouseMode(pg.ViewBox.PanMode)
        layout.addWidget(self.main, 1)
        self.main.setLabel('left', 'Valor')
        self.main.setLabel('bottom', 'Data e hora')
        self.main.addLegend(offset=(10, 10))
        self.main.scene().sigMouseMoved.connect(self._hover)
        self.main.scene().sigMouseClicked.connect(self._clicked)
        self.data = None
        self.curves = []
        self.full_range = None
        self.crosshair = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen('#94a3b8', style=Qt.PenStyle.DashLine))
        self.selected_index = None
        self.selection_line = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen('#f59e0b', width=2))
        self.selection_marker = pg.ScatterPlotItem(size=12, pen=pg.mkPen('#d97706', width=2), brush=(255, 255, 255, 180))
        self.details = QFrame()
        self.details.setObjectName('card')
        detail_layout = QVBoxLayout(self.details)
        detail_layout.setContentsMargins(10, 8, 10, 8)
        heading = QHBoxLayout()
        self.details_title = QLabel('Registro selecionado')
        heading.addWidget(self.details_title, 1)
        close = QPushButton('Fechar detalhes')
        close.clicked.connect(self.clear_selection)
        heading.addWidget(close)
        detail_layout.addLayout(heading)
        self.details_table, self.details_model = make_table(centered=True)
        self.details_table.setSortingEnabled(False)
        self.details_table.setFixedHeight(80)
        detail_layout.addWidget(self.details_table)
        layout.addWidget(self.details)
        self.details.hide()

    def set_chart(self, data):
        self.clear_selection()
        self.main.clear()
        self.main.setToolTip('')
        self.data = data
        self.curves = []
        if data is None or not len(data[0]):
            self.full_range = None
            self.hint.setText('Selecione medições numéricas e um período com datas válidas.')
            return
        x, series, fills, durations, _ = data
        palette = ['#0d9488', '#6366f1', '#f59e0b', '#ec4899', '#14b8a6', '#8b5cf6']
        finite = [y[np.isfinite(y)] for _, y in series]
        minimum = min((float(y.min()) for y in finite if len(y)), default=0)
        maximum = max((float(y.max()) for y in finite if len(y)), default=1)
        baseline = minimum - max((maximum - minimum) * .08, .1)
        for area, ax, ay in fills:
            color = (239, 68, 68, 40) if area == 'Área quente' else (59, 130, 246, 40)
            self.main.plot(ax, ay, pen=None, fillLevel=baseline, brush=color, connect='finite')
        for i, (name, y) in enumerate(series):
            color = palette[i % len(palette)]
            curve = self.main.plot(x, y, pen=pg.mkPen(color, width=2), name=name,
                symbol='o' if len(x) == 1 else None, symbolBrush=color, connect='finite', autoDownsample=True)
            # Ativa o recorte após a curva estar vinculada ao ViewBox.
            curve.setClipToView(True)
            self.curves.append(curve)
        self.main.addItem(self.crosshair, ignoreBounds=True)
        self.main.addItem(self.selection_line, ignoreBounds=True)
        self.main.addItem(self.selection_marker, ignoreBounds=True)
        self.full_range = (float(x[0]), float(x[-1]) if x[-1] > x[0] else float(x[0] + 1))
        self.reset()
        totals = durations.groupby('Area')['DuracaoSegundos'].sum() if not durations.empty else {}
        self.hint.setText(f'{len(x):,} registros · Subida: {core.format_duration(totals.get("Área quente", 0))} · Descida: {core.format_duration(totals.get("Área fria", 0))} · Roda: zoom · Arraste: mover · Clique: dados do ponto'.replace(',', '.'))
        self.hint.setWordWrap(True)

    def reset(self):
        if self.full_range:
            self.main.enableAutoRange(axis='y', enable=True)
            self.main.setXRange(*self.full_range, padding=.01)

    def _hover(self, position):
        if self.data is None or not self.main.sceneBoundingRect().contains(position):
            return
        x, series = self.data[:2]
        if not len(x):
            return
        point = self.main.plotItem.vb.mapSceneToView(position)
        idx = int(np.searchsorted(x, point.x()))
        idx = min(max(idx, 0), len(x) - 1)
        if idx and abs(x[idx - 1] - point.x()) < abs(x[idx] - point.x()):
            idx -= 1
        self.crosshair.setPos(x[idx])
        when = datetime.fromtimestamp(float(x[idx]), timezone.utc).strftime('%d/%m/%Y %H:%M:%S')
        self.main.setToolTip(when + '\n' + '\n'.join(f'{name}: {core.format_metric(float(y[idx]))}' for name, y in series))

    def _clicked(self, event):
        if event.button() != Qt.MouseButton.LeftButton or event.isAccepted() or self.data is None:
            return
        view = self.main.getViewBox()
        if not view.sceneBoundingRect().contains(event.scenePos()):
            return
        x, series, _, _, records = self.data
        if not len(x):
            return
        point = view.mapSceneToView(event.scenePos())
        bounds = view.viewRange()
        x_unit = max((bounds[0][1] - bounds[0][0]) / max(view.width(), 1), 1e-12)
        y_unit = max((bounds[1][1] - bounds[1][0]) / max(view.height(), 1), 1e-12)
        x_distance = ((x - point.x()) / x_unit) ** 2
        best_index, best_distance = None, float('inf')
        # A distância em pixels considera a série e distingue registros no mesmo horário.
        for _, values in series:
            distances = x_distance + ((values - point.y()) / y_unit) ** 2
            distances = np.where(np.isfinite(distances), distances, np.inf)
            index = int(np.argmin(distances))
            if distances[index] < best_distance:
                best_index, best_distance = index, float(distances[index])
        if best_index is None:
            return
        self.selected_index = best_index
        self.selection_line.setPos(float(x[best_index]))
        self.selection_line.show()
        ys = [float(values[best_index]) for _, values in series if np.isfinite(values[best_index])]
        self.selection_marker.setData([float(x[best_index])] * len(ys), ys)
        self.selection_marker.show()
        when = datetime.fromtimestamp(float(x[best_index]), timezone.utc).strftime('%d/%m/%Y %H:%M:%S')
        self.details_title.setText(f'Registro selecionado · {when}')
        self.details_model.set_frame(records.iloc[[best_index]])
        self.details.show()

    def clear_selection(self, *_):
        self.selected_index = None
        self.selection_line.hide()
        self.selection_marker.hide()
        self.details.hide()
        self.details_model.set_frame(pd.DataFrame())


def make_table(*, centered=False):
    table = QTableView()
    model = DataFrameModel(parent=table, alignment=Qt.AlignmentFlag.AlignCenter if centered else None)
    table.setModel(model)
    table.setAlternatingRowColors(True)
    table.setSortingEnabled(True)
    table.sortByColumn(-1, Qt.SortOrder.AscendingOrder)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    table.horizontalHeader().setDefaultSectionSize(145)
    table.horizontalHeader().setStretchLastSection(True)
    if centered:
        table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
    return table, model


def metric_row(titles, *, compact=False):
    row = QHBoxLayout()
    values = []
    for title in titles:
        card = QFrame()
        card.setObjectName('panelMetric' if compact else 'card')
        layout = QVBoxLayout(card)
        if compact:
            layout.setContentsMargins(12, 8, 12, 8)
        else:
            layout.setContentsMargins(18, 12, 18, 12)
        layout.addWidget(QLabel(title))
        value = QLabel('—')
        value.setObjectName('panelMetricValue' if compact else 'value')
        layout.addWidget(value)
        values.append(value)
        row.addWidget(card)
    return row, values


class PanelControlsArea(QScrollArea):
    def __init__(self, parent):
        super().__init__(parent)
        self._fit_queued = False
        parent.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Resize, QEvent.Type.LayoutRequest, QEvent.Type.Show):
            self.queue_fit()
        return super().eventFilter(watched, event)

    def queue_fit(self):
        if not self._fit_queued:
            self._fit_queued = True
            QTimer.singleShot(0, self.fit_height)

    def fit_height(self):
        self._fit_queued = False
        if not self.isVisible() or not self.widget():
            return
        page = self.parentWidget()
        layout = page.layout()
        if layout.count() < 4:
            return
        chart = layout.itemAt(layout.count() - 1).widget()
        margins = layout.contentsMargins()
        used = margins.top() + margins.bottom() + layout.spacing() * (layout.count() - 1)
        for i in range(layout.count() - 1):
            item = layout.itemAt(i)
            if item.widget() is not self:
                used += item.geometry().height()
        chart_space = max(140, chart.minimumSizeHint().height())
        available = max(80, page.height() - used - chart_space)
        height = min(self.widget().minimumSizeHint().height(), available)
        if self.minimumHeight() != height or self.maximumHeight() != height:
            self.setFixedHeight(height)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('novaview_datalogger_v1')
        self.resize(1280, 880)
        self.setMinimumSize(960, 700)
        icon = core.APP_BASE_DIR / 'img' / 'icon.ico'
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))
        self.dataset = None
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.jobs = set()
        self.range_frame = pd.DataFrame()
        self.export_frame = pd.DataFrame()
        self.period_bounds = (None, None)
        self.setAcceptDrops(True)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(22, 18, 22, 12)
        layout.setSpacing(14)
        header = QFrame()
        header.setObjectName('header')
        top = QHBoxLayout(header)
        logo = QLabel()
        pixmap = QPixmap(str(core.LOGO_PATH))
        if not pixmap.isNull():
            logo.setPixmap(pixmap.scaled(308, 123, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            top.addWidget(logo)
        self.source_label = QLabel('Análise de temperatura e histórico de alarmes')
        self.source_label.setObjectName('subtitle')
        self.source_label.setTextFormat(Qt.TextFormat.PlainText)
        self.source_label.setWordWrap(True)
        top.addWidget(self.source_label, 1)
        self.open_button = QPushButton('Abrir arquivo')
        self.open_button.setObjectName('primary')
        self.folder_button = QPushButton('Abrir pasta IHM')
        self.open_button.clicked.connect(self.open_file)
        self.folder_button.clicked.connect(self.open_folder)
        top.addWidget(self.open_button)
        top.addWidget(self.folder_button)
        layout.addWidget(header)
        equipment_row = QHBoxLayout()
        equipment_row.addWidget(QLabel('Tipo de equipamento'))
        self.equipment_profile = QComboBox()
        self.equipment_profile.addItem('Automático', 'auto')
        self.equipment_profile.addItem('Câmara Fria', 'cold_chamber')
        self.equipment_profile.addItem('Freezer −30 °C', 'freezer')
        self.equipment_profile.setToolTip('Automático estima o tipo pela temperatura de todo o arquivo. Se necessário, selecione Câmara Fria ou Freezer manualmente.')
        self.equipment_profile.currentIndexChanged.connect(self._equipment_changed)
        equipment_row.addWidget(self.equipment_profile)
        self.alarm_limits_label = QLabel('')
        self.alarm_limits_label.setWordWrap(True)
        equipment_row.addWidget(self.alarm_limits_label)
        equipment_row.addStretch()
        layout.addLayout(equipment_row)
        self.stack = QStackedWidget()
        welcome = QWidget()
        welcome_layout = QVBoxLayout(welcome)
        welcome_layout.addStretch()
        headline = QLabel('Seus registros, em uma visão completa.')
        headline.setObjectName('title')
        headline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        welcome_layout.addWidget(headline)
        description = QLabel('Abra um arquivo .db ou .txt, ou selecione a pasta DataLogFile da IHM.\nVocê também pode arrastar um arquivo ou uma pasta para esta janela.')
        description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        welcome_layout.addWidget(description)
        welcome_layout.addStretch()
        self.stack.addWidget(welcome)
        self.tabs = QTabWidget()
        self.stack.addWidget(self.tabs)
        self._build_panel()
        self._build_data()
        self._build_alarms()
        self.tabs.currentChanged.connect(self.refresh)
        layout.addWidget(self.stack, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.statusBar().showMessage('Pronto para importar dados.')
        open_action = QAction('Abrir arquivo…', self)
        open_action.setShortcut('Ctrl+O')
        open_action.triggered.connect(self.open_file)
        self.addAction(open_action)
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(350)
        self.search_timer.timeout.connect(self.refresh)

    def _build_panel(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.panel_serial = self._serial_label()
        panel_header = QHBoxLayout()
        panel_header.addWidget(self.panel_serial, 1)
        self.panel_controls_toggle = QPushButton('Mostrar filtros e indicadores')
        self.panel_controls_toggle.setCheckable(True)
        self.panel_controls_toggle.toggled.connect(self._toggle_panel_controls)
        panel_header.addWidget(self.panel_controls_toggle)
        self.reset_plot = QPushButton('Restaurar gráfico')
        self.reset_plot.clicked.connect(lambda: self.chart.reset())
        panel_header.addWidget(self.reset_plot)
        layout.addLayout(panel_header)
        available_period = QHBoxLayout()
        available_period.setSpacing(24)
        self.datalogger_start = QLabel('Início do datalogger: —')
        self.datalogger_end = QLabel('Fim do datalogger: —')
        for label in (self.datalogger_start, self.datalogger_end):
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            label.setWordWrap(True)
            available_period.addWidget(label, 0, Qt.AlignmentFlag.AlignLeft)
        available_period.addStretch()
        layout.addLayout(available_period)
        self.panel_controls = QFrame()
        self.panel_controls.setObjectName('panelControls')
        controls_layout = QVBoxLayout(self.panel_controls)
        controls_layout.setContentsMargins(14, 12, 14, 10)
        controls_layout.setSpacing(12)
        controls_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
        filter_card = QWidget()
        filter_card.setObjectName('periodFilters')
        filter_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        filters = QHBoxLayout(filter_card)
        filters.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        filters.setContentsMargins(0, 0, 0, 0)
        filters.setSpacing(14)
        self.start = QDateTimeEdit()
        self.end = QDateTimeEdit()
        for caption, editor in [('De (data e hora)', self.start), ('Até (data e hora)', self.end)]:
            field = QVBoxLayout()
            field.setSpacing(6)
            editor.setDisplayFormat('dd/MM/yyyy HH:mm:ss')
            editor.setCalendarPopup(True)
            editor.setFixedWidth(232)
            editor.setMinimumHeight(40)
            editor.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            editor.setAlignment(Qt.AlignmentFlag.AlignCenter)
            field.addWidget(QLabel(caption))
            field.addWidget(editor)
            filters.addLayout(field)
        self.apply_period = QPushButton('Confirmar período')
        self.apply_period.setObjectName('primary')
        self.apply_period.setFixedHeight(40)
        self.apply_period.clicked.connect(self.refresh)
        filters.addWidget(self.apply_period, 0, Qt.AlignmentFlag.AlignBottom)
        filters.addStretch()
        controls_layout.addWidget(filter_card)
        metrics, self.panel_values = metric_row(['Temperatura média', 'Setpoint médio', 'Maior temperatura', 'Menor temperatura'], compact=True)
        metrics.setSpacing(10)
        controls_layout.addLayout(metrics)
        self.series_container = QWidget()
        self.series_container.setObjectName('series')
        self.series_layout = QHBoxLayout(self.series_container)
        self.series_layout.setContentsMargins(0, 0, 0, 0)
        self.series_boxes = []
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.series_container)
        scroll.setFixedHeight(48)
        controls_layout.addWidget(scroll)
        self.panel_controls_scroll = PanelControlsArea(page)
        self.panel_controls_scroll.setObjectName('panelControlsScroll')
        self.panel_controls_scroll.setWidgetResizable(True)
        self.panel_controls_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.panel_controls_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.panel_controls_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.panel_controls_scroll.setWidget(self.panel_controls)
        layout.addWidget(self.panel_controls_scroll)
        self.panel_controls_scroll.hide()
        self.panel_controls.hide()
        self.chart = TemperatureChart()
        layout.addWidget(self.chart, 1)
        self.tabs.addTab(page, 'Painel')

    def _toggle_panel_controls(self, visible):
        self.panel_controls.setVisible(visible)
        if visible:
            self.panel_controls.ensurePolished()
            self.panel_controls.layout().activate()
        self.panel_controls_scroll.setVisible(visible)
        self.panel_controls_scroll.queue_fit()
        self.panel_controls_toggle.setText('Ocultar filtros e indicadores' if visible else 'Mostrar filtros e indicadores')

    def _build_data(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.data_serial = self._serial_label()
        layout.addWidget(self.data_serial)
        actions = QHBoxLayout()
        actions.addWidget(QLabel('Período dos dados'))
        self.data_range = QComboBox()
        self.data_range.addItems(list(core.DATA_RANGE_OPTIONS))
        self.data_range.currentTextChanged.connect(self.refresh)
        actions.addWidget(self.data_range)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Buscar palavra, número ou data nos dados…')
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda: self.search_timer.start())
        actions.addWidget(self.search, 1)
        self.excel_button = QPushButton('Exportar Excel')
        self.pdf_button = QPushButton('Gerar PDF')
        self.excel_button.clicked.connect(lambda: self.export('xlsx'))
        self.pdf_button.clicked.connect(lambda: self.export('pdf'))
        actions.addWidget(self.excel_button)
        actions.addWidget(self.pdf_button)
        layout.addLayout(actions)
        filter_card = QFrame()
        filter_card.setObjectName('card')
        filters = QHBoxLayout(filter_card)
        filters.setContentsMargins(12, 10, 12, 10)
        self.alarm_filter = QComboBox()
        for label, key in ALARM_FILTER_OPTIONS.items():
            self.alarm_filter.addItem(label, key)
        self.alarm_filter.setToolTip('Alta e baixa temperatura aparecem mesmo com Al=0. O valor de alarme registra a confirmação do controlador. Os filtros térmicos incluem condições simultâneas à porta.')
        self.alarm_filter.currentIndexChanged.connect(self.refresh)
        self.temp_min = QLineEdit()
        self.temp_max = QLineEdit()
        for caption, widget in [('Tipo de alarme', self.alarm_filter),
                                ('Temperatura mín. (°C)', self.temp_min),
                                ('Temperatura máx. (°C)', self.temp_max)]:
            field = QVBoxLayout()
            field.addWidget(QLabel(caption))
            field.addWidget(widget)
            filters.addLayout(field)
        for editor in (self.temp_min, self.temp_max):
            editor.setPlaceholderText('Sem limite')
            editor.setClearButtonEnabled(True)
            editor.setMaximumWidth(155)
            editor.setToolTip('Temperatura principal. Aceita vírgula ou ponto; inclui o valor informado no limite.')
            editor.returnPressed.connect(self.refresh)
        self.apply_data_filters = QPushButton('Aplicar filtros')
        self.apply_data_filters.setObjectName('primary')
        self.apply_data_filters.clicked.connect(self.refresh)
        self.clear_data_filters = QPushButton('Limpar filtros')
        self.clear_data_filters.clicked.connect(self._clear_data_filters)
        filters.addStretch()
        for button in (self.apply_data_filters, self.clear_data_filters):
            filters.addWidget(button, 0, Qt.AlignmentFlag.AlignBottom)
        layout.addWidget(filter_card)
        self.data_summary = QLabel()
        layout.addWidget(self.data_summary)
        note = QLabel('Excel: dados dos filtros e ordenação atuais. PDF: todos os registros do período selecionado.')
        note.setObjectName('subtitle')
        layout.addWidget(note)
        self.data_table, self.data_model = make_table(centered=True)
        layout.addWidget(self.data_table, 1)
        self.tabs.addTab(page, 'Dados')

    def _clear_data_filters(self, *_):
        for widget in (self.search, self.alarm_filter, self.temp_min, self.temp_max):
            widget.blockSignals(True)
            if isinstance(widget, QComboBox):
                widget.setCurrentIndex(0)
            else:
                widget.clear()
            widget.blockSignals(False)
        self.search_timer.stop()
        self.refresh()

    @staticmethod
    def _serial_label():
        label = QLabel('Número de série: não informado')
        label.setObjectName('deviceSerial')
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setWordWrap(True)
        return label

    def _build_alarms(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        metrics, self.alarm_values = metric_row(['Registros com alarme', 'Alta temperatura', 'Baixa temperatura', 'Porta aberta'])
        layout.addLayout(metrics)
        self.latest_alarm = QLabel('Nenhum alarme carregado.')
        self.latest_alarm.setTextFormat(Qt.TextFormat.PlainText)
        self.latest_alarm.setWordWrap(True)
        layout.addWidget(self.latest_alarm)
        self.alarm_table, self.alarm_model = make_table(centered=True)
        layout.addWidget(self.alarm_table, 1)
        layout.addWidget(QLabel('Alta e baixa temperatura independem de Al. A coluna alarme mantém a confirmação do controlador; Tipo indica a condição observada.'))
        self.tabs.addTab(page, 'Alarmes')

    def _set_busy(self, busy):
        self.progress.setVisible(busy)
        for widget in (self.open_button, self.folder_button, self.tabs, self.equipment_profile):
            widget.setEnabled(not busy)

    def run_job(self, function, callback, message):
        if self.jobs:
            return
        job = Job(function)
        self.jobs.add(job)
        self._set_busy(True)
        self.statusBar().showMessage(message)
        job.signals.result.connect(callback)
        job.signals.error.connect(self.show_error)
        job.signals.finished.connect(self._job_finished)
        self.pool.start(job)

    @Slot()
    def _job_finished(self):
        self.jobs.clear()
        self._set_busy(False)

    def show_error(self, message):
        self.statusBar().showMessage('Não foi possível concluir a operação.')
        QMessageBox.warning(self, 'novaview_datalogger_v1', message)

    def open_file(self):
        if self.jobs:
            return
        path, _ = QFileDialog.getOpenFileName(self, 'Abrir dados do datalogger', '', 'Dados (*.db *.sqlite *.sqlite3 *.txt);;Todos os arquivos (*)')
        if path:
            self.load_path(path)

    def open_folder(self):
        if self.jobs:
            return
        path = QFileDialog.getExistingDirectory(self, 'Selecione a pasta da IHM ou DataLogFile')
        if path:
            self.load_path(path, True)

    def load_path(self, path, folder=False):
        self.search_timer.stop()
        self.run_job(lambda: load_dataset(path, folder), self._loaded, 'Lendo e normalizando os dados…')

    def _loaded(self, dataset):
        dataset = dataset.with_equipment_profile(self.equipment_profile.currentData())
        self.dataset = dataset
        self._show_alarm_limits()
        for label in (self.panel_serial, self.data_serial):
            label.setText(f'Número de série: {dataset.serial_number}')
        frame = dataset.frame
        time_col = core.get_main_time_column(frame)
        self.source_label.setText(f'{dataset.source_name} · {dataset.source_label} · {len(frame):,} registros'.replace(',', '.'))
        if time_col:
            low, high = frame[time_col].min(), frame[time_col].max()
            self.datalogger_start.setText(f'Início do datalogger: {core.format_datetime(low)}')
            self.datalogger_end.setText(f'Fim do datalogger: {core.format_datetime(high)}')
            # Os seletores exibem segundos; o filtro inclui as frações do segundo final.
            minimum = QDateTime(low.floor('s').to_pydatetime())
            maximum = QDateTime(high.floor('s').to_pydatetime())
            for editor in (self.start, self.end):
                editor.setDateTimeRange(minimum, maximum)
            self.end.setDateTime(maximum)
            default_start = max(high - pd.Timedelta(hours=24), low)
            self.start.setDateTime(QDateTime(default_start.floor('s').to_pydatetime()))
        else:
            self.datalogger_start.setText('Início do datalogger: não informado')
            self.datalogger_end.setText('Fim do datalogger: não informado')
        self.start.setEnabled(bool(time_col))
        self.end.setEnabled(bool(time_col))
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.alarm_filter.blockSignals(True)
        self.alarm_filter.setCurrentIndex(0)
        self.alarm_filter.blockSignals(False)
        self.temp_min.clear()
        self.temp_max.clear()
        self.data_range.blockSignals(True)
        self.data_range.setCurrentIndex(0)
        self.data_range.blockSignals(False)
        while self.series_layout.count():
            item = self.series_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.series_boxes = []
        columns = core.get_preferred_plot_columns(frame, dataset.is_txt)
        defaults = [c for c in ('Tprincipal', 'Setpoint') if c in columns]
        for name in columns:
            box = QCheckBox(name)
            box.setChecked(name in defaults)
            box.toggled.connect(self.refresh)
            self.series_layout.addWidget(box)
            self.series_boxes.append(box)
        self.series_layout.addStretch()
        self.stack.setCurrentIndex(1)
        self.tabs.blockSignals(True)
        self.tabs.setCurrentIndex(0)
        self.tabs.blockSignals(False)
        self.data_model.set_frame(pd.DataFrame())
        self.alarm_model.set_frame(pd.DataFrame())
        if dataset.notices:
            QMessageBox.warning(self, 'Importação com avisos', '\n'.join(dataset.notices))
        # O sinal finished libera a operação antes do próximo processamento.
        QTimer.singleShot(0, self.refresh)

    def _show_alarm_limits(self):
        if self.dataset:
            name = 'Freezer −30 °C' if self.dataset.equipment_profile == 'freezer' else 'Câmara Fria'
            automatic = self.equipment_profile.currentData() == 'auto'
            if automatic and detect_equipment_profile(self.dataset.frame) is None:
                self.alarm_limits_label.setText('Sem temperatura válida para identificar o equipamento. Selecione o tipo manualmente.')
                return
            prefix = f'Identificado: {name} · ' if automatic else ''
            self.alarm_limits_label.setText(f'{prefix}Alertas: abaixo de {self.dataset.low_limit:g} °C ou acima de {self.dataset.high_limit:g} °C')
        elif self.equipment_profile.currentData() == 'freezer':
            self.alarm_limits_label.setText('Alertas: abaixo de −45 °C ou acima de −15 °C')
        else:
            self.alarm_limits_label.setText('Escolha um arquivo para consultar os limites de alarme.')

    def _equipment_changed(self, *_):
        if self.dataset:
            self.dataset = self.dataset.with_equipment_profile(self.equipment_profile.currentData())
            # As tabelas de outras abas serão refeitas quando forem abertas.
            self.data_model.set_frame(pd.DataFrame())
            self.alarm_model.set_frame(pd.DataFrame())
        self._show_alarm_limits()
        self.refresh()

    def refresh(self, *_):
        if not self.dataset or self.jobs:
            return
        self.search_timer.stop()
        dataset = self.dataset
        view = self.tabs.currentIndex()
        start = self.start.dateTime().toPython()
        end = self.end.dateTime().toPython()
        if view == 0 and start > end:
            self.show_error('A data/hora inicial precisa ser menor que a data/hora final.')
            return
        columns = [box.text() for box in self.series_boxes if box.isChecked()]
        range_label, text = self.data_range.currentText(), self.search.text().strip()
        alarm_type = self.alarm_filter.currentData()
        minimum = maximum = None
        if view == 1:
            try:
                minimum = parse_temperature_bound(self.temp_min.text())
                maximum = parse_temperature_bound(self.temp_max.text())
                if minimum is not None and maximum is not None and minimum > maximum:
                    raise ValueError('A temperatura mínima precisa ser menor ou igual à máxima.')
                if (minimum is not None or maximum is not None) and 'Tprincipal' not in dataset.frame:
                    raise ValueError('Esta origem não possui a coluna de temperatura principal para aplicar a faixa.')
            except ValueError as error:
                self.show_error(str(error))
                return

        def prepare():
            frame = dataset.frame
            if view == 0:
                filtered = core.filter_by_period(frame, start.date(), start.time(), end.date(), end.time())
                temperature = pd.to_numeric(filtered.get('Tprincipal', pd.Series(dtype=float)), errors='coerce')
                setpoint = pd.to_numeric(filtered.get('Setpoint', pd.Series(dtype=float)), errors='coerce')
                metrics = [temperature.mean(), setpoint.mean(), temperature.max(), temperature.min()]
                return view, (metrics, prepare_chart(filtered, columns, dataset.low_limit, dataset.high_limit))
            if view == 1:
                ranged = core.filter_data_by_range(frame, range_label)
                display = filter_records(ranged, text, alarm_type, minimum, maximum, dataset.low_limit, dataset.high_limit)
                return view, (ranged, display, core.get_data_range_bounds(frame, range_label))
            return view, alarm_history(frame, dataset.low_limit, dataset.high_limit)

        self.run_job(prepare, self._refreshed, 'Atualizando visualização…')

    def _refreshed(self, result):
        view, payload = result
        if view == 0:
            metrics, chart = payload
            for label, value in zip(self.panel_values, metrics):
                label.setText(core.format_metric(value))
            self.chart.set_chart(chart)
        elif view == 1:
            self.range_frame, self.export_frame, self.period_bounds = payload
            self.data_model.set_frame(self.export_frame)
            start, end = self.period_bounds
            self.data_summary.setText(f'{len(self.export_frame):,} de {len(self.range_frame):,} registros · Primeiro: {core.format_datetime(start)} · Último: {core.format_datetime(end)}'.replace(',', '.'))
            self.excel_button.setEnabled(not self.export_frame.empty)
            self.pdf_button.setEnabled(not self.range_frame.empty)
        else:
            frame, counts = payload
            self.alarm_model.set_frame(frame)
            for label, count in zip(self.alarm_values, counts):
                label.setText(str(count))
            if not frame.empty:
                time_col = next((c for c in ['Data e hora', 'Início', 'Fim'] if c in frame), None)
                row = frame.iloc[0]
                when = core.format_datetime(row[time_col]) if time_col else 'Sem data'
                self.latest_alarm.setText(f'Último alarme: {when} · {row["Tipo"]}')
            else:
                self.latest_alarm.setText('Nenhum registro com alarme ou condição de temperatura fora dos limites.')
        self.statusBar().showMessage('Visualização atualizada.')

    def export(self, kind):
        if not self.dataset or self.jobs:
            return
        dataset = self.dataset
        stem = core.extract_txt_device_name(dataset.source_label, Path(dataset.source_name).stem) if dataset.is_txt else Path(dataset.source_name).stem
        name = f'{stem}.xlsx' if kind == 'xlsx' else f'relatorio_{stem}.pdf'
        path, _ = QFileDialog.getSaveFileName(self, 'Salvar exportação', name, 'Excel (*.xlsx)' if kind == 'xlsx' else 'PDF (*.pdf)')
        if not path:
            return
        destination = Path(path)
        if not destination.suffix:
            destination = destination.with_suffix('.' + kind)
        if destination.exists() and str(destination) != path:
            if QMessageBox.question(self, 'Substituir arquivo?', f'O arquivo {destination.name} já existe. Substituir?') != QMessageBox.StandardButton.Yes:
                return
        frame = self.data_model.frame.copy() if kind == 'xlsx' else self.range_frame.copy()
        start, end = self.period_bounds

        def save():
            data = core.dataframe_to_excel_bytes(frame) if kind == 'xlsx' else core.build_report_pdf(frame, dataset.source_name, dataset.source_label, dataset.high_limit, dataset.low_limit, start, end)
            # Só substitui o destino depois da geração e gravação completas.
            from tempfile import NamedTemporaryFile
            temporary = None
            try:
                with NamedTemporaryFile(dir=destination.parent, suffix='.tmp', delete=False) as stream:
                    temporary = Path(stream.name)
                    stream.write(data)
                temporary.replace(destination)
            finally:
                if temporary and temporary.exists():
                    temporary.unlink()
            return destination

        self.run_job(save, self._exported, 'Gerando e salvando exportação…')

    def _exported(self, destination):
        self.statusBar().showMessage(f'Arquivo salvo: {destination}')
        QMessageBox.information(self, 'Exportação concluída', f'Arquivo salvo em:\n{destination}')

    def dragEnterEvent(self, event):
        if not self.jobs and event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if len(urls) == 1 and urls[0].isLocalFile():
                event.acceptProposedAction()

    def dropEvent(self, event):
        if not self.jobs:
            urls = event.mimeData().urls()
            if len(urls) == 1 and urls[0].isLocalFile():
                path = Path(urls[0].toLocalFile())
                self.load_path(str(path), path.is_dir())
                event.acceptProposedAction()

    def closeEvent(self, event):
        if self.jobs:
            self.statusBar().showMessage('Aguarde a operação terminar antes de fechar.')
            event.ignore()
        else:
            event.accept()


def main():
    QLocale.setDefault(QLocale('pt_BR'))
    application = QApplication.instance() or QApplication(sys.argv)
    application.setApplicationName('novaview_datalogger_v1')
    application.setOrganizationName('NovaIOT')
    application.setStyle('Fusion')
    application.setPalette(light_palette())
    application.setStyleSheet(STYLE)
    pg.setConfigOptions(antialias=True)
    window = MainWindow()
    window.showMaximized()
    if len(sys.argv) > 1 and Path(sys.argv[1]).exists():
        path = Path(sys.argv[1])
        QTimer.singleShot(0, lambda: window.load_path(str(path), path.is_dir()))
    return application.exec()
