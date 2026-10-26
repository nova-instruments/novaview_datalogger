from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from io import BytesIO

import pandas as pd
from pandas.testing import assert_frame_equal

import datalogger_core as core
from data_service import (Dataset, alarm_history, filter_records, load_dataset,
                          parse_temperature_bound, search_dataframe, detect_equipment_profile)


class CoreTests(unittest.TestCase):
    def setUp(self):
        temporary_root = Path(__file__).resolve().parents[1] / 'temp'
        temporary_root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temporary_root)
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def database(self, path, frame, table='DataGrpData'):
        with closing(sqlite3.connect(path)) as connection:
            frame.to_sql(table, connection, index=False)
        return path

    def test_db_timezone_aliases_and_original_alarm_flags(self):
        path = self.database(self.root / 'device.db', pd.DataFrame({
            'CollectTime': [0, 1000], 'temp principal': [1.5, 9], 'Alarme': [0, 1]}))
        dataset = load_dataset(str(path))
        self.assertEqual(dataset.frame['CollectTime_dt'].iloc[0], pd.Timestamp('1969-12-31 21:00:00'))
        self.assertIn('Tprincipal', dataset.frame)
        self.assertEqual(dataset.low_limit, 1)
        self.assertEqual(dataset.frame['Alarme'].tolist(), [0, 1])

    def test_txt_time_and_alarm_boundaries(self):
        path = self.root / 'export.txt'
        path.write_text('NAME: equipamento AB123\nR;Data Hora;TPrincipal;PA\n'
                        '1;16/10/26 1:2:3;1.5;0\n2;16/10/26 1:3:3;2;0\n'
                        '3;16/10/26 1:4:3;8;0\n4;16/10/26 1:5:3;8.1;0\n'
                        '5;16/10/26 1:6:3;4;1\n', encoding='utf-8')
        dataset = load_dataset(str(path))
        self.assertEqual(dataset.frame['Time_dt'].iloc[0], pd.Timestamp('2026-10-16 01:02:03'))
        self.assertEqual(dataset.frame['Alarme'].tolist(), [1, 0, 0, 1, 1])
        self.assertEqual(dataset.low_limit, 2)
        self.assertEqual(core.extract_txt_device_name(dataset.source_label), 'AB123')
        self.assertEqual(dataset.serial_number, 'AB123')

    def test_serial_identification_preserves_full_serial_and_ignores_bank_suffix(self):
        frame = pd.DataFrame({'Tprincipal': [4.]})
        for filename in ['BK23110686-39.db', 'BK23110686-39_0.db', 'backup_BK23110686-39_10.db']:
            self.assertEqual(Dataset(frame, filename, '1–11', 2).serial_number, 'BK23110686-39')
        self.assertEqual(Dataset(frame, 'device.db', '1–11', 2).serial_number, 'Não informado')
        metadata = pd.DataFrame({'SerialNumber': ['000123', '000123']})
        self.assertEqual(Dataset(metadata, 'device.db', '-', 1).serial_number, '000123')

    def test_txt_controller_alarm_is_authoritative(self):
        path = self.root / 'NI280000.txt'
        path.write_text('NAME: NI280000\nR;Data Hora;TPrincipal;PA;Al\n'
                        '1;13/10/26 17:14:52;3.70;1;0\n'
                        '2;13/10/26 17:15:05;3.70;0;0\n'
                        '3;13/10/26 17:16:05;9.70;1;0\n'
                        '4;13/10/26 17:17:05;1.00;0;0\n'
                        '5;13/10/26 17:18:05;3.70;0;1\n'
                        '6;13/10/26 17:19:05;9.70;0;\n', encoding='utf-8')
        dataset = load_dataset(str(path))
        self.assertEqual(dataset.serial_number, 'NI280000')
        self.assertEqual(dataset.frame['Alarme'].iloc[:5].tolist(), [0, 0, 0, 0, 1])
        self.assertTrue(pd.isna(dataset.frame['Alarme'].iloc[5]))
        self.assertNotIn('Al', dataset.frame)
        history, counts = alarm_history(dataset.frame, dataset.low_limit)
        self.assertEqual(history['Registro'].tolist(), [6, 5, 4, 3])
        self.assertEqual(counts, [4, 2, 1, 0])
        self.assertEqual(filter_records(dataset.frame, alarm_type='none', low_limit=2)['Registro'].tolist(), [1, 2])
        self.assertEqual(filter_records(dataset.frame, alarm_type='any', low_limit=2)['Registro'].tolist(), [3, 4, 5, 6])

    def test_temperature_conditions_precede_controller_confirmation(self):
        frame = pd.DataFrame({'Registro': range(7), 'Tprincipal': [9., 1., 2., 8., 9., 4., 4.],
                              'Porta': [1, 0, 0, 0, 1, 1, 0], 'Alarme': [0, 0, 0, 0, 1, 0, 1]})
        history, counts = alarm_history(frame, 2)
        self.assertEqual(history['Registro'].tolist(), [6, 4, 1, 0])
        self.assertEqual(counts, [4, 2, 1, 1])
        self.assertEqual(history['Tipo'].iloc[-1], 'Alarme de alta temperatura')
        self.assertEqual(filter_records(frame, alarm_type='high')['Registro'].tolist(), [0, 4])
        self.assertEqual(filter_records(frame, alarm_type='low', low_limit=2)['Registro'].tolist(), [1])
        self.assertEqual(filter_records(frame, alarm_type='none', low_limit=2)['Registro'].tolist(), [2, 3, 5])
        self.assertEqual(frame['Alarme'].tolist(), [0, 0, 0, 0, 1, 0, 1])
        missing = pd.DataFrame({'Tprincipal': [9., 1., 4.]})
        self.assertEqual(alarm_history(missing, 2)[1], [2, 1, 1, 0])

    def test_alarm_rules_preserve_original_flags_in_ihm(self):
        self.database(self.root / 'NI280000_0.db', pd.DataFrame({
            'Tprincipal': [9., 1., 4.], 'Porta': [1, 0, 0], 'Al': [0, 0, 1]}))
        dataset = load_dataset(str(self.root), folder=True)
        self.assertEqual(dataset.frame['Alarme'].tolist(), [0, 0, 1])
        original = pd.DataFrame({'Tprincipal': [9.], 'Porta': [1], 'Alarme': [0]})
        assert_frame_equal(core.apply_alarm_rules(original), original)

    def test_freezer_limits_and_profile_switch_preserve_controller_alarm(self):
        frame = pd.DataFrame({'Registro': range(6), 'Tprincipal': [-46., -45., -30., -15., -14., None],
                              'Porta': [0] * 6, 'Alarme': [0] * 6})
        dataset = Dataset(frame, 'freezer.db', '-', 1).with_equipment_profile('freezer')
        self.assertEqual((dataset.low_limit, dataset.high_limit), (-45, -15))
        history, counts = alarm_history(dataset.frame, dataset.low_limit, dataset.high_limit)
        self.assertEqual(counts, [2, 1, 1, 0])
        self.assertEqual(history['Registro'].tolist(), [4, 0])
        self.assertEqual(history['Tipo'].tolist(), ['Alarme de alta temperatura', 'Alarme de baixa temperatura'])
        self.assertEqual(filter_records(dataset.frame, alarm_type='high', low_limit=-45, high_limit=-15)['Registro'].tolist(), [4])
        self.assertEqual(filter_records(dataset.frame, alarm_type='low', low_limit=-45, high_limit=-15)['Registro'].tolist(), [0])
        self.assertEqual(filter_records(dataset.frame, alarm_type='none', low_limit=-45, high_limit=-15)['Registro'].tolist(), [1, 2, 3, 5])
        self.assertEqual(dataset.frame['Alarme'].tolist(), [0] * 6)
        refrigerator = dataset.with_equipment_profile('cold_chamber')
        self.assertEqual((refrigerator.low_limit, refrigerator.high_limit), (1, 8))
        self.assertEqual(refrigerator.frame['Alarme'].tolist(), [0] * 6)

    def test_automatic_equipment_detection_uses_finite_median(self):
        cases = [([-30., -31., -29., 20., 4.], 'freezer'),
                 ([3., 4., 5., -50.], 'cold_chamber'),
                 ([-10.], 'freezer'), ([-9.9], 'cold_chamber'),
                 ([None, 'invalid', float('inf'), float('-inf')], None)]
        for values, expected in cases:
            with self.subTest(values=values):
                frame = pd.DataFrame({'Tprincipal': values})
                self.assertEqual(detect_equipment_profile(frame), expected)
                dataset = Dataset(frame.assign(Alarme=0), 'device.txt', '-', 2).with_equipment_profile('auto')
                self.assertEqual(dataset.high_limit, -15 if expected == 'freezer' else 8)
        self.assertIsNone(detect_equipment_profile(pd.DataFrame({'Porta': [1]})))

    def test_legacy_txt_recalculates_for_freezer_without_false_generic_alarms(self):
        path = self.root / 'legacy.txt'
        path.write_text('R;Data Hora;TPrincipal;PA\n1;13/10/26 17:14:52;-30;0\n'
                        '2;13/10/26 17:15:05;-46;0\n3;13/10/26 17:16:05;-14;0\n', encoding='utf-8')
        original = load_dataset(str(path))
        self.assertTrue(original.calculated_alarm)
        freezer = original.with_equipment_profile('auto')
        self.assertEqual(freezer.frame['Alarme'].tolist(), [0, 1, 1])
        self.assertEqual(alarm_history(freezer.frame, freezer.low_limit, freezer.high_limit)[1], [2, 1, 1, 0])
        self.assertEqual(freezer.with_equipment_profile('cold_chamber').low_limit, 2)
        self.assertEqual(original.frame['Alarme'].tolist(), [1, 1, 1])

    def test_ihm_partial_database_and_bank_metadata(self):
        folder = self.root / 'DataLogFile'
        folder.mkdir()
        for bank in [10, 2]:
            self.database(folder / f'device_{bank}.db', pd.DataFrame({
                'CollectTime': [bank * 1000], 'Tprincipal': [1.5], 'Porta': [0]}))
        (folder / 'broken_3.db').write_text('not a database')
        dataset = load_dataset(str(self.root), folder=True)
        self.assertEqual(dataset.source_label, '3–11')
        self.assertEqual(len(dataset.frame), 2)
        self.assertEqual(dataset.frame['Alarme'].tolist(), [1, 1])
        self.assertEqual(len(dataset.notices), 2)
        self.assertEqual([p.stem for p in core.list_ihm_db_files(self.root)], ['device_2', 'broken_3', 'device_10'])

    def test_reimport_same_path_reads_new_data(self):
        path = self.database(self.root / 'same.db', pd.DataFrame({'Tprincipal': [3]}))
        first = load_dataset(str(path))
        with closing(sqlite3.connect(path)) as connection:
            connection.execute('UPDATE DataGrpData SET Tprincipal=7')
            connection.commit()
        self.assertEqual(first.frame['Tprincipal'].iloc[0], 3)
        self.assertEqual(load_dataset(str(path)).frame['Tprincipal'].iloc[0], 7)

    def test_period_includes_milliseconds_and_range_uses_data_end(self):
        frame = pd.DataFrame({'Time_dt': pd.to_datetime([
            '2026-10-01 10:00:00.000', '2026-10-16 10:00:00.999', '2026-10-16 10:00:01.000'])})
        start = pd.Timestamp('2026-10-16 10:00:00')
        filtered = core.filter_by_period(frame, start.date(), start.time(), start.date(), start.time())
        self.assertEqual(len(filtered), 1)
        self.assertEqual(len(core.filter_data_by_range(frame, '1 dia')), 2)

    def test_search_is_literal_and_alarm_priority_is_preserved(self):
        frame = pd.DataFrame({'Tprincipal': [9., 1.5, 5.], 'Porta': [1, 0, 0], 'Alarme': [1, 1, 1]})
        history, counts = alarm_history(frame, 2)
        self.assertEqual(counts, [3, 1, 1, 1])
        self.assertEqual(history['Tipo'].iloc[-1], 'Alarme de porta aberta')
        self.assertEqual(len(search_dataframe(pd.DataFrame({'text': ['a.b', 'axb']}), '.')), 1)

    def test_combined_alarm_temperature_and_text_filters(self):
        frame = pd.DataFrame({'Registro': range(6), 'Tprincipal': [9., 9., 1.5, 8., 5., None],
                              'Porta': [0, 1, 0, 0, 0, 0], 'Alarme': [1, 1, 1, 0, 1, None]})
        high = filter_records(frame, 'alta temperatura', 'high', 9, 9, low_limit=2)
        self.assertEqual(high['Registro'].tolist(), [0])
        self.assertEqual(filter_records(frame, alarm_type='door')['Registro'].tolist(), [1])
        self.assertEqual(filter_records(frame, alarm_type='low', low_limit=2)['Registro'].tolist(), [2])
        self.assertTrue(filter_records(frame, alarm_type='low', low_limit=1).empty)
        self.assertEqual(filter_records(frame, alarm_type='none')['Registro'].tolist(), [3])
        self.assertEqual(filter_records(frame, alarm_type='generic')['Registro'].tolist(), [2, 4])
        self.assertEqual(filter_records(frame, alarm_type='any')['Registro'].tolist(), [0, 1, 2, 4])
        self.assertEqual(filter_records(frame, minimum=8, maximum=9)['Registro'].tolist(), [0, 1, 3])
        self.assertEqual(filter_records(pd.DataFrame({'Tprincipal': [4]}))['Tipo de alarme'].iloc[0], 'Sem informação de alarme')
        with self.assertRaises(ValueError):
            filter_records(frame, minimum=9, maximum=8)

    def test_temperature_input_accepts_decimal_separators_and_rejects_invalid_values(self):
        self.assertEqual(parse_temperature_bound(' -5,5 '), -5.5)
        self.assertEqual(parse_temperature_bound('8.0'), 8)
        self.assertIsNone(parse_temperature_bound(' '))
        for invalid in ['x', '1,2,3', 'nan', 'inf']:
            with self.assertRaises(ValueError):
                parse_temperature_bound(invalid)

    def test_exports_roundtrip_and_special_table_name(self):
        frame = pd.DataFrame({'Tprincipal': [3., 8., 9.], 'Alarme': [0, 0, 1], 'Porta': [0, 0, 0],
                              'CollectTime': [0, 1000, 2000]})
        path = self.database(self.root / 'quoted.db', frame, 'table"name')
        assert_frame_equal(core.read_table(str(path), 'table"name'), frame)
        normalized = core.normalize_dataframe(frame)
        display = core.prepare_display_dataframe(normalized)
        data = core.dataframe_to_excel_bytes(display)
        restored = pd.read_excel(BytesIO(data))
        self.assertEqual(list(restored.columns), list(display.columns))
        self.assertEqual(len(restored), 3)
        pdf = core.build_report_pdf(normalized, 'teste.db')
        self.assertTrue(pdf.startswith(b'%PDF-'))
        self.assertTrue(pdf.rstrip().endswith(b'%%EOF'))

    def test_invalid_sources_do_not_create_database(self):
        path = self.root / 'missing.db'
        with self.assertRaises(ValueError):
            load_dataset(str(path))
        self.assertFalse(path.exists())
        with self.assertRaises(sqlite3.OperationalError):
            core.list_tables(str(path))
        self.assertFalse(path.exists())


if __name__ == '__main__':
    unittest.main()
