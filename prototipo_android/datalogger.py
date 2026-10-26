"""Leitor TXT independente. Não importa nem modifica o aplicativo Windows."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
import math
import re
import sqlite3
import tempfile
from pathlib import Path
from functools import cached_property
from statistics import median

MAX_BYTES = 30 * 1024 * 1024
MAX_RECORDS = 100_000


@dataclass(frozen=True)
class Record:
    number: str
    when: datetime
    temperature: float | None
    door: int | None
    controller_alarm: int | None
    setpoint: float | None = None
    defrost: float | None = None
    outlet: float | None = None
    battery: float | None = None

    @property
    def timestamp(self) -> float:
        return self.when.timestamp() * 1000

    def kind(self, low: float, high: float) -> str:
        if self.controller_alarm == 1 and self.door == 1:
            return 'Alarme de porta aberta'
        if self.temperature is not None and self.temperature > high:
            return 'Alta temperatura'
        if self.temperature is not None and self.temperature < low:
            return 'Baixa temperatura'
        if self.controller_alarm == 1:
            return 'Alarme ativo sem classificação'
        return 'Sem alarme' if self.controller_alarm == 0 else 'Sem informação do controlador'

    def as_dict(self, low: float, high: float) -> dict:
        return {'number': self.number, 'time': self.when.strftime('%d/%m/%Y %H:%M:%S'),
                'x': self.timestamp, 'y': self.temperature, 'door': self.door,
                'alarm': self.controller_alarm, 'kind': self.kind(low, high),
                'setpoint': self.setpoint, 'defrost': self.defrost,
                'outlet': self.outlet, 'battery': self.battery}

    def flags(self, low, high):
        high_flag = self.temperature is not None and self.temperature > high
        low_flag = self.temperature is not None and self.temperature < low
        door_flag = self.door == 1 and self.controller_alarm == 1
        return {'high': high_flag, 'low': low_flag, 'door': door_flag,
                'any': high_flag or low_flag or self.controller_alarm == 1,
                'generic': self.controller_alarm == 1 and not (high_flag or low_flag or door_flag)}


@dataclass(frozen=True)
class Datalogger:
    name: str
    records: tuple[Record, ...]
    skipped: int = 0
    chamber_low: float = 2.

    @cached_property
    def detected_profile(self) -> str | None:
        temperatures = [r.temperature for r in self.records if r.temperature is not None]
        if not temperatures:
            return None
        return 'freezer' if median(temperatures) <= -10 else 'cold_chamber'

    def limits(self, profile: str = 'auto') -> tuple[float, float]:
        if profile not in ('auto', 'freezer', 'cold_chamber'):
            raise ValueError('Tipo de equipamento inválido.')
        effective = self.detected_profile if profile == 'auto' else profile
        return (-45., -15.) if effective == 'freezer' else (self.chamber_low, 8.)

    def counts(self, profile: str = 'auto') -> dict:
        low, high = self.limits(profile)
        high_count = low_count = door_count = total = 0
        for record in self.records:
            high_flag = record.temperature is not None and record.temperature > high
            low_flag = record.temperature is not None and record.temperature < low
            door_flag = record.controller_alarm == 1 and record.door == 1
            high_count += high_flag
            low_count += low_flag
            door_count += door_flag
            total += high_flag or low_flag or record.controller_alarm == 1
        return {'total': total, 'high': high_count, 'low': low_count, 'door': door_count}


def _number(value: str | None) -> float | None:
    try:
        result = float((value or '').strip().replace(',', '.'))
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def _flag(value: str | None) -> int | None:
    number = _number(value)
    return int(number) if number in (0, 1) else None


def parse_txt(data: bytes) -> Datalogger:
    if len(data) > MAX_BYTES:
        raise ValueError('Selecione um arquivo de até 30 MB.')
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = data.decode('cp1252')
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    name = 'Não informado'
    if lines and lines[0].upper().startswith('NAME:'):
        name = lines.pop(0).split(':', 1)[1].strip() or name
    if len(lines) < 2:
        raise ValueError('O arquivo precisa conter um cabeçalho e registros de temperatura.')
    reader = csv.DictReader(lines, delimiter=';')
    aliases = {'r': 'number', 'registro': 'number', 'data hora': 'time', 'time': 'time',
               'tprincipal': 'temperature', 'pa': 'door', 'porta': 'door',
               'al': 'alarm', 'alarme': 'alarm'}
    columns = {aliases[c.strip().lower()]: c for c in (reader.fieldnames or [])
               if c.strip().lower() in aliases}
    if not {'time', 'temperature'} <= columns.keys():
        raise ValueError('Formato não reconhecido. Use um TXT com Data Hora e TPrincipal, separados por ponto e vírgula.')
    records, skipped = [], 0
    for index, row in enumerate(reader, 1):
        if index > MAX_RECORDS:
            raise ValueError('O limite é de 100.000 registros por arquivo.')
        if None in row:
            skipped += 1
            continue
        value = lambda key: row.get(columns.get(key, ''), '') or ''
        when = None
        for date_format in ('%d/%m/%y %H:%M:%S', '%d/%m/%Y %H:%M:%S'):
            try:
                when = datetime.strptime(value('time').strip(), date_format)
                break
            except ValueError:
                pass
        if when is None:
            skipped += 1
            continue
        records.append(Record(value('number') or str(index), when,
                              _number(value('temperature')), _flag(value('door')), _flag(value('alarm'))))
    if not records:
        raise ValueError('Nenhum registro com data e hora válidas foi encontrado.')
    return Datalogger(name, tuple(sorted(records, key=lambda record: record.when)), skipped)


def parse_database(raw: bytes, filename: str) -> Datalogger:
    """Lê uma cópia privada e temporária, sem escrever no arquivo do equipamento."""
    if len(raw) > MAX_BYTES:
        raise ValueError('Selecione um arquivo de até 30 MB.')
    aliases = {'collecttime': 'time', 'starttime': 'time', 'timestamp': 'time',
               'time': 'time', 'data hora': 'time', 'data e hora': 'time',
               'tprincipal': 'temperature', 't principal': 'temperature',
               'temperatura principal': 'temperature', 'temp principal': 'temperature',
               'indexid': 'number', 'registro': 'number', 'r': 'number',
               'al': 'alarm', 'alarme': 'alarm', 'porta': 'door', 'pa': 'door',
               'setpoint': 'setpoint', 'set point': 'setpoint', 'sp': 'setpoint',
               'degelo': 'defrost', 'tdegelo': 'defrost', 'tomada': 'outlet',
               'bateria': 'battery'}
    try:
        with tempfile.TemporaryDirectory(prefix='novaview-read-') as directory:
            path = Path(directory) / 'equipment.db'
            path.write_bytes(raw)
            connection = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
            try:
                connection.execute('PRAGMA query_only=ON')
                # Interrompe consultas em bancos danificados ou excessivamente complexos.
                budget = [0]
                def progress():
                    budget[0] += 1
                    return int(budget[0] > 20000)
                connection.set_progress_handler(progress, 1000)
                tables = [r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
                tables.sort(key=lambda name: (name != 'DataGrpData', name))
                for table in tables:
                    quoted = '"' + table.replace('"', '""') + '"'
                    cursor = connection.execute('SELECT * FROM ' + quoted + ' LIMIT ?', (MAX_RECORDS + 1,))
                    columns = {}
                    for index, description in enumerate(cursor.description):
                        canonical = aliases.get(description[0].strip().casefold())
                        if canonical is not None and canonical not in columns:
                            columns[canonical] = index
                    if not {'time', 'temperature'} <= columns.keys():
                        continue
                    records, skipped = [], 0
                    for index, row in enumerate(cursor, 1):
                        if index > MAX_RECORDS:
                            raise ValueError('O limite é de 100.000 registros por arquivo.')
                        value = lambda key: row[columns[key]] if key in columns else None
                        date = value('time')
                        try:
                            # CollectTime e Timestamp usam milissegundos desde UTC.
                            if isinstance(date, (int, float)) or str(date).replace('.', '', 1).isdigit():
                                from datetime import timezone, timedelta
                                when = datetime.fromtimestamp(float(date) / 1000, timezone(timedelta(hours=-3))).replace(tzinfo=None)
                            else:
                                when = None
                                for pattern in ('%d/%m/%y %H:%M:%S', '%d/%m/%Y %H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S'):
                                    try:
                                        when = datetime.strptime(str(date).strip(), pattern)
                                        break
                                    except ValueError:
                                        pass
                                if when is None:
                                    raise ValueError()
                        except (ValueError, TypeError, OverflowError, OSError):
                            skipped += 1
                            continue
                        records.append(Record(str(value('number') if value('number') is not None else index), when,
                                              _number(str(value('temperature'))), _flag(str(value('door'))),
                                              _flag(str(value('alarm'))), *(_number(str(value(key))) for key in ('setpoint', 'defrost', 'outlet', 'battery'))))
                    if records:
                        name = re.sub(r'_\d+$', '', Path(filename).stem)
                        return Datalogger(name, tuple(sorted(records, key=lambda record: record.when)), skipped, 1.)
            finally:
                connection.close()
    except sqlite3.Error as error:
        raise ValueError('Não foi possível ler os registros deste arquivo DB. Extraia os dados novamente no equipamento.') from error
    raise ValueError('Nenhuma tabela com data, hora e temperatura principal foi encontrada neste arquivo.')


def parse_file(raw: bytes, filename: str) -> Datalogger:
    if raw.startswith(b'SQLite format 3\x00'):
        return parse_database(raw, filename)
    if Path(filename).suffix.casefold() in ('.db', '.sqlite', '.sqlite3'):
        raise ValueError('O arquivo DB está incompleto ou não tem um formato reconhecido.')
    return parse_txt(raw)


def reduce_points(records: list[Record], maximum: int) -> list[Record]:
    """Preserva os extremos de cada intervalo ao reduzir o desenho do gráfico."""
    if len(records) <= maximum:
        return records
    bucket_size = max(1, math.ceil(len(records) / max(1, (maximum - 2) // 2)))
    selected = {0, len(records) - 1}
    for start in range(0, len(records), bucket_size):
        indexes = range(start, min(start + bucket_size, len(records)))
        valid = [i for i in indexes if records[i].temperature is not None]
        if valid:
            selected.add(min(valid, key=lambda i: records[i].temperature))
            selected.add(max(valid, key=lambda i: records[i].temperature))
    return [records[i] for i in sorted(selected)]
