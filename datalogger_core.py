"""Leitura, normalização e relatórios, independentes da interface gráfica."""
from __future__ import annotations
import warnings
from contextlib import closing


import os

import re

import sqlite3

import sys

import string

from io import BytesIO

from pathlib import Path

import pandas as pd

from reportlab.lib import colors

from reportlab.lib.pagesizes import A4

from reportlab.lib.styles import getSampleStyleSheet

from reportlab.lib.units import cm

from reportlab.graphics.shapes import Drawing, Line, PolyLine, Rect, String

from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

def _get_app_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return Path(__file__).resolve().parent

def _get_data_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        local_appdata = os.environ.get("LOCALAPPDATA")
        base_dir = Path(local_appdata) / "NovaView" if local_appdata else Path.home() / ".novaview"
    else:
        base_dir = Path(__file__).resolve().parent
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir

APP_BASE_DIR = _get_app_base_dir()

DATA_BASE_DIR = _get_data_base_dir()

TEMP_DIR = DATA_BASE_DIR / "temp"

TIMEZONE = "America/Sao_Paulo"

LOGO_PATH = APP_BASE_DIR / "img" / "novaview_datalogger_logo.png"

TEMP_HIGH_ALARM_LIMIT = 8

TEMP_LOW_ALARM_LIMIT = 1

TEMP_LOW_ALARM_LIMIT_TXT = 2

RAW_TIME_COLUMNS = ["CollectTime", "StartTime", "EndTime", "Timestamp", "Time"]

DISPLAY_TIME_COLUMNS = {
    "CollectTime_dt": "Data e hora",
    "StartTime_dt": "Início",
    "EndTime_dt": "Fim",
    "Timestamp_dt": "Data e hora",
    "Time_dt": "Data e hora",
}

CANONICAL_MEASUREMENT_COLUMNS = [
    "Tprincipal", "Degelo", "Setpoint", "Tomada", "Bateria", "Alarme", "Porta",
]

COLUMN_ALIASES = {
    "Tprincipal": ["tprincipal", "t principal", "temp principal", "temperatura principal"],
    "Degelo": ["degelo", "tdegelo", "t degelo", "temp degelo"],
    "Setpoint": ["setpoint", "set point", "set-point", "sp"],
    "Tomada": ["tomada", "ttomada", "t tomada", "temp tomada"],
    "Bateria": ["bateria", "vbateria", "tensao bateria"],
    "Alarme": ["alarme", "al"],
    "Porta": ["porta", "pa"],
}

DATA_RANGE_OPTIONS: dict[str, int | None] = {
    "1 dia": 1,
    "7 dias": 7,
    "15 dias": 15,
    "30 dias": 30,
    "Completo": None,
}

def canonicalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    lookup: dict[str, str] = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in (canonical, *aliases):
            lookup[alias.strip().lower()] = canonical

    rename: dict[str, str] = {}
    claimed: set[str] = set()
    for col in df.columns:
        canonical = lookup.get(str(col).strip().lower())
        if (
            canonical
            and canonical != col
            and canonical not in df.columns
            and canonical not in claimed
        ):
            rename[col] = canonical
            claimed.add(canonical)

    return df.rename(columns=rename) if rename else df

def parse_chunk_index_from_stem(stem: str) -> int:
    if "_" not in stem:
        return 0
    tail = stem.rsplit("_", 1)[-1]
    return int(tail) if tail.isdigit() else 0

def resolve_ihm_datalog_dir(base_path: str | Path) -> Path:
    root = Path(base_path).expanduser().resolve()
    data_log_dir = root / "DataLogFile"
    if data_log_dir.exists() and data_log_dir.is_dir():
        return data_log_dir
    return root

def list_ihm_db_files(base_path: str | Path) -> list[Path]:
    data_log_dir = resolve_ihm_datalog_dir(base_path)
    if not data_log_dir.exists() or not data_log_dir.is_dir():
        return []

    db_files = [
        p for p in data_log_dir.rglob("*.db")
        if p.is_file()
    ]
    db_files.sort(key=lambda p: (str(p.parent), parse_chunk_index_from_stem(p.stem), p.name.lower()))
    return db_files

