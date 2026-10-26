"""Estado da interface Android, leitura somente e consultas paginadas."""
from bisect import bisect_left, bisect_right
from datetime import datetime
import math
import unicodedata
from PySide6.QtCore import QObject, Property, Signal, Slot, QUrl, QFile, QFileInfo, QIODevice, QThread
from datalogger import MAX_BYTES, parse_file, reduce_points

PAGE_SIZE = 50


def read_file(url):
    filename = url.toLocalFile() if url.isLocalFile() else url.toString()
    source = url.fileName() or 'Arquivo selecionado'
    file = QFile(filename)
    if not file.open(QIODevice.OpenModeFlag.ReadOnly):
        raise ValueError('Não foi possível abrir o arquivo. Selecione-o novamente e confira o acesso ao pendrive.')
    try:
        source = QFileInfo(file).fileName() or source
        raw = bytes(file.read(MAX_BYTES + 1))
        if file.error() != QFile.FileError.NoError:
            raise ValueError('A leitura foi interrompida. Reconecte o pendrive e selecione o arquivo novamente.')
        return parse_file(raw, source), source
    finally:
        file.close()


class FileLoader(QThread):
    loaded = Signal(object, str)
    failed = Signal(str)

    def __init__(self, url, parent):
        super().__init__(parent)
        self.url = QUrl(url)

    def run(self):
        try:
            dataset, source = read_file(self.url)
            self.loaded.emit(dataset, source)
        except Exception as error:
            self.failed.emit(str(error) or 'Não foi possível ler este arquivo.')


def folded(text):
    return ''.join(c for c in unicodedata.normalize('NFD', str(text).casefold()) if not unicodedata.combining(c))


def temperature_bound(text):
    if not text.strip():
        return None
    try:
        number = float(text.strip().replace(',', '.'))
        if math.isfinite(number):
            return number
    except ValueError:
        pass
    raise ValueError('Informe uma temperatura válida, como -30 ou 8,5.')


