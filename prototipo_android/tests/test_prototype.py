import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')

import sys
import unittest
from pathlib import Path
from datetime import datetime, timedelta
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QObject, QUrl, QPoint, QPointF, Qt, QMetaObject, Q_ARG, qInstallMessageHandler
from PySide6.QtGui import QGuiApplication, QFontDatabase
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest

from datalogger import Record, parse_txt, reduce_points
from controller import Controller
from main import create_engine


class ReaderTests(unittest.TestCase):
    def parse(self, rows, header='R;Data Hora;TPrincipal;PA;Al'):
        return parse_txt(('NAME: NI280000\n' + header + '\n' + rows).encode('utf-8-sig'))

    def test_original_controller_flag_and_door_are_independent(self):
        data = self.parse('1;13/10/26 17:14:52;3.70;1;0\n2;13/10/26 17:15:05;3.70;0;0')
        self.assertEqual(data.name, 'NI280000')
        self.assertEqual(data.counts(), {'total': 0, 'high': 0, 'low': 0, 'door': 0})
        self.assertEqual(data.records[0].controller_alarm, 0)

    def test_freezer_limits_are_strict_and_independent_of_al(self):
        rows = '\n'.join(f'{i};13/10/26 17:{i:02}:00;{temp};0;0' for i, temp in enumerate([-46, -45, -30, -15, -14], 1))
        data = self.parse(rows)
        self.assertEqual(data.detected_profile, 'freezer')
        self.assertEqual(data.limits(), (-45, -15))
        self.assertEqual(data.counts(), {'total': 2, 'high': 1, 'low': 1, 'door': 0})
        self.assertEqual([r.controller_alarm for r in data.records], [0]*5)
        self.assertEqual(data.limits('cold_chamber'), (2, 8))

    def test_missing_temperature_flags_and_bad_dates_are_reported(self):
        data = self.parse('1;bad;3.7;0;0\n2;13/10/26 17:15:05;nan;;\n3;13/10/26 17:16:05;inf;2;2')
        self.assertEqual(data.skipped, 1)
        self.assertIsNone(data.detected_profile)
        self.assertTrue(all(r.temperature is None and r.controller_alarm is None for r in data.records))
        self.assertIsNone(data.records[-1].door)

    def test_order_decimal_and_door_priority(self):
        data = self.parse('2;13/10/2026 17:15:05;9,5;1;1\n1;13/10/2026 17:14:52;4;0;0')
        self.assertEqual([r.number for r in data.records], ['1', '2'])
        self.assertEqual(data.records[-1].kind(2, 8), 'Alarme de porta aberta')
        self.assertEqual(data.counts(), {'total': 1, 'high': 1, 'low': 0, 'door': 1})

    def test_invalid_input_is_rejected(self):
        for raw in (b'', b'NAME: x', b'bad;header\n1;2', b'Data Hora;TPrincipal\ninvalid;4'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_txt(raw)

    def test_downsampling_preserves_spikes_and_endpoints(self):
        records = [Record(str(i), datetime(2026, 10, 1) + timedelta(seconds=i),
                          100. if i == 500 else -100. if i == 501 else 4., 0, 0) for i in range(2000)]
        reduced = reduce_points(records, 100)
        self.assertLessEqual(len(reduced), 100)
        self.assertEqual(reduced[0], records[0])
        self.assertEqual(reduced[-1], records[-1])
        self.assertIn(records[500], reduced)
        self.assertIn(records[501], reduced)


class InterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QGuiApplication.instance() or QGuiApplication([])
        QQuickStyle.setStyle('Basic')
        if os.name == 'nt':
            font = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / 'segoeui.ttf'
            if font.exists():
                QFontDatabase.addApplicationFont(str(font))

    def setUp(self):
        self.messages = []
        self.previous_handler = qInstallMessageHandler(lambda kind, context, text: self.messages.append(text))
        self.engine, self.controller = create_engine(visible=False)
        self.window = self.engine.rootObjects()[0]

    def tearDown(self):
        self.window.close()
        self.engine.deleteLater()
        self.application.processEvents()
        qInstallMessageHandler(self.previous_handler)

    def test_file_profiles_alarm_counts_and_manual_override(self):
        self.controller.openFile(QUrl.fromLocalFile(str(ROOT / 'tests' / 'fixtures' / 'freezer.txt')))
        self.assertEqual(self.controller.summary['count'], 36)
        self.assertEqual(self.controller.summary['high'], -15)
        self.assertEqual(self.controller.summary['counts'], {'total': 6, 'high': 3, 'low': 2, 'door': 1})
        self.assertEqual(len(self.controller.recentAlarms(40)), 6)
        self.controller.setProfile('cold_chamber')
        self.assertEqual(self.controller.summary['high'], 8)
        self.controller.setProfile('auto')
        self.controller.openFile(QUrl.fromLocalFile(str(ROOT / 'tests' / 'fixtures' / 'camara_fria.txt')))
        self.assertIn('Câmara Fria', self.controller.summary['equipment'])
        self.assertEqual(self.controller.summary['counts']['total'], 6)

    def test_failed_file_keeps_previous_dataset_and_source_unchanged(self):
        path = ROOT / 'tests' / 'fixtures' / 'freezer.txt'
        original = path.read_bytes()
        self.controller.openFile(QUrl.fromLocalFile(str(path)))
        previous = self.controller.dataset
        errors = []
        self.controller.error.connect(errors.append)
        self.controller.openFile(QUrl.fromLocalFile(str(ROOT / 'not_found.txt')))
        self.assertIs(self.controller.dataset, previous)
        self.assertEqual(len(errors), 1)
        self.assertEqual(path.read_bytes(), original)

    def test_chart_selection_and_zoom_are_connected_to_original_records(self):
        self.controller.openFile(QUrl.fromLocalFile(str(ROOT / 'tests' / 'fixtures' / 'freezer.txt')))
        self.application.processEvents()
        chart = self.window.findChild(QObject, 'temperatureChart')
        self.assertIsNotNone(chart)
        initial_span = chart.property('viewEnd') - chart.property('viewStart')
        QMetaObject.invokeMethod(chart, 'zoom', Q_ARG('QVariant', 2.0), Q_ARG('QVariant', .5))
        self.assertAlmostEqual(chart.property('viewEnd') - chart.property('viewStart'), initial_span / 2)
        QMetaObject.invokeMethod(chart, 'pick', Q_ARG('QVariant', .5))
        selected = self.window.property('selectedRecord')
        self.assertIn('number', selected)
        self.assertEqual(selected['alarm'], 0)
        QMetaObject.invokeMethod(chart, 'reset')
        self.assertAlmostEqual(chart.property('viewEnd') - chart.property('viewStart'), initial_span)

    def test_portrait_landscape_render_and_mouse_tap(self):
        self.controller.openFile(QUrl.fromLocalFile(str(ROOT / 'tests' / 'fixtures' / 'freezer.txt')))
        self.window.setVisible(True)
        for width, height in ((1100, 900), (600, 960), (390, 844)):
            self.window.resize(width, height)
            QTest.qWait(250)
            image = self.window.grabWindow()
            self.assertFalse(image.isNull())
            image.save(str(ROOT / 'qa' / f'preview_{width}.png'))
        self.window.resize(1100, 900)
        QTest.qWait(100)
        chart = self.window.findChild(QObject, 'temperatureChart')
        position = chart.mapToScene(QPointF(chart.width()*.5, 140))
        QTest.mouseClick(self.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(round(position.x()), round(position.y())))
        self.application.processEvents()
        self.assertIn('number', self.window.property('selectedRecord'))
        # Erros de execução QML também aparecem como mensagens Qt, não só exceções Python.
        failures = [m for m in self.messages if any(token in m for token in ('ReferenceError', 'TypeError', 'failed to load', 'Cannot assign', 'Binding loop'))]
        self.assertEqual(failures, [])

    def test_simulated_two_finger_pinch_changes_visible_period(self):
        self.controller.openFile(QUrl.fromLocalFile(str(ROOT / 'tests' / 'fixtures' / 'freezer.txt')))
        self.window.setVisible(True)
        QTest.qWait(100)
        chart = self.window.findChild(QObject, 'temperatureChart')
        center = chart.mapToScene(QPointF(chart.width()*.5, 140))
        cx, cy = round(center.x()), round(center.y())
        original_span = chart.property('viewEnd') - chart.property('viewStart')
        device = QTest.createTouchDevice()
        QTest.touchEvent(self.window, device).press(0, QPoint(cx-40, cy)).press(1, QPoint(cx+40, cy)).commit()
        QTest.qWait(30)
        for distance in (50, 65, 80, 100):
            QTest.touchEvent(self.window, device).move(0, QPoint(cx-distance, cy)).move(1, QPoint(cx+distance, cy)).commit()
            QTest.qWait(30)
        QTest.touchEvent(self.window, device).release(0, QPoint(cx-100, cy)).release(1, QPoint(cx+100, cy)).commit()
        QTest.qWait(30)
        self.assertLess(chart.property('viewEnd') - chart.property('viewStart'), original_span * .8)


if __name__ == '__main__':
    unittest.main()