def list_removable_drive_candidates() -> list[Path]:
    candidates: list[Path] = []

    if os.name == "nt":
        for letter in string.ascii_uppercase:
            drive = Path(f"{letter}:/")
            if drive.exists() and drive.is_dir():
                candidates.append(drive)
    else:
        def safe_list_dirs(base: Path) -> list[Path]:
            try:
                entries = list(base.iterdir())
            except (PermissionError, OSError):
                return []
            out: list[Path] = []
            for e in entries:
                try:
                    if e.is_dir():
                        out.append(e)
                except (PermissionError, OSError):
                    continue
            return out

        for root in [Path("/media"), Path("/run/media"), Path("/Volumes"), Path("/mnt")]:
            try:
                if not root.exists() or not root.is_dir():
                    continue
            except (PermissionError, OSError):
                continue
            # Busca rasa e segura: somente pontos de montagem prováveis
            # Ex.: /media/<user>/<label>, /run/media/<user>/<label>, /mnt/<label>
            first_level = safe_list_dirs(root)
            candidates.extend(first_level)
            for level1 in first_level:
                candidates.extend(safe_list_dirs(level1))

    unique: list[Path] = []
    seen = set()
    for p in candidates:
        try:
            key = str(p.resolve())
        except (PermissionError, OSError):
            continue
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique

def discover_ihm_root_from_removable() -> list[tuple[Path, Path]]:
    matches: list[tuple[Path, Path]] = []
    for mount in list_removable_drive_candidates():
        data_log_dir = mount / "DataLogFile"
        if data_log_dir.exists() and data_log_dir.is_dir():
            matches.append((mount, data_log_dir))
    return matches

def normalize_time_fragment(time_fragment: str) -> str:
    parts = [p.strip() for p in str(time_fragment).split(":")]
    if len(parts) != 3:
        return str(time_fragment).strip()
    hh, mm, ss = parts
    return f"{hh.zfill(2)}:{mm.zfill(2)}:{ss.zfill(2)}"

