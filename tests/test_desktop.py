import os
from contextlib import closing
os.environ.setdefault('QT_QPA_PLATFORM', 'windows' if os.name == 'nt' else 'offscreen')

from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

import pandas as pd
from PySide6.QtCore import Qt, QDateTime, QPoint, QPointF, QEvent
from PySide6.QtGui import QWheelEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

from desktop_app import DataFrameModel, MainWindow, STYLE, light_palette, prepare_chart, time_values


class DesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])
        cls.application.setStyle('Fusion')
        cls.application.setPalette(light_palette())
        cls.application.setStyleSheet(STYLE)

    def setUp(self):
        temporary_root = Path(__file__).resolve().parents[1] / 'temp'
        temporary_root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temporary_root)
        self.root = Path(self.temp.name)
        self.window = MainWindow()
        self.window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        self.errors = []
        self.window.show_error = self.errors.append
        self.window.show()

    def tearDown(self):
        self.wait_idle()
        self.window.close()
        self.window.deleteLater()
        self.application.processEvents()
        self.temp.cleanup()

    def wait_idle(self):
        deadline = time.monotonic() + 25
        # Processa também o refresh agendado após a importação.
        quiet = 0
        while time.monotonic() < deadline:
            self.application.processEvents()
            if not self.window.jobs:
                quiet += 1
                if quiet > 8:
                    break
            else:
                quiet = 0
            time.sleep(.01)
        self.assertFalse(self.window.jobs, 'Operação não terminou')
        self.assertEqual(self.errors, [])

    def fixture(self, count=600):
        path = self.root / 'BK23110686-39.db'
        timestamps = pd.date_range('2026-10-15', periods=count, freq='5min')
        import numpy as np
        temperature = 4 + 5 * np.sin(np.arange(count) / 20)
        frame = pd.DataFrame({'IndexID': range(count),
            'CollectTime': timestamps.tz_localize('America/Sao_Paulo').as_unit('ms').asi8,
            'Tprincipal': temperature, 'Setpoint': 4., 'Alarme': ((temperature > 8) | (temperature < 1)).astype(int),
            'Porta': (np.arange(count) % 31 == 0).astype(int)})
        with closing(sqlite3.connect(path)) as connection:
            frame.to_sql('DataGrpData', connection, index=False)
        return path

    def test_model_formats_and_numeric_sort(self):
        model = DataFrameModel(pd.DataFrame({'value': [10., 2.], 'when': pd.to_datetime(['2026-10-16', '2026-10-15'])}))
        self.assertEqual(model.data(model.index(0, 0)), '10,00')
        model.sort(0, Qt.SortOrder.AscendingOrder)
        self.assertEqual(model.frame['value'].tolist(), [2., 10.])
        self.assertEqual(model.data(model.index(0, 1)), '15/10/2026 00:00:00')
        model.set_frame(pd.DataFrame({'value': [30., 3.], 'when': [None, None]}))
        self.assertEqual(model.frame['value'].tolist(), [3., 30.])

    def test_load_filter_chart_data_alarms_and_exports(self):
        self.window.load_path(str(self.fixture()))
        self.wait_idle()
        self.assertEqual(self.window.stack.currentIndex(), 1)
        self.assertEqual(self.window.panel_serial.text(), 'Número de série: BK23110686-39')
        self.assertEqual(self.window.data_serial.text(), self.window.panel_serial.text())
        self.assertIsNotNone(self.window.chart.data)
        self.assertEqual(len(self.window.chart.curves), 2)
        start, end = self.window.chart.full_range
        chart = self.window.chart.main
        viewport = chart.viewport()
        position = chart.mapFromScene(chart.getViewBox().sceneBoundingRect().center())
        before = chart.viewRange()[0]
        wheel = QWheelEvent(QPointF(position), QPointF(viewport.mapToGlobal(position)),
                            QPoint(), QPoint(0, 120), Qt.MouseButton.NoButton,
                            Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        self.application.sendEvent(viewport, wheel)
        self.application.processEvents()
        after = chart.viewRange()[0]
        self.assertLess(after[1] - after[0], before[1] - before[0])
        for event_type, point, button, buttons in [
            (QEvent.Type.MouseButtonPress, position, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton),
            (QEvent.Type.MouseMove, position + QPoint(8, 0), Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton),
            (QEvent.Type.MouseMove, position + QPoint(48, 0), Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton),
            (QEvent.Type.MouseButtonRelease, position + QPoint(48, 0), Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton),
        ]:
            event = QMouseEvent(event_type, QPointF(point), QPointF(viewport.mapToGlobal(point)),
                                button, buttons, Qt.KeyboardModifier.NoModifier)
            self.application.sendEvent(viewport, event)
            self.application.processEvents()
        self.assertNotAlmostEqual(chart.viewRange()[0][0], after[0], places=2)
        self.window.chart.reset()
        restored = chart.viewRange()[0]
        self.assertLessEqual(restored[0], start)
        self.assertGreaterEqual(restored[1], end)
        self.assertTrue(self.window.panel_controls.isHidden())
        self.window.panel_controls_toggle.click()
        self.assertFalse(self.window.panel_controls.isHidden())
        self.window.panel_controls_toggle.click()
        self.application.processEvents()
        x, series = self.window.chart.data[:2]
        selected = len(x) // 2
        position = chart.mapFromScene(chart.getViewBox().mapViewToScene(QPointF(float(x[selected]), float(series[0][1][selected]))))
        for event_type, buttons in [(QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton),
                                    (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton)]:
            event = QMouseEvent(event_type, QPointF(position), QPointF(viewport.mapToGlobal(position)),
                                Qt.MouseButton.LeftButton, buttons, Qt.KeyboardModifier.NoModifier)
            self.application.sendEvent(viewport, event)
            self.application.processEvents()
        # As coordenadas de mouse são arredondadas para pixels; pontos densos
        # podem selecionar o vizinho imediato, que deve fornecer a linha exata.
        clicked_index = self.window.chart.selected_index
        self.assertIsNotNone(clicked_index)
        self.assertLessEqual(abs(clicked_index - selected), 1)
        self.assertFalse(self.window.chart.details.isHidden())
        record = self.window.chart.details_model.frame.iloc[0]
        self.assertAlmostEqual(record['Tprincipal'], series[0][1][clicked_index])
        self.assertIn('porta', self.window.chart.details_model.frame)
        self.assertIn('Tipo de alarme', self.window.chart.details_model.frame)
        self.window.grab().save('temp/selected_point_preview.png')
        self.window.chart.clear_selection()
        self.assertTrue(self.window.chart.details.isHidden())
        self.assertEqual(self.window.chart.details_model.rowCount(), 0)
        self.window.tabs.setCurrentIndex(1)
        self.wait_idle()
        self.assertGreater(self.window.data_model.rowCount(), 0)
        self.window.data_range.setCurrentText('Completo')
        self.wait_idle()
        self.assertEqual(self.window.data_model.rowCount(), 600)
        self.window.grab().save('temp/data_preview.png')
        self.window.search.setText('9999999')
        self.window.search_timer.stop()
        self.window.refresh()
        self.wait_idle()
        self.assertEqual(self.window.data_model.rowCount(), 0)
        self.window.search.clear()
        self.window.search_timer.stop()
        self.window.refresh()
        self.wait_idle()
        self.window._exported = lambda path: None
        for kind in ['xlsx', 'pdf']:
            destination = self.root / f'export.{kind}'
            with patch('desktop_app.QFileDialog.getSaveFileName', return_value=(str(destination), '')):
                self.window.export(kind)
                self.wait_idle()
            self.assertTrue(destination.is_file())
            self.assertGreater(destination.stat().st_size, 1000)
        self.window.tabs.setCurrentIndex(2)
        self.wait_idle()
        self.assertGreater(self.window.alarm_model.rowCount(), 0)
        self.assertIn('Último alarme:', self.window.latest_alarm.text())
        self.window.grab().save('temp/alarms_preview.png')
        self.window.tabs.setCurrentIndex(0)
        self.wait_idle()
        self.window.grab().save('temp/desktop_preview.png')

    def test_empty_single_point_and_missing_time_chart(self):
        self.assertIsNone(prepare_chart(pd.DataFrame({'Tprincipal': [4]}), ['Tprincipal']))
        frame = pd.DataFrame({'Time_dt': [pd.Timestamp('2026-10-16 12:00:00')], 'Tprincipal': [4.]})
        self.window.chart.set_chart(prepare_chart(frame, ['Tprincipal']))
        self.assertEqual(len(self.window.chart.curves), 1)
        self.assertEqual(time_values(frame.Time_dt)[0], pd.Timestamp('2026-10-16 12:00:00').value / 1e9)
        self.window.chart.set_chart(None)
        self.assertIsNone(self.window.chart.full_range)

    def test_point_selection_distinguishes_same_timestamp_and_keeps_unplotted_values(self):
        frame = pd.DataFrame({
            'Time_dt': pd.to_datetime(['2026-10-16 12:00:00', '2026-10-16 12:00:00', '2026-10-16 13:00:00']),
            'Tprincipal': [2., 9., 4.], 'Bateria': [11., 12., 13.], 'Alarme': [0, 1, 0],
        })
        self.window.stack.setCurrentIndex(1)
        self.window.chart.set_chart(prepare_chart(frame, ['Tprincipal']))
        self.application.processEvents()
        chart = self.window.chart.main
        x = self.window.chart.data[0]
        position = chart.mapFromScene(chart.getViewBox().mapViewToScene(QPointF(float(x[1]), 9.)))
        viewport = chart.viewport()
        for event_type, buttons in [(QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton),
                                    (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton)]:
            self.application.sendEvent(viewport, QMouseEvent(
                event_type, QPointF(position), QPointF(viewport.mapToGlobal(position)),
                Qt.MouseButton.LeftButton, buttons, Qt.KeyboardModifier.NoModifier))
            self.application.processEvents()
        self.assertEqual(self.window.chart.selected_index, 1)
        record = self.window.chart.details_model.frame.iloc[0]
        self.assertEqual(record['Tprincipal'], 9.)
        self.assertEqual(record['Bateria'], 12.)
        self.window.chart.set_chart(None)
        self.assertTrue(self.window.chart.details.isHidden())
        self.assertIsNone(self.window.chart.selected_index)

    def test_equipment_profile_updates_chart_data_alarms_and_pdf(self):
        path = self.root / 'freezer.txt'
        path.write_text('NAME: NI280000\nR;Data Hora;TPrincipal;PA;Al\n'
                        '1;13/10/26 17:14:52;-30;0;0\n'
                        '2;13/10/26 17:15:05;-46;0;0\n'
                        '3;13/10/26 17:16:05;-14;0;0\n', encoding='utf-8')
        self.assertEqual(self.window.equipment_profile.currentData(), 'auto')
        self.window.load_path(str(path))
        self.wait_idle()
        self.assertEqual((self.window.dataset.low_limit, self.window.dataset.high_limit), (-45, -15))
        self.assertIn('-45', self.window.alarm_limits_label.text())
        self.assertIn('Identificado: Freezer', self.window.alarm_limits_label.text())
        self.window.tabs.setCurrentIndex(2)
        self.wait_idle()
        self.assertEqual(self.window.alarm_model.rowCount(), 2)
        self.assertEqual([label.text() for label in self.window.alarm_values], ['2', '1', '1', '0'])
        self.window.tabs.setCurrentIndex(1)
        self.wait_idle()
        self.window.alarm_filter.setCurrentIndex(self.window.alarm_filter.findData('high'))
        self.wait_idle()
        self.assertEqual(self.window.data_model.frame['Tprincipal'].tolist(), [-14])
        self.window._exported = lambda path: None
        destination = self.root / 'freezer.pdf'
        import datalogger_core as core
        with patch('desktop_app.QFileDialog.getSaveFileName', return_value=(str(destination), '')), \
             patch('desktop_app.core.build_report_pdf', wraps=core.build_report_pdf) as report:
            self.window.export('pdf')
            self.wait_idle()
            self.assertEqual(report.call_args.args[3:5], (-15, -45))
        self.assertTrue(destination.read_bytes().startswith(b'%PDF-'))
        self.window.equipment_profile.setCurrentIndex(self.window.equipment_profile.findData('cold_chamber'))
        self.wait_idle()
        self.assertEqual((self.window.dataset.low_limit, self.window.dataset.high_limit), (2, 8))
        self.assertEqual(self.window.data_model.rowCount(), 0)
        self.assertFalse(self.errors)

    def test_automatic_profile_reidentifies_new_files_and_allows_manual_override(self):
        path = self.root / 'automatic.txt'
        path.write_text('R;Data Hora;TPrincipal;PA;Al\n1;13/10/26 17:14:52;-30;0;0\n', encoding='utf-8')
        self.window.load_path(str(path))
        self.wait_idle()
        self.assertEqual(self.window.dataset.equipment_profile, 'freezer')
        path.write_text('R;Data Hora;TPrincipal;PA;Al\n1;13/10/26 17:14:52;4;0;0\n', encoding='utf-8')
        self.window.load_path(str(path))
        self.wait_idle()
        self.assertEqual(self.window.dataset.equipment_profile, 'cold_chamber')
        self.assertIn('Câmara Fria', self.window.alarm_limits_label.text())
        self.window.equipment_profile.setCurrentIndex(self.window.equipment_profile.findData('freezer'))
        self.wait_idle()
        self.assertEqual(self.window.dataset.high_limit, -15)
        self.window.equipment_profile.setCurrentIndex(self.window.equipment_profile.findData('auto'))
        self.wait_idle()
        self.assertEqual(self.window.dataset.high_limit, 8)
        path.write_text('R;Data Hora;TPrincipal;PA;Al\n1;13/10/26 17:14:52;;0;0\n', encoding='utf-8')
        self.window.load_path(str(path))
        self.wait_idle()
        self.assertIn('Sem temperatura válida', self.window.alarm_limits_label.text())
        self.assertFalse(self.errors)

    def test_advanced_data_filters_combine_and_clear(self):
        self.window.load_path(str(self.fixture()))
        self.wait_idle()
        self.window.tabs.setCurrentIndex(1)
        self.wait_idle()
        original_count = self.window.data_model.rowCount()
        self.window.temp_min.setText('8,2')
        self.window.temp_max.setText('9.0')
        self.window.alarm_filter.setCurrentIndex(self.window.alarm_filter.findData('high'))
        self.wait_idle()
        filtered = self.window.data_model.frame
        self.assertGreater(len(filtered), 0)
        self.assertLess(len(filtered), original_count)
        self.assertTrue(filtered['Tprincipal'].between(8.2, 9).all())
        self.assertTrue(filtered['Tipo de alarme'].isin(['Alarme de alta temperatura', 'Alarme de porta aberta']).all())
        self.window.grab().save('temp/advanced_filters_preview.png')
        self.window._exported = lambda path: None
        destination = self.root / 'filtered.xlsx'
        with patch('desktop_app.QFileDialog.getSaveFileName', return_value=(str(destination), '')):
            self.window.export('xlsx')
            self.wait_idle()
        exported = pd.read_excel(destination)
        self.assertEqual(exported['indexID'].tolist(), filtered['indexID'].tolist())
        self.assertEqual(exported['Tipo de alarme'].tolist(), filtered['Tipo de alarme'].tolist())
        self.window.temp_min.setText('10')
        self.window.refresh()
        self.assertEqual(len(self.errors), 1)
        self.errors.clear()
        self.assertEqual(len(self.window.data_model.frame), len(filtered))
        self.window._clear_data_filters()
        self.wait_idle()
        self.assertEqual(self.window.data_model.rowCount(), original_count)
        self.assertFalse(self.window.temp_min.text())
        self.assertEqual(self.window.alarm_filter.currentData(), 'all')

    def test_panel_limits_period_to_imported_data_and_resets_on_reimport(self):
        self.window.load_path(str(self.fixture()))
        self.wait_idle()
        self.assertEqual(self.window.datalogger_start.text(), 'Início do datalogger: 15/10/2026 00:00:00')
        self.assertEqual(self.window.datalogger_end.text(), 'Fim do datalogger: 17/10/2026 01:55:00')
        minimum = QDateTime(pd.Timestamp('2026-10-15').to_pydatetime())
        maximum = QDateTime(pd.Timestamp('2026-10-17 01:55:00').to_pydatetime())
        for editor in (self.window.start, self.window.end):
            self.assertEqual(editor.minimumDateTime(), minimum)
            self.assertEqual(editor.maximumDateTime(), maximum)
            editor.setDateTime(minimum.addSecs(-1))
            self.assertEqual(editor.dateTime(), minimum)
            editor.setDateTime(maximum.addSecs(1))
            self.assertEqual(editor.dateTime(), maximum)
        # Um novo arquivo pode ter um intervalo completamente diferente.
        path = self.root / 'earlier.txt'
        path.write_text('R;Data Hora;TPrincipal;PA\n1;01/01/25 12:00:00;4;0\n', encoding='utf-8')
        self.window.load_path(str(path))
        self.wait_idle()
        expected = QDateTime(pd.Timestamp('2025-01-01 12:00:00').to_pydatetime())
        for editor in (self.window.start, self.window.end):
            self.assertEqual(editor.minimumDateTime(), expected)
            self.assertEqual(editor.maximumDateTime(), expected)
            self.assertEqual(editor.dateTime(), expected)

    def test_failed_import_preserves_dataset_and_source_without_dates(self):
        path = self.root / 'no_dates.db'
        with closing(sqlite3.connect(path)) as connection:
            pd.DataFrame({'Tprincipal': [4., 6.]}).to_sql('readings', connection, index=False)
        self.window.load_path(str(path))
        self.wait_idle()
        self.assertFalse(self.window.start.isEnabled())
        self.assertEqual(self.window.datalogger_start.text(), 'Início do datalogger: não informado')
        self.assertEqual(self.window.datalogger_end.text(), 'Fim do datalogger: não informado')
        self.assertIsNone(self.window.chart.data)
        self.assertEqual(self.window.panel_values[0].text(), '5,00')
        original = self.window.dataset
        with self.assertLogs(level='ERROR'):
            self.window.load_path(str(self.root / 'missing.db'))
            deadline = time.monotonic() + 5
            while self.window.jobs and time.monotonic() < deadline:
                self.application.processEvents()
                time.sleep(.01)
        self.assertIs(self.window.dataset, original)
        self.assertEqual(len(self.errors), 1)
        self.errors.clear()


if __name__ == '__main__':
    unittest.main()
