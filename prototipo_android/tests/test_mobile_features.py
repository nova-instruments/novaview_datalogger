import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QObject, QUrl, QMetaObject, Q_ARG, QPoint, QPointF, Qt, qInstallMessageHandler
from PySide6.QtGui import QGuiApplication, QFontDatabase
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from controller import Controller
from datalogger import Datalogger, Record, parse_file
from main import create_engine


class MobileDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QGuiApplication.instance() or QGuiApplication([])

    def setUp(self):
        self.controller = Controller()
        self.errors = []
        self.controller.error.connect(self.errors.append)

    def fixture(self):
        when = datetime(2026, 10, 13, 17, 14, 52)
        values = [(4., 0, 0), (9., 1, 0), (1., 1, 1), (10., 1, 1), (4., 0, 1), (None, None, None)]
        records = tuple(Record(str(i), when + timedelta(minutes=i), temperature, door, alarm)
                        for i, (temperature, door, alarm) in enumerate(values))
        self.controller._accept(Datalogger('NI280000', records), 'test.txt')
        return records

    def test_period_bounds_metrics_and_empty_interval(self):
        records = self.fixture()
        previous = self.controller.summary
        self.assertFalse(self.controller.setPeriod(records[-1].timestamp, records[0].timestamp))
        self.assertFalse(self.controller.setPeriod(records[0].timestamp - 1, records[-1].timestamp))
        self.assertFalse(self.controller.setPeriod(float('nan'), records[-1].timestamp))
        self.assertEqual(self.controller.summary, previous)
        self.assertTrue(self.controller.setPeriod(records[1].timestamp, records[3].timestamp))
        self.assertEqual(self.controller.summary['periodCount'], 3)
        self.assertEqual(self.controller.summary['minimum'], 1.)
        self.assertEqual(self.controller.summary['maximum'], 10.)
        self.assertAlmostEqual(self.controller.summary['average'], 20/3)
        self.assertEqual(self.controller.summary['counts'], {'total': 3, 'high': 2, 'low': 1, 'door': 2})
        self.assertEqual(self.controller.dataPage['total'], 3)
        self.assertEqual(self.controller.alarmPage['total'], 3)
        self.assertTrue(self.controller.setPeriod(records[1].timestamp+1, records[2].timestamp-1))
        self.assertEqual(self.controller.dataPage['total'], 0)
        self.assertIsNone(self.controller.summary['average'])
        self.assertEqual(self.controller.recordAt(records[0].timestamp), {})
        self.assertEqual(self.controller.plotPoints(records[0].timestamp, records[-1].timestamp, 400), [])
        self.controller.resetPeriod()
        self.assertEqual(self.controller.dataPage['total'], 6)

    def test_combined_filters_overlap_and_invalid_ranges(self):
        self.fixture()
        c = self.controller
        self.assertTrue(c.setFilters('data', '', 'high', '9,0', '10', False))
        self.assertEqual([r['number'] for r in c.dataPage['rows']], ['1', '3'])
        self.assertEqual(c.dataPage['rows'][0]['alarm'], 0)
        self.assertTrue(c.setFilters('alarms', 'PORTA', 'high', '', '', True))
        self.assertEqual([r['number'] for r in c.alarmPage['rows']], ['3'])
        self.assertTrue(c.setFilters('alarms', '', 'generic', '', '', True))
        self.assertEqual([r['number'] for r in c.alarmPage['rows']], ['4'])
        self.assertTrue(c.setFilters('data', '', 'none', '', '', True))
        self.assertEqual([r['number'] for r in c.dataPage['rows']], ['0'])
        previous = c.dataPage
        for minimum, maximum in [('10', '2'), ('NaN', ''), ('', 'inf'), ('bad', '')]:
            self.assertFalse(c.setFilters('data', '', 'all', minimum, maximum, True))
            self.assertEqual(c.dataPage, previous)
        c.resetFilters('data')
        self.assertEqual(c.dataPage['total'], 6)

    def test_pagination_reaches_all_records_and_resets_after_filter(self):
        start = datetime(2026, 1, 1)
        records = tuple(Record(str(i), start + timedelta(seconds=i), 4., 0, 0) for i in range(129))
        self.controller._accept(Datalogger('NI280000', records), 'test.txt')
        found = []
        for page in range(3):
            self.controller.setPage('data', page)
            found.extend(row['number'] for row in self.controller.dataPage['rows'])
        self.assertEqual(found, [str(i) for i in range(128, -1, -1)])
        self.controller.setPage('data', 1000)
        self.assertEqual(self.controller.dataPage['page'], 2)
        self.controller.setFilters('data', '128', 'all', '', '', False)
        self.assertEqual(self.controller.dataPage['page'], 0)
        self.assertEqual(self.controller.dataPage['total'], 1)

    def test_database_readonly_aliases_timestamp_and_setpoint(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'qa') as folder:
            path = Path(folder) / 'NI280000_0.db'
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE Config (value TEXT)')
                db.execute('CREATE TABLE DataGrpData (IndexID INT, CollectTime INT, Tprincipal REAL, SetPoint REAL, Porta INT, Alarme INT, Degelo REAL, Bateria REAL)')
                timestamp = int(datetime(2026, 10, 13, 20, 14, 52, tzinfo=timezone.utc).timestamp()*1000)
                db.executemany('INSERT INTO DataGrpData VALUES (?,?,?,?,?,?,?,?)', [(1, timestamp, -46., -30., 1, 0, -20., 12.8), (2, timestamp+1000, -14., -30., 0, 0, -20., 12.8)])
            db.close()
            original = path.read_bytes()
            self.controller.openFile(QUrl.fromLocalFile(str(path)))
            self.assertEqual(path.read_bytes(), original)
            data = self.controller.dataset
            self.assertEqual(data.name, 'NI280000')
            self.assertEqual(data.records[0].when, datetime(2026, 10, 13, 17, 14, 52))
            self.assertEqual(data.counts()['total'], 2)
            self.assertEqual(self.controller.summary['setpointAverage'], -30.)
            self.assertEqual(self.controller.dataPage['rows'][0]['battery'], 12.8)
            self.controller.setProfile('cold_chamber')
            self.assertEqual(self.controller.summary['low'], 1.)
        with self.assertRaises(ValueError):
            parse_file(b'invalid', 'bad.db')

    def test_async_file_loading_failure_recovery_and_repeated_selection(self):
        c = self.controller
        c.startOpenFile(QUrl.fromLocalFile(str(ROOT / 'missing.txt')))
        self.assertTrue(c.busy)
        for _ in range(200):
            QTest.qWait(10)
            if not c.busy:
                break
        self.assertFalse(c.busy)
        self.assertEqual(len(self.errors), 1)
        for sample in ('freezer', 'camara_fria', 'freezer'):
            c.startOpenFile(QUrl.fromLocalFile(str(ROOT / 'tests' / 'fixtures' / (sample + '.txt'))))
            for _ in range(200):
                QTest.qWait(10)
                if not c.busy:
                    break
            self.assertFalse(c.busy)
            self.assertEqual(c.summary['count'], 36)
            self.assertEqual(c.profileValue, 'auto')


class MobileInterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QGuiApplication.instance() or QGuiApplication([])
        QQuickStyle.setStyle('Basic')
        if os.name == 'nt':
            QFontDatabase.addApplicationFont(str(Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/segoeui.ttf'))

    def setUp(self):
        self.messages = []
        self.previous = qInstallMessageHandler(lambda kind, context, text: self.messages.append(text))
        self.engine, self.controller = create_engine(False)
        self.window = self.engine.rootObjects()[0]
        self.controller.openFile(QUrl.fromLocalFile(str(ROOT / 'tests' / 'fixtures' / 'freezer.txt')))
        self.window.setVisible(True)

    def tearDown(self):
        self.controller.shutdown()
        self.window.close()
        self.engine.deleteLater()
        self.application.processEvents()
        qInstallMessageHandler(self.previous)

    def test_tabs_tables_filters_and_details_in_portrait_and_landscape(self):
        tabs = self.window.findChild(QObject, 'mainTabs')
        for width, height in ((390, 844), (600, 960), (1100, 900)):
            self.window.resize(width, height)
            for index, name in ((1, 'data'), (2, 'alarms')):
                tabs.setProperty('currentIndex', index)
                QTest.qWait(100)
                self.window.grabWindow().save(str(ROOT / 'qa' / f'{name}_{width}.png'))
                table = self.window.findChild(QObject, name + 'Rows')
                self.assertGreater(table.property('count'), 0)
                self.assertGreater(table.property('height'), 50)
        tabs.setProperty('currentIndex', 1)
        minimum = self.window.findChild(QObject, 'dataMinimum')
        maximum = self.window.findChild(QObject, 'dataMaximum')
        kind = self.window.findChild(QObject, 'dataAlarmFilter')
        minimum.setProperty('text', '-15')
        maximum.setProperty('text', '-10')
        kind.setProperty('currentIndex', 2)
        QMetaObject.invokeMethod(self.window.findChild(QObject, 'dataApply'), 'clicked')
        self.assertEqual(self.controller.dataPage['total'], 3)
        QTest.qWait(100)
        rows = self.window.findChild(QObject, 'dataRows')
        point = rows.mapToScene(QPointF(100, 25))
        QTest.mouseClick(self.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         QPoint(round(point.x()), round(point.y())))
        self.application.processEvents()
        self.assertTrue(self.window.findChild(QObject, 'recordDialog').property('visible'))
        failures = [m for m in self.messages if any(token in m for token in ('ReferenceError', 'TypeError', 'Binding loop', 'Cannot assign'))]
        self.assertEqual(failures, [])

    def test_period_picker_limits_and_empty_period_interface(self):
        self.window.resize(390, 844)
        self.window.setProperty('periodExpanded', True)
        QTest.qWait(100)
        QMetaObject.invokeMethod(self.window, 'chooseDate', Q_ARG('QVariant', True))
        QTest.qWait(100)
        picker = self.window.findChild(QObject, 'periodPicker')
        self.assertTrue(picker.property('visible'))
        self.assertEqual(picker.property('minimum'), self.controller.summary['fullStart'])
        hour = self.window.findChild(QObject, 'periodHour')
        self.assertEqual(hour.property('from'), 8)
        self.assertEqual(hour.property('to'), 13)
        self.window.grabWindow().save(str(ROOT / 'qa' / 'period_390.png'))
        QMetaObject.invokeMethod(picker, 'reject')
        start = self.controller.summary['fullStart']
        self.assertTrue(self.controller.setPeriod(start+1000, start+2000))
        QTest.qWait(100)
        self.assertEqual(self.controller.summary['periodCount'], 0)
        self.window.grabWindow().save(str(ROOT / 'qa' / 'empty_period_390.png'))
        failures = [m for m in self.messages if any(token in m for token in ('ReferenceError', 'TypeError', 'Binding loop', 'Cannot assign'))]
        self.assertEqual(failures, [])


if __name__ == '__main__':
    unittest.main()