def parse_datalogger_txt(txt_path: str) -> tuple[pd.DataFrame, str]:
    text = Path(txt_path).read_text(encoding="utf-8", errors="replace")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        raise ValueError("Arquivo TXT vazio.")

    name_value = "-"
    rows_start = 0
    if lines[0].upper().startswith("NAME:"):
        name_value = lines[0][len("NAME:"):].strip() or "-"
        rows_start = 1

    if len(lines) <= rows_start:
        raise ValueError("Cabeçalho de dados não encontrado no TXT.")

    header_line = lines[rows_start]
    data_lines = lines[rows_start + 1:]
    if not data_lines:
        raise ValueError("Não há linhas de dados no TXT.")

    csv_buffer = "\n".join([header_line] + data_lines)
    df = pd.read_csv(
        BytesIO(csv_buffer.encode("utf-8")),
        sep=";",
        dtype=str,
    )
    df.columns = [col.strip() for col in df.columns]

    rename_map = {
        "R": "Registro",
        "Data Hora": "Time",
        "TPrincipal": "Tprincipal",
        "PA": "Porta",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

    if "Time" in df.columns:
        normalized_time_values = []
        for raw_value in df["Time"].fillna("").astype(str):
            cleaned = raw_value.strip()
            if not cleaned:
                normalized_time_values.append(cleaned)
                continue
            parts = cleaned.split()
            if len(parts) >= 2:
                date_part = parts[0]
                time_part = normalize_time_fragment(parts[1])
                normalized_time_values.append(f"{date_part} {time_part}")
            else:
                normalized_time_values.append(cleaned)
        df["Time"] = normalized_time_values

    for col in ["Registro", "Porta", "Tprincipal"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df.attrs['calculated_alarm'] = 'Alarme' not in canonicalize_columns(df).columns
    df = apply_alarm_rules(df, high_limit=TEMP_HIGH_ALARM_LIMIT, low_limit=TEMP_LOW_ALARM_LIMIT_TXT)

    return df, name_value

def extract_txt_device_name(name_value: str, fallback: str = "arquivo") -> str:
    text = str(name_value or "").strip()
    if not text or text == "-":
        return fallback

    matches = re.findall(r"\b([A-Z]{2,}\d+(?:-\d+)?)\b", text)
    if matches:
        return matches[-1]

    base_name = Path(text.replace("\\", "/")).stem.strip()
    return base_name or fallback

def apply_alarm_rules(
    df: pd.DataFrame,
    high_limit: float = TEMP_HIGH_ALARM_LIMIT,
    low_limit: float = TEMP_LOW_ALARM_LIMIT,
) -> pd.DataFrame:
    # Al/Alarme é o estado lido do controlador. As condições locais só são
    # usadas para formatos antigos que não registram esse estado.
    out = canonicalize_columns(df).copy()
    if "Alarme" in out.columns:
        out["Alarme"] = pd.to_numeric(out["Alarme"], errors="coerce")
        return out
    porta_series = (
        pd.to_numeric(out["Porta"], errors="coerce").fillna(0)
        if "Porta" in out.columns
        else pd.Series(index=out.index, data=0, dtype="float64")
    )
    temp_series = (
        pd.to_numeric(out["Tprincipal"], errors="coerce")
        if "Tprincipal" in out.columns
        else pd.Series(index=out.index, data=float("nan"), dtype="float64")
    )
    alarm_mask = (
        (porta_series == 1)
        | (temp_series > high_limit)
        | (temp_series < low_limit)
    )
    out["Alarme"] = alarm_mask.astype(int)
    return out

def list_tables(db_path: str) -> list[str]:
    with closing(sqlite3.connect(Path(db_path).resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    return [row[0] for row in rows if not row[0].startswith("sqlite_")]

def read_table(db_path: str, table_name: str) -> pd.DataFrame:
    with closing(sqlite3.connect(Path(db_path).resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        return pd.read_sql_query('SELECT * FROM "' + table_name.replace('"', '""') + '"', conn)

def list_tables_from_many_databases(db_paths: tuple[str, ...]) -> list[str]:
    table_names: set[str] = set()
    failed_names: list[str] = []
    for db_path in db_paths:
        try:
            table_names.update(list_tables(db_path))
        except Exception:
            failed_names.append(Path(db_path).name)
    if failed_names:
        warnings.warn(
            f"Não foi possível ler {len(failed_names)} arquivo(s) de banco de dados "
            f"(ignorado(s)): {', '.join(failed_names)}"
        )
    return sorted(table_names)

def read_table_from_many_databases(db_paths: tuple[str, ...], table_name: str) -> pd.DataFrame:
    chunks: list[pd.DataFrame] = []
    failed_names: list[str] = []
    for db_path in db_paths:
        try:
            chunk = read_table(db_path, table_name)
            if not chunk.empty:
                chunks.append(chunk)
        except Exception:
            failed_names.append(Path(db_path).name)
    if failed_names:
        warnings.warn(
            f"Não foi possível ler {len(failed_names)} arquivo(s) de banco de dados "
            f"(dados parciais): {', '.join(failed_names)}"
        )

    if not chunks:
        return pd.DataFrame()
    return pd.concat(chunks, ignore_index=True, sort=False)

def normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    # Uniformiza os nomes das colunas de medicao entre DB, TXT e pasta IHM para
    # que painel, tabela, Excel e PDF encontrem sempre as mesmas variaveis.
    out = canonicalize_columns(out)

    # Detecta e converte colunas de tempo comuns
    for col in RAW_TIME_COLUMNS:
        if col in out.columns:
            if col == "Time":
                try:
                    out[col + "_dt"] = pd.to_datetime(
                        out[col],
                        format="%d/%m/%y %H:%M:%S",
                        errors="coerce",
                    )
                    continue
                except Exception:
                    pass
            try:
                out[col + "_dt"] = (
                    pd.to_datetime(out[col], unit="ms", utc=True)
                    .dt.tz_convert(TIMEZONE)
                    .dt.tz_localize(None)
                )
            except Exception:
                try:
                    out[col + "_dt"] = pd.to_datetime(out[col], errors="coerce", dayfirst=True)
                except Exception:
                    pass

    return out

def coerce_float(value, default: float = float("nan")) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return default if pd.isna(result) else result

def format_metric(value) -> str:
    if pd.isna(value):
        return "-"
    if isinstance(value, (int, float)):
        return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return str(value)

def format_datetime(value) -> str:
    if pd.isna(value):
        return "-"
    if hasattr(value, "strftime"):
        return value.strftime("%d/%m/%Y %H:%M:%S")
    return str(value)

def truncate_text(value: str, max_len: int = 18) -> str:
    text = str(value or "").strip()
    if len(text) <= max_len:
        return text
    return f"{text[:max_len - 3]}..."

def get_main_time_column(df: pd.DataFrame) -> str | None:
    for col in ["CollectTime_dt", "StartTime_dt", "EndTime_dt", "Timestamp_dt", "Time_dt"]:
        if col in df.columns and df[col].notna().any():
            return col
    return None

def get_preferred_plot_columns(df: pd.DataFrame, is_txt_source: bool = False) -> list[str]:
    preferred_cols = ["Tprincipal", "Setpoint"]
    ignored_plot_columns = {"indexid", "index", "registro", "r", "rowid"}
    if is_txt_source:
        ignored_plot_columns.add("alarme")
    numeric_cols = [
        col for col in df.select_dtypes(include="number").columns
        if (
            not col.endswith("_dt")
            and col not in RAW_TIME_COLUMNS
            and col.strip().lower() not in ignored_plot_columns
        )
    ]
    ordered = [col for col in preferred_cols if col in numeric_cols]
    ordered.extend(col for col in numeric_cols if col not in ordered)
    return ordered

def prepare_display_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    display_df = df.copy()

    for raw_col in RAW_TIME_COLUMNS:
        converted_col = f"{raw_col}_dt"
        if raw_col in display_df.columns and converted_col in display_df.columns:
            display_df = display_df.drop(columns=[raw_col])

    display_df = display_df.rename(
        columns={
            **DISPLAY_TIME_COLUMNS,
            "IndexID": "indexID",
            "Setpoint": "setpoint",
            "Alarme": "alarme",
            "Porta": "porta",
        }
    )

    preferred_order = [
        "indexID", "Data e hora", "Tprincipal", "Degelo", "setpoint", "Tomada", "Bateria", "alarme", "porta",
    ]
    ordered_cols = [col for col in preferred_order if col in display_df.columns]
    ordered_cols.extend(col for col in display_df.columns if col not in ordered_cols)
    return display_df.loc[:, ordered_cols]

def filter_by_period(
    df: pd.DataFrame,
    start_date,
    start_time,
    end_date,
    end_time,
) -> pd.DataFrame:
    time_col = get_main_time_column(df)
    if not time_col:
        return df

    if start_date is None or start_time is None or end_date is None or end_time is None:
        return df

    start_dt = pd.Timestamp.combine(start_date, start_time)
    end_dt = pd.Timestamp.combine(end_date, end_time)
    if start_dt > end_dt:
        warnings.warn("A data/hora inicial precisa ser menor que a data/hora final.")
        return df.iloc[0:0]

    # end_time só tem precisão de segundos (widget de hora), mas os timestamps dos
    # dataloggers têm precisão de milissegundos. Um limite "<=" exato no segundo
    # descartaria qualquer leitura com fração de segundo naquele instante — por
    # isso o limite superior é exclusivo no início do próximo segundo.
    end_dt_exclusive = end_dt + pd.Timedelta(seconds=1)
    return df[(df[time_col] >= start_dt) & (df[time_col] < end_dt_exclusive)]

def get_data_range_bounds(
    df: pd.DataFrame,
    range_label: str,
) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    time_col = get_main_time_column(df)
    if not time_col or df.empty:
        return None, None

    period_end = pd.Timestamp(df[time_col].max())
    days = DATA_RANGE_OPTIONS.get(range_label)
    if days is None:
        period_start = pd.Timestamp(df[time_col].min())
    else:
        period_start = period_end - pd.Timedelta(days=days)
    return period_start, period_end

def filter_data_by_range(df: pd.DataFrame, range_label: str) -> pd.DataFrame:
    if range_label == "Completo":
        return df.copy()

    time_col = get_main_time_column(df)
    period_start, period_end = get_data_range_bounds(df, range_label)
    if not time_col or period_start is None or period_end is None:
        return df.copy()

    mask = (df[time_col] >= period_start) & (df[time_col] <= period_end)
    return df.loc[mask].copy()

def build_temperature_trend_areas(
    plot_df: pd.DataFrame,
    time_col: str,
    temperature_col: str,
) -> pd.DataFrame:
    trend_df = (
        plot_df[[time_col, temperature_col]]
        .dropna()
        .sort_values(time_col)
        .reset_index(drop=True)
    )

    if len(trend_df) < 2:
        return pd.DataFrame(columns=["DataHora", "Temperatura", "Area", "Segmento"])

    trend_df["Delta"] = trend_df[temperature_col].diff()
    trend_df["TrendRaw"] = trend_df["Delta"].apply(
        lambda value: "up" if value > 0 else ("down" if value < 0 else None)
    )

    if trend_df["TrendRaw"].dropna().empty:
        # Sem variação no período inteiro: divide em metade quente/metade fria.
        split_idx = len(trend_df) // 2
        if split_idx <= 0 or split_idx >= len(trend_df):
            return pd.DataFrame(columns=["DataHora", "Temperatura", "Area", "Segmento"])

        first_half = trend_df.iloc[: split_idx + 1].copy()
        second_half = trend_df.iloc[split_idx:].copy()
        first_half["Area"] = "Área quente"
        first_half["Segmento"] = "Área quente_1"
        second_half["Area"] = "Área fria"
        second_half["Segmento"] = "Área fria_1"

        return (
            pd.concat(
                [
                    first_half.rename(columns={time_col: "DataHora", temperature_col: "Temperatura"})[
                        ["DataHora", "Temperatura", "Area", "Segmento"]
                    ],
                    second_half.rename(columns={time_col: "DataHora", temperature_col: "Temperatura"})[
                        ["DataHora", "Temperatura", "Area", "Segmento"]
                    ],
                ],
                ignore_index=True,
            )
            .sort_values("DataHora")
            .reset_index(drop=True)
        )

    # Em cada trecho estável (delta=0), aplica divisão 50/50 (quente/fria).
    trend_df["Trend"] = trend_df["TrendRaw"].copy()
    stable_indices = [
        idx for idx in range(1, len(trend_df))
        if trend_df.loc[idx, "Trend"] is None
    ]
    run_start = None
    prev_idx = None
    stable_runs: list[tuple[int, int]] = []
    for idx in stable_indices:
        if run_start is None:
            run_start = idx
            prev_idx = idx
            continue
        if idx != prev_idx + 1:
            stable_runs.append((run_start, prev_idx))
            run_start = idx
        prev_idx = idx
    if run_start is not None:
        stable_runs.append((run_start, prev_idx))

    for start_idx, end_idx in stable_runs:
        run_len = end_idx - start_idx + 1
        split = run_len // 2
        for offset, idx in enumerate(range(start_idx, end_idx + 1)):
            trend_df.loc[idx, "Trend"] = "up" if offset < split else "down"

    points: list[dict[str, object]] = []
    active_trend = None
    segment_idx = 0

    for idx in range(1, len(trend_df)):
        current_trend = trend_df.loc[idx, "Trend"]
        if current_trend is None:
            continue

        if active_trend is None:
            active_trend = current_trend
            segment_idx += 1
        elif current_trend != active_trend:
            active_trend = current_trend
            segment_idx += 1

        area_name = "Área quente" if active_trend == "up" else "Área fria"
        segment_name = f"{area_name}_{segment_idx}"

        previous_point = trend_df.loc[idx - 1]
        current_point = trend_df.loc[idx]
        points.append(
            {
                "DataHora": previous_point[time_col],
                "Temperatura": previous_point[temperature_col],
                "Area": area_name,
                "Segmento": segment_name,
            }
        )
        points.append(
            {
                "DataHora": current_point[time_col],
                "Temperatura": current_point[temperature_col],
                "Area": area_name,
                "Segmento": segment_name,
            }
        )

    if not points:
        return pd.DataFrame(columns=["DataHora", "Temperatura", "Area", "Segmento"])

    return (
        pd.DataFrame(points)
        .drop_duplicates(subset=["DataHora", "Area", "Segmento"])
        .sort_values("DataHora")
        .reset_index(drop=True)
    )

def compute_temperature_segment_durations(
    plot_df: pd.DataFrame,
    time_col: str,
    temperature_col: str,
) -> pd.DataFrame:
    trend_df = (
        plot_df[[time_col, temperature_col]]
        .dropna()
        .sort_values(time_col)
        .reset_index(drop=True)
    )

    if len(trend_df) < 2:
        return pd.DataFrame(columns=["Area", "Inicio", "Fim", "DuracaoSegundos", "Segmento"])

    trend_df["Delta"] = trend_df[temperature_col].diff()
    trend_df["Trend"] = trend_df["Delta"].apply(
        lambda value: "up" if value > 0 else ("down" if value < 0 else None)
    )

    intervals: list[dict[str, object]] = []
    for idx in range(1, len(trend_df)):
        direction = trend_df.loc[idx, "Trend"]
        if direction is None:
            continue

        start_time = trend_df.loc[idx - 1, time_col]
        end_time = trend_df.loc[idx, time_col]
        if pd.isna(start_time) or pd.isna(end_time) or end_time <= start_time:
            continue

        intervals.append(
            {
                "Trend": direction,
                "Inicio": start_time,
                "Fim": end_time,
            }
        )

    if not intervals:
        return pd.DataFrame(columns=["Area", "Inicio", "Fim", "DuracaoSegundos", "Segmento"])

    segments: list[dict[str, object]] = []
    for interval in intervals:
        area = "Área quente" if interval["Trend"] == "up" else "Área fria"
        if not segments:
            segments.append(
                {
                    "Area": area,
                    "Trend": interval["Trend"],
                    "Inicio": interval["Inicio"],
                    "Fim": interval["Fim"],
                }
            )
            continue

        previous = segments[-1]
        if (
            previous["Trend"] == interval["Trend"]
            and interval["Inicio"] <= previous["Fim"]
        ):
            if interval["Fim"] > previous["Fim"]:
                previous["Fim"] = interval["Fim"]
        else:
            segments.append(
                {
                    "Area": area,
                    "Trend": interval["Trend"],
                    "Inicio": interval["Inicio"],
                    "Fim": interval["Fim"],
                }
            )

    if not segments:
        return pd.DataFrame(columns=["Area", "Inicio", "Fim", "DuracaoSegundos", "Segmento"])

    segment_count = {"Área quente": 0, "Área fria": 0}
    parsed_segments: list[dict[str, object]] = []
    for segment in segments:
        area = str(segment["Area"])
        start_time = segment["Inicio"]
        end_time = segment["Fim"]
        duration_seconds = float((end_time - start_time).total_seconds())
        if duration_seconds <= 0:
            continue

        segment_count[area] = segment_count.get(area, 0) + 1
        parsed_segments.append(
            {
                "Area": area,
                "Inicio": start_time,
                "Fim": end_time,
                "DuracaoSegundos": duration_seconds,
                "Segmento": f"{area} #{segment_count[area]}",
            }
        )

    if not parsed_segments:
        return pd.DataFrame(columns=["Area", "Inicio", "Fim", "DuracaoSegundos", "Segmento"])

    return pd.DataFrame(parsed_segments)

def format_duration(seconds: float) -> str:
    if pd.isna(seconds) or seconds <= 0:
        return "0s"

    total_seconds = int(round(float(seconds)))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)

    if hours > 0:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    if minutes > 0:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"

ALARM_GLYPHS = {
    "high": "▲",
    "low": "▼",
    "door": "◆",
    "generic": "●",
}

ALARM_LABELS = {
    "high": "Alarme de alta temperatura",
    "low": "Alarme de baixa temperatura",
    "door": "Alarme de porta aberta",
    "generic": "Alarme ativo (sem classificação)",
}

def alarm_kind(temperature, door, high_limit: float = TEMP_HIGH_ALARM_LIMIT, low_limit: float = TEMP_LOW_ALARM_LIMIT) -> str:
    if door == 1:
        return "door"
    if pd.notna(temperature) and temperature > high_limit:
        return "high"
    if pd.notna(temperature) and temperature < low_limit:
        return "low"
    return "generic"

def classify_alarm(temperature, door, high_limit: float = TEMP_HIGH_ALARM_LIMIT, low_limit: float = TEMP_LOW_ALARM_LIMIT) -> str:
    return ALARM_LABELS[alarm_kind(temperature, door, high_limit=high_limit, low_limit=low_limit)]


def record_alarm_kinds(df: pd.DataFrame, high_limit: float = TEMP_HIGH_ALARM_LIMIT,
                       low_limit: float = TEMP_LOW_ALARM_LIMIT) -> pd.Series:
    """Condições térmicas independem da confirmação Al; porta mantém a regra anterior."""
    temperatures = pd.to_numeric(df.get("Tprincipal", pd.Series(index=df.index, dtype=float)), errors="coerce")
    doors = pd.to_numeric(df.get("Porta", pd.Series(index=df.index, dtype=float)), errors="coerce")
    alarms = pd.to_numeric(df.get("Alarme", pd.Series(index=df.index, dtype=float)), errors="coerce")
    kinds = pd.Series("unknown", index=df.index)
    kinds.loc[alarms.eq(0)] = "none"
    kinds.loc[alarms.eq(1)] = "generic"
    kinds.loc[temperatures.lt(low_limit)] = "low"
    kinds.loc[temperatures.gt(high_limit)] = "high"
    kinds.loc[alarms.eq(1) & doors.eq(1)] = "door"
    return kinds

def dataframe_to_excel_bytes(df: pd.DataFrame) -> bytes:
    excel_buffer = BytesIO()
    df.to_excel(excel_buffer, index=False, sheet_name="Dados")
    return excel_buffer.getvalue()

def build_report_pdf(
    df: pd.DataFrame,
    source_name: str,
    source_label: str | None = None,
    high_limit: float = TEMP_HIGH_ALARM_LIMIT,
    low_limit: float = TEMP_LOW_ALARM_LIMIT,
    period_start: pd.Timestamp | None = None,
    period_end: pd.Timestamp | None = None,
) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=1.6 * cm,
        rightMargin=1.6 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
        title="Relatorio Datalogger",
    )
    styles = getSampleStyleSheet()
    story = []

    if LOGO_PATH.exists():
        try:
            story.append(Image(str(LOGO_PATH), width=6.8 * cm, height=2.4 * cm))
            story.append(Spacer(1, 4))
        except Exception:
            pass

    story.append(Paragraph("Relatorio do Datalogger", styles["Title"]))
    story.append(Spacer(1, 8))
    story.append(Paragraph(f"Arquivo: {source_name}", styles["Normal"]))
    story.append(Paragraph(f"NAME: {source_label or '-'}", styles["Normal"]))
    story.append(Paragraph(f"Limites de temperatura: {format_metric(low_limit)} a {format_metric(high_limit)} °C", styles["Normal"]))
    record_count_label = (
        "Registros encontrados no periodo"
        if period_start is not None and period_end is not None
        else "Total de registros"
    )
    story.append(Paragraph(f"{record_count_label}: {len(df)}", styles["Normal"]))
    time_col = get_main_time_column(df)
    if period_start is not None and period_end is not None:
        story.append(
            Paragraph(
                f"Periodo selecionado: {format_datetime(period_start)} ate {format_datetime(period_end)}",
                styles["Normal"],
            )
        )
    elif time_col and not df.empty:
        story.append(
            Paragraph(
                f"Periodo: {format_datetime(df[time_col].min())} ate {format_datetime(df[time_col].max())}",
                styles["Normal"],
            )
        )

    temp_series = (
        pd.to_numeric(df["Tprincipal"], errors="coerce")
        if "Tprincipal" in df.columns
        else pd.Series(dtype="float64")
    )
    temp_min = temp_series.min() if not temp_series.empty else float("nan")
    temp_max = temp_series.max() if not temp_series.empty else float("nan")
    temp_avg = temp_series.mean() if not temp_series.empty else float("nan")
    story.append(Spacer(1, 10))
    story.append(Paragraph("Resumo de temperatura", styles["Heading3"]))
    summary_table = Table(
        [
            ["Metrica", "Valor"],
            ["Temperatura minima", format_metric(temp_min)],
            ["Temperatura maxima", format_metric(temp_max)],
            ["Temperatura media", format_metric(temp_avg)],
        ],
        colWidths=[7 * cm, 7 * cm],
    )
    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
            ]
        )
    )
    story.append(summary_table)

    if time_col and "Tprincipal" in df.columns:
        plot_df = (
            df[[time_col, "Tprincipal"]]
            .dropna(subset=[time_col])
            .sort_values(time_col)
            .tail(1200)
            .copy()
        )
        plot_df["Tprincipal"] = pd.to_numeric(plot_df["Tprincipal"], errors="coerce")
        plot_df = plot_df.dropna(subset=["Tprincipal"])
        if not plot_df.empty:
            story.append(Spacer(1, 12))
            story.append(Paragraph("Grafico de temperatura", styles["Heading3"]))

            chart_w = 17.5 * cm
            chart_h = 6.2 * cm
            pad_l, pad_r, pad_t, pad_b = 34, 12, 14, 22
            plot_w = chart_w - pad_l - pad_r
            plot_h = chart_h - pad_t - pad_b
            y_vals_full = plot_df["Tprincipal"].tolist()
            max_points = 260
            if len(y_vals_full) > max_points:
                step = max(1, len(y_vals_full) // max_points)
                sampled = (
                    plot_df.reset_index(drop=True)
                    .groupby(plot_df.reset_index(drop=True).index // step)["Tprincipal"]
                    .mean()
                    .tolist()
                )
                y_vals = sampled
            else:
                y_vals = y_vals_full

            y_min = min(y_vals)
            y_max = max(y_vals)
            if y_min == y_max:
                y_min -= 1
                y_max += 1

            n = len(y_vals)
            points = []
            for i, y in enumerate(y_vals):
                x = pad_l + (i / max(1, n - 1)) * plot_w
                y_norm = (y - y_min) / (y_max - y_min)
                y_pix = pad_b + y_norm * plot_h
                points.extend([x, y_pix])

            drawing = Drawing(chart_w, chart_h)
            drawing.add(Rect(0, 0, chart_w, chart_h, fillColor=colors.white, strokeColor=colors.white))
            drawing.add(Rect(pad_l, pad_b, plot_w, plot_h, fillColor=colors.HexColor("#f8fafc"), strokeColor=colors.HexColor("#cbd5e1"), strokeWidth=0.8))
            for t in (0.25, 0.5, 0.75):
                gy = pad_b + plot_h * t
                drawing.add(Line(pad_l, gy, pad_l + plot_w, gy, strokeColor=colors.HexColor("#e2e8f0"), strokeWidth=0.5))
            drawing.add(PolyLine(points, strokeColor=colors.HexColor("#0d9488"), strokeWidth=1.2))
            drawing.add(String(2, chart_h - 10, "T", fontSize=8, fillColor=colors.HexColor("#64748b")))
            drawing.add(String(chart_w - 52, 4, "tempo", fontSize=8, fillColor=colors.HexColor("#64748b")))
            drawing.add(String(pad_l, 4, f"min: {format_metric(y_min)}", fontSize=8, fillColor=colors.HexColor("#64748b")))
            drawing.add(String(chart_w - 120, chart_h - 10, f"max: {format_metric(y_max)}", fontSize=8, fillColor=colors.HexColor("#64748b")))
            story.append(drawing)

    story.append(Spacer(1, 12))
    story.append(Paragraph("Ultimos alarmes", styles["Heading3"]))
    kinds = record_alarm_kinds(df, high_limit=high_limit, low_limit=low_limit)
    alarm_df = df.loc[kinds.isin(ALARM_LABELS)].copy()
    alarm_df["_report_alarm_kind"] = kinds.loc[alarm_df.index]

    if alarm_df.empty:
        story.append(Paragraph("Nenhum alarme ativo encontrado.", styles["Normal"]))
    else:
        rows = [["Data e hora", "Tipo", "Temperatura", "Porta"]]
        for _, row in alarm_df.tail(10).iloc[::-1].iterrows():
            row_temp = coerce_float(row.get("Tprincipal"))
            row_door = coerce_float(row.get("Porta"), default=0.0)
            when = format_datetime(row.get(time_col)) if time_col else "-"
            rows.append(
                [
                    when,
                    ALARM_LABELS[row["_report_alarm_kind"]],
                    format_metric(row_temp),
                    format_metric(row_door),
                ]
            )
        alarm_table = Table(rows, colWidths=[4.8 * cm, 6.1 * cm, 3 * cm, 2.1 * cm])
        alarm_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        story.append(alarm_table)

    story.append(Spacer(1, 12))
    story.append(Paragraph("Registros encontrados no periodo selecionado", styles["Heading3"]))
    display_df = prepare_display_dataframe(df)
    preview_df = display_df.copy()
    if preview_df.empty:
        story.append(Paragraph("Sem dados no periodo selecionado.", styles["Normal"]))
    else:
        # Ordem preferida das colunas. Só entram no relatório as que realmente
        # existem no arquivo importado — variável ausente não vira coluna vazia.
        time_label_col = next(
            (c for c in ["Data e hora", "Início", "Fim"] if c in preview_df.columns),
            None,
        )
        report_spec = []
        if time_label_col:
            report_spec.append((time_label_col, "Data e Hora"))
        report_spec += [
            ("Tprincipal", "Tprincipal"),
            ("Degelo", "Degelo"),
            ("setpoint", "SetPoint"),
            ("Tomada", "Tomada"),
            ("Bateria", "Bateria"),
            ("alarme", "Alarme"),
            ("porta", "Porta"),
        ]
        report_spec = [(src, label) for src, label in report_spec if src in preview_df.columns]
        if not report_spec:
            report_spec = [(col, str(col)) for col in list(preview_df.columns)[:6]]

        source_cols = [src for src, _ in report_spec]
        header_row = [label for _, label in report_spec]

        # A coluna de data/hora recebe largura fixa para o timestamp não invadir
        # a coluna seguinte; o restante divide o espaço disponível.
        total_width = 17.0 * cm
        has_date_first = bool(time_label_col) and source_cols and source_cols[0] == time_label_col
        date_width = 3.5 * cm if has_date_first else 0.0
        other_count = len(source_cols) - (1 if has_date_first else 0)
        other_width = (total_width - date_width) / other_count if other_count else total_width
        col_widths = [
            date_width if (has_date_first and idx == 0) else other_width
            for idx in range(len(source_cols))
        ]
        table_style = TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )

        # Gera todos os registros. Os blocos menores evitam que o ReportLab
        # precise calcular uma única tabela gigantesca de uma vez.
        rows_per_table = 1000
        for chunk_start in range(0, len(preview_df), rows_per_table):
            chunk = preview_df[source_cols].iloc[chunk_start:chunk_start + rows_per_table]
            table_rows = [header_row]
            for row in chunk.itertuples(index=False):
                table_rows.append(
                    ["" if pd.isna(value) else str(value)[:40] for value in row]
                )

            data_table = Table(table_rows, colWidths=col_widths, repeatRows=1)
            data_table.setStyle(table_style)
            story.append(data_table)

    doc.build(story)
    return buffer.getvalue()
