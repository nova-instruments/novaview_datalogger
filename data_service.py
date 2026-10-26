"""Operações de arquivo e preparação dos dados para o desktop."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
import re
import math
import warnings

import pandas as pd

import datalogger_core as core


def detect_equipment_profile(frame: pd.DataFrame) -> str | None:
    """Usa a mediana de todo o arquivo para reduzir o efeito de picos isolados."""
    temperatures = pd.to_numeric(frame.get('Tprincipal', pd.Series(dtype=float)), errors='coerce')
    temperatures = temperatures.loc[temperatures.abs().lt(float('inf'))].dropna()
    if temperatures.empty:
        return None
    return 'freezer' if temperatures.median() <= -10 else 'cold_chamber'


@dataclass
class Dataset:
    frame: pd.DataFrame
    source_name: str
    source_label: str
    low_limit: float
    is_txt: bool = False
    notices: list[str] = field(default_factory=list)
    high_limit: float = core.TEMP_HIGH_ALARM_LIMIT
    base_low_limit: float | None = None
    calculated_alarm: bool = False
    equipment_profile: str = 'cold_chamber'

    def with_equipment_profile(self, profile: str) -> Dataset:
        base_low = self.low_limit if self.base_low_limit is None else self.base_low_limit
        if profile == 'auto':
            profile = detect_equipment_profile(self.frame) or 'cold_chamber'
        if profile == 'freezer':
            low, high = -45., -15.
        elif profile == 'cold_chamber':
            low, high = base_low, core.TEMP_HIGH_ALARM_LIMIT
        else:
            raise ValueError('Tipo de equipamento inválido.')
        frame = self.frame
        if self.calculated_alarm:
            frame = core.apply_alarm_rules(frame.drop(columns='Alarme'), high_limit=high, low_limit=low)
        return replace(self, frame=frame, low_limit=low, high_limit=high,
                       base_low_limit=base_low, equipment_profile=profile)

    @property
    def serial_number(self) -> str:
        aliases = {'serial', 'serialnumber', 'serialno', 'sn', 'numerodeserie', 'númerodesérie'}
        for column in self.frame.columns:
            key = re.sub(r'[\s_\-]+', '', str(column)).casefold()
            if key in aliases:
                values = self.frame[column].dropna().astype(str).str.strip()
                values = values[~values.isin(['', '-'])].unique()
                if len(values) == 1:
                    return str(values[0])
                if len(values) > 1:
                    return 'Múltiplos equipamentos'
        # TXT identifica o equipamento no NAME; DB/IHM usam o nome do arquivo.
        # O sufixo _0, _1... dos bancos IHM não faz parte do número de série.
        for value in (self.source_label if self.is_txt else '', self.source_name):
            matches = re.findall(r'(?<![A-Z0-9])([A-Z]{2,}\d+(?:-\d+)?)(?![A-Z0-9])', value, re.IGNORECASE)
            if matches:
                return matches[-1]
        return 'Não informado'


def load_dataset(path: str, folder: bool = False) -> Dataset:
    source = Path(path)
    if not source.exists() or (not folder and not source.is_file()):
        raise ValueError('O arquivo ou pasta selecionado não existe mais.')
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        if folder:
            paths = core.list_ihm_db_files(source)
            if not paths:
                raise ValueError('Nenhum banco .db encontrado na pasta selecionada.')
            tables = core.list_tables_from_many_databases(tuple(map(str, paths)))
            if not tables:
                raise ValueError('Não encontramos tabelas nos bancos selecionados.')
            table = 'DataGrpData' if 'DataGrpData' in tables else tables[0]
            raw = core.read_table_from_many_databases(tuple(map(str, paths)), table)
            frame = core.apply_alarm_rules(core.normalize_dataframe(raw), low_limit=core.TEMP_LOW_ALARM_LIMIT_TXT)
            banks = [core.parse_chunk_index_from_stem(p.stem) + 1 for p in paths]
            label = str(min(banks)) if min(banks) == max(banks) else f'{min(banks)}–{max(banks)}'
            name = paths[0].stem.rsplit('_', 1)[0]
            dataset = Dataset(frame, name, label, core.TEMP_LOW_ALARM_LIMIT_TXT,
                              calculated_alarm='Alarme' not in core.canonicalize_columns(raw).columns)
        elif source.suffix.lower() == '.txt':
            raw, name = core.parse_datalogger_txt(str(source))
            dataset = Dataset(core.normalize_dataframe(raw), source.name, name, core.TEMP_LOW_ALARM_LIMIT_TXT, True,
                              calculated_alarm=raw.attrs.get('calculated_alarm', False))
        elif source.suffix.lower() in {'.db', '.sqlite', '.sqlite3'}:
            tables = core.list_tables(str(source))
            if not tables:
                raise ValueError('Não encontramos tabelas neste banco.')
            table = 'DataGrpData' if 'DataGrpData' in tables else tables[0]
            dataset = Dataset(core.normalize_dataframe(core.read_table(str(source), table)), source.name, '-', core.TEMP_LOW_ALARM_LIMIT)
        else:
            raise ValueError('Selecione um arquivo DB, SQLite ou TXT.')
        dataset.notices = [str(w.message) for w in caught]
    if dataset.frame.empty:
        raise ValueError('A origem selecionada está sem registros válidos.')
    time_col = core.get_main_time_column(dataset.frame)
    if time_col:
        dataset.frame = dataset.frame.sort_values(time_col, kind='stable', na_position='first').reset_index(drop=True)
    return dataset


def search_dataframe(frame: pd.DataFrame, text: str) -> pd.DataFrame:
    if not text:
        return frame
    matches = pd.Series(False, index=frame.index)
    for column in frame.columns:
        matches |= frame[column].astype(str).str.contains(text, case=False, na=False, regex=False)
    return frame.loc[matches]


ALARM_FILTER_OPTIONS = {
    'Todos os registros': 'all',
    'Sem alarme': 'none',
    'Qualquer alarme ativo': 'any',
    'Alta temperatura': 'high',
    'Baixa temperatura': 'low',
    'Porta aberta': 'door',
    'Alarme sem classificação': 'generic',
}


def parse_temperature_bound(text: str) -> float | None:
    if not text.strip():
        return None
    try:
        value = float(text.strip().replace(',', '.'))
    except ValueError:
        raise ValueError('Informe uma temperatura válida, como -5,5 ou 8.0.') from None
    if not math.isfinite(value):
        raise ValueError('A temperatura precisa ser um número finito.')
    return value


def filter_records(frame: pd.DataFrame, text: str = '', alarm_type: str = 'all',
                   minimum: float | None = None, maximum: float | None = None,
                   low_limit: float = core.TEMP_LOW_ALARM_LIMIT,
                   high_limit: float = core.TEMP_HIGH_ALARM_LIMIT) -> pd.DataFrame:
    """Combina busca, classificação de alarme e limites inclusivos de Tprincipal."""
    if minimum is not None and maximum is not None and minimum > maximum:
        raise ValueError('A temperatura mínima precisa ser menor ou igual à máxima.')
    if alarm_type not in ALARM_FILTER_OPTIONS.values():
        raise ValueError('Tipo de alarme inválido.')
    temperatures = pd.to_numeric(frame.get('Tprincipal', pd.Series(index=frame.index, dtype=float)), errors='coerce')
    kinds = core.record_alarm_kinds(frame, high_limit=high_limit, low_limit=low_limit)
    active = kinds.isin(core.ALARM_LABELS)
    mask = pd.Series(True, index=frame.index)
    if alarm_type == 'any':
        mask &= active
    elif alarm_type == 'high':
        mask &= temperatures.gt(high_limit)
    elif alarm_type == 'low':
        mask &= temperatures.lt(low_limit)
    elif alarm_type != 'all':
        mask &= kinds.eq(alarm_type)
    if minimum is not None:
        mask &= temperatures.ge(minimum)
    if maximum is not None:
        mask &= temperatures.le(maximum)
    selected = frame.loc[mask].copy()
    labels = {**core.ALARM_LABELS, 'none': 'Sem alarme', 'unknown': 'Sem informação de alarme'}
    selected['Tipo de alarme'] = kinds.loc[mask].map(labels)
    return search_dataframe(core.prepare_display_dataframe(selected), text)


def alarm_history(frame: pd.DataFrame, low_limit: float,
                  high_limit: float = core.TEMP_HIGH_ALARM_LIMIT) -> tuple[pd.DataFrame, list[int]]:
    kinds = core.record_alarm_kinds(frame, high_limit=high_limit, low_limit=low_limit)
    active = frame.loc[kinds.isin(core.ALARM_LABELS)].copy()
    temperatures = pd.to_numeric(active.get('Tprincipal', pd.Series(index=active.index, dtype=float)), errors='coerce')
    counts = [len(active), int((temperatures > high_limit).sum()), int((temperatures < low_limit).sum()), int(kinds.eq('door').sum())]
    active['Tipo'] = kinds.loc[active.index].map(core.ALARM_LABELS)
    display = core.prepare_display_dataframe(active.iloc[::-1])
    return display, counts