class Controller(QObject):
    changed = Signal()
    rowsChanged = Signal()
    busyChanged = Signal()
    fileChanged = Signal()
    error = Signal(str)

    def __init__(self):
        super().__init__()
        self.dataset = None
        self.profile = 'auto'
        self._times = []
        self._source = ''
        self._period = (0., 1.)
        self._busy = False
        self._loader = None
        self._rows = {'data': [], 'alarms': []}
        self._pages = {'data': 0, 'alarms': 0}
        self._filters = {key: self.default_filters(key) for key in self._rows}
        self._summary = {'loaded': False, 'source': '', 'serial': '', 'count': 0, 'periodCount': 0,
                         'start': 0., 'end': 1., 'equipment': '', 'limits': '', 'notice': ''}

    @staticmethod
    def default_filters(tab):
        return {'search': '', 'kind': 'any' if tab == 'alarms' else 'all',
                'minimum': None, 'maximum': None, 'descending': True}

    @Property(bool, notify=busyChanged)
    def busy(self):
        return self._busy

    @Property('QVariantMap', notify=changed)
    def summary(self):
        return self._summary

    @Property(str, notify=changed)
    def profileValue(self):
        return self.profile

    @Property('QVariantList', notify=changed)
    def availableDays(self):
        if not self.dataset:
            return []
        return [{'label': date.strftime('%d/%m/%Y'), 'year': date.year, 'month': date.month,
                 'day': date.day} for date in sorted({r.when.date() for r in self.dataset.records})]

    def _period_records(self):
        if not self.dataset:
            return ()
        return self.dataset.records[bisect_left(self._times, self._period[0]):bisect_right(self._times, self._period[1])]

    def _refresh(self):
        if not self.dataset:
            return
        data = self.dataset
        low, high = data.limits(self.profile)
        effective = data.detected_profile if self.profile == 'auto' else self.profile
        name = 'Freezer −30 °C' if effective == 'freezer' else 'Câmara Fria'
        if effective is None:
            name = 'Não identificado — selecione o tipo'
        elif self.profile == 'auto':
            name = 'Identificado: ' + name
        records = self._period_records()
        temperatures = [r.temperature for r in records if r.temperature is not None]
        setpoints = [r.setpoint for r in records if r.setpoint is not None]
        counts = dict.fromkeys(('total', 'high', 'low', 'door'), 0)
        for record in records:
            flags = record.flags(low, high)
            for key in counts:
                counts[key] += int(flags['any' if key == 'total' else key])
        label = lambda value: datetime.fromtimestamp(value / 1000).strftime('%d/%m/%Y %H:%M:%S')
        self._summary = {'loaded': True, 'source': self._source, 'serial': data.name,
            'count': len(data.records), 'periodCount': len(records), 'start': self._period[0], 'end': self._period[1],
            'fullStart': self._times[0], 'fullEnd': self._times[-1],
            'startLabel': label(self._times[0]), 'endLabel': label(self._times[-1]),
            'periodStartLabel': label(self._period[0]), 'periodEndLabel': label(self._period[1]),
            'equipment': name, 'low': low, 'high': high, 'counts': counts,
            'average': sum(temperatures) / len(temperatures) if temperatures else None,
            'minimum': min(temperatures) if temperatures else None,
            'maximum': max(temperatures) if temperatures else None,
            'setpointAverage': sum(setpoints) / len(setpoints) if setpoints else None,
            'hasSetpoint': bool(setpoints),
            'limits': f'Alertas abaixo de {low:g} °C e acima de {high:g} °C',
            'notice': f'{data.skipped} linha(s) com formato/data inválidos foram ignoradas.' if data.skipped else ''}
        self._update_rows()
        self.changed.emit()

    @Slot(object, str)
    def _accept(self, dataset, source):
        self.dataset = dataset
        self._times = [record.timestamp for record in dataset.records]
        self._source = source
        self._period = (self._times[0], self._times[-1])
        self.profile = 'auto'
        self._filters = {key: self.default_filters(key) for key in self._rows}
        self._refresh()
        self.fileChanged.emit()

    @Slot(QUrl)
    def openFile(self, url):
        try:
            self._accept(*read_file(url))
        except Exception as error:
            self.error.emit(str(error) or 'Não foi possível ler este arquivo.')

    @Slot(QUrl)
    def startOpenFile(self, url):
        if self._busy or not url.isValid() or url.isEmpty():
            return
        self._busy = True
        self.busyChanged.emit()
        loader = FileLoader(url, self)
        self._loader = loader
        loader.loaded.connect(self._accept)
        loader.failed.connect(self.error)
        loader.finished.connect(self._finished)
        loader.start()

    @Slot()
    def _finished(self):
        loader = self._loader
        self._loader = None
        self._busy = False
        self.busyChanged.emit()
        if loader:
            loader.deleteLater()

    @Slot()
    def shutdown(self):
        if self._loader:
            self._loader.wait()

    def _read(self, filename, source):
        try:
            dataset, _ = read_file(QUrl.fromLocalFile(filename))
            self._accept(dataset, source)
            return True
        except Exception as error:
            self.error.emit(str(error))
            return False

    @Slot(str)
    def setProfile(self, profile):
        if profile in ('auto', 'cold_chamber', 'freezer'):
            self.profile = profile
            self._refresh()

    @Slot(float, float, result=bool)
    def setPeriod(self, start, end):
        if not self.dataset:
            return False
        if not all(math.isfinite(v) for v in (start, end)) or start > end:
            self.error.emit('O início precisa ser anterior ou igual ao fim do período.')
            return False
        if start < self._times[0] or end > self._times[-1]:
            self.error.emit('Escolha datas e horários dentro do período do datalogger.')
            return False
        self._period = (start, end)
        self._refresh()
        return True

    @Slot()
    def resetPeriod(self):
        if self.dataset:
            self.setPeriod(self._times[0], self._times[-1])

    @Slot(float, float, int, result='QVariantList')
    def plotPoints(self, start, end, pixels):
        if not self.dataset:
            return []
        left = max(bisect_left(self._times, self._period[0]), bisect_left(self._times, start) - 1)
        right = min(bisect_right(self._times, self._period[1]), bisect_right(self._times, end) + 1)
        records = reduce_points(list(self.dataset.records[left:right]), max(50, min(2000, pixels * 2)))
        return [{'x': r.timestamp, 'y': r.temperature, 'setpoint': r.setpoint, 'door': r.door} for r in records]

    @Slot(float, result='QVariantMap')
    def recordAt(self, timestamp):
        records = self._period_records()
        if not records:
            return {}
        start = bisect_left(self._times, self._period[0])
        index = min(start + len(records) - 1, max(start, bisect_left(self._times, timestamp)))
        if index > start and abs(self._times[index - 1] - timestamp) <= abs(self._times[index] - timestamp):
            index -= 1
        return self.dataset.records[index].as_dict(*self.dataset.limits(self.profile))

    @Slot(int, result='QVariantList')
    def recentAlarms(self, maximum=40):
        if not self.dataset:
            return []
        low, high = self.dataset.limits(self.profile)
        return [r.as_dict(low, high) for r in reversed(self._period_records()) if r.flags(low, high)['any']][:min(100, max(1, maximum))]

    def _update_rows(self, tab=None):
        if not self.dataset:
            return
        low, high = self.dataset.limits(self.profile)
        records = self._period_records()
        for key in ([tab] if tab else self._rows):
            filters = self._filters[key]
            matched = []
            for record in records:
                flags = record.flags(low, high)
                if key == 'alarms' and not flags['any']:
                    continue
                kind = filters['kind']
                if kind == 'none' and (flags['any'] or record.controller_alarm is None):
                    continue
                if kind not in ('all', 'none') and not flags[kind]:
                    continue
                if any(bound is not None for bound in (filters['minimum'], filters['maximum'])):
                    if record.temperature is None:
                        continue
                    if filters['minimum'] is not None and record.temperature < filters['minimum']:
                        continue
                    if filters['maximum'] is not None and record.temperature > filters['maximum']:
                        continue
                if filters['search']:
                    text = ' '.join(str(value) for value in record.as_dict(low, high).values())
                    if folded(filters['search']) not in folded(text):
                        continue
                matched.append(record)
            if filters['descending']:
                matched.reverse()
            self._rows[key] = matched
            self._pages[key] = 0
        self.rowsChanged.emit()

    @Slot(str, str, str, str, str, bool, result=bool)
    def setFilters(self, tab, search, kind, minimum, maximum, descending):
        if tab not in self._rows or kind not in ('all', 'none', 'any', 'high', 'low', 'door', 'generic'):
            return False
        try:
            low, high = temperature_bound(minimum), temperature_bound(maximum)
            if low is not None and high is not None and low > high:
                raise ValueError('A temperatura mínima precisa ser menor ou igual à máxima.')
        except ValueError as error:
            self.error.emit(str(error))
            return False
        self._filters[tab] = {'search': search.strip(), 'kind': kind, 'minimum': low,
                              'maximum': high, 'descending': descending}
        self._update_rows(tab)
        return True

    @Slot(str)
    def resetFilters(self, tab):
        if tab in self._rows:
            self._filters[tab] = self.default_filters(tab)
            self._update_rows(tab)

    def _page(self, tab):
        rows, page = self._rows[tab], self._pages[tab]
        low, high = self.dataset.limits(self.profile) if self.dataset else (2, 8)
        return {'rows': [r.as_dict(low, high) for r in rows[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]],
                'total': len(rows), 'page': page, 'pages': max(1, math.ceil(len(rows) / PAGE_SIZE)),
                'first': page * PAGE_SIZE + 1 if rows else 0,
                'last': min(len(rows), (page + 1) * PAGE_SIZE)}

    @Property('QVariantMap', notify=rowsChanged)
    def dataPage(self):
        return self._page('data')

    @Property('QVariantMap', notify=rowsChanged)
    def alarmPage(self):
        return self._page('alarms')

    @Slot(str, int)
    def setPage(self, tab, page):
        if tab in self._pages:
            self._pages[tab] = max(0, min(max(0, math.ceil(len(self._rows[tab]) / PAGE_SIZE) - 1), page))
            self.rowsChanged.emit()
