"""Data access layer: every query the UI needs, in one module.

The UI never reads Parquet directly. It calls these functions, which run
DuckDB SQL over the pipeline output and return small, chart-ready frames.
Results are cached, so moving a slider back to an earlier value is instant.

If the data later moves to a database or an API, only this file changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import duckdb
import numpy as np
import pandas as pd
import streamlit as st

from frontend import config


@dataclass(frozen=True)
class Filters:
    """Everything the sidebar controls. Frozen so it can key the caches."""

    region: str
    year_from: int
    year_to: int
    metric: str                     # column name, e.g. "harmonized_frp"
    density: bool                   # True: MW per 1,000 km², False: total MW
    landcovers: tuple[str, ...]
    cell_ids: tuple[str, ...] = ()  # empty = whole region


ALLOWED_METRICS = set(config.METRICS.values())


@st.cache_resource
def _con() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute(f"CREATE VIEW cells AS SELECT * FROM read_parquet('{config.CELLS_PATH.as_posix()}')")
    con.execute(f"CREATE VIEW daily AS SELECT * FROM read_parquet('{config.DAILY_PATH.as_posix()}')")
    return con


def _query(sql: str, params: list | None = None) -> pd.DataFrame:
    # DuckDB connections are not thread-safe; each Streamlit session gets a cursor.
    return _con().cursor().execute(sql, params or []).df()


def _where(f: Filters, alias_daily: str = "d", alias_cells: str = "c") -> tuple[str, list]:
    if f.metric not in ALLOWED_METRICS:
        raise ValueError(f"Unknown metric {f.metric!r}")
    clauses = [
        f"{alias_cells}.region = ?",
        f"year({alias_daily}.date) BETWEEN ? AND ?",
    ]
    params: list = [f.region, f.year_from, f.year_to]
    if f.landcovers:
        clauses.append(f"{alias_cells}.landcover IN ({','.join('?' * len(f.landcovers))})")
        params += list(f.landcovers)
    if f.cell_ids:
        clauses.append(f"{alias_cells}.cell_id IN ({','.join('?' * len(f.cell_ids))})")
        params += list(f.cell_ids)
    return " AND ".join(clauses), params


def _area_km2(f: Filters) -> float:
    """Total area of the selected cells, burning or not (for density)."""
    clauses, params = ["region = ?"], [f.region]
    if f.landcovers:
        clauses.append(f"landcover IN ({','.join('?' * len(f.landcovers))})")
        params += list(f.landcovers)
    if f.cell_ids:
        clauses.append(f"cell_id IN ({','.join('?' * len(f.cell_ids))})")
        params += list(f.cell_ids)
    df = _query(f"SELECT sum(area_km2) AS a FROM cells WHERE {' AND '.join(clauses)}", params)
    return float(df["a"].iloc[0] or np.nan)


def _scale(f: Filters) -> float:
    """Multiplier that turns summed MW into the chosen unit."""
    return 1000.0 / _area_km2(f) if f.density else 1.0


# --- Lookups for the sidebar ---------------------------------------------------

@st.cache_data
def regions() -> list[str]:
    return _query("SELECT DISTINCT region FROM cells ORDER BY 1")["region"].tolist()


@st.cache_data
def landcovers(region: str) -> list[str]:
    return _query(
        "SELECT DISTINCT landcover FROM cells WHERE region = ? ORDER BY 1", [region]
    )["landcover"].tolist()


@st.cache_data
def year_bounds() -> tuple[int, int]:
    df = _query("SELECT min(year(date)) AS lo, max(year(date)) AS hi FROM daily")
    return int(df["lo"].iloc[0]), int(df["hi"].iloc[0])


# --- Burning calendar -----------------------------------------------------------

@st.cache_data(show_spinner=False)
def daily_values(f: Filters, start: date, end: date) -> pd.Series:
    """One value per day from start to end (inclusive), in the chosen unit.

    Days with no row in the data are real zeros (no fire). Days the chosen
    sensor had no data at all (raw VIIRS before it launched) are NaN, so the
    calendar can show "no data" instead of "no fire".
    """
    where, params = _where(f)
    df = _query(
        f"""
        SELECT d.date AS day, sum(d.{f.metric}) AS value, count(d.{f.metric}) AS n
        FROM daily d JOIN cells c USING (cell_id)
        WHERE {where} AND d.date BETWEEN ? AND ?
        GROUP BY ALL
        """,
        params + [start, end],
    )
    days = pd.date_range(start, end, freq="D")
    s = pd.Series(0.0, index=days)
    if len(df):
        df["day"] = pd.to_datetime(df["day"])
        s.loc[df["day"]] = df["value"].fillna(0.0).to_numpy()
    if f.metric == "viirs_frp":
        s[s.index < config.VIIRS_START] = np.nan
    return s * _scale(f)


@st.cache_data(show_spinner=False)
def source_by_month(f: Filters, start: date, end: date) -> dict[str, str]:
    """Where each month's harmonized values come from: {"2024-03": "VIIRS→MODIS", ...}."""
    where, params = _where(f)
    df = _query(
        f"""
        SELECT strftime(d.date, '%Y-%m') AS ym, max(d.source) AS source
        FROM daily d JOIN cells c USING (cell_id)
        WHERE {where} AND d.date BETWEEN ? AND ?
        GROUP BY 1
        """,
        params + [start, end],
    )
    return dict(zip(df["ym"], df["source"]))


# --- Time series ----------------------------------------------------------------

@st.cache_data(show_spinner=False)
def monthly_series(f: Filters) -> pd.DataFrame:
    """Monthly totals of every sensor series, plus the harmonized uncertainty band.

    The band sums the per-cell lower and upper bounds, which assumes the
    model errors are fully correlated. That is a conservative (wide) band.
    """
    where, params = _where(f)
    df = _query(
        f"""
        SELECT date_trunc('month', d.date) AS month,
               sum(d.harmonized_frp) AS "Harmonized",
               sum(d.modis_frp)      AS "MODIS (raw)",
               sum(d.viirs_frp)      AS "VIIRS (raw)",
               sum(d.harmonized_lo)  AS lo,
               sum(d.harmonized_hi)  AS hi
        FROM daily d JOIN cells c USING (cell_id)
        WHERE {where}
        GROUP BY ALL ORDER BY 1
        """,
        params,
    )
    full = pd.date_range(f"{f.year_from}-01-01", f"{f.year_to}-12-01", freq="MS")
    df["month"] = pd.to_datetime(df["month"])
    df = df.set_index("month").reindex(full)
    # Months with no fire are real zeros, except for a sensor outside its record.
    df["Harmonized"] = df["Harmonized"].fillna(0.0)
    df["lo"] = df["lo"].fillna(df["Harmonized"])
    df["hi"] = df["hi"].fillna(df["Harmonized"])
    viirs_on = df.index >= config.VIIRS_START.to_period("M").to_timestamp()
    df.loc[viirs_on, "VIIRS (raw)"] = df.loc[viirs_on, "VIIRS (raw)"].fillna(0.0)
    df["MODIS (raw)"] = df["MODIS (raw)"].fillna(0.0)
    return (df * _scale(f)).rename_axis("month").reset_index()


# --- Map ------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def cell_totals(f: Filters) -> pd.DataFrame:
    """One row per grid cell in the region, with its total (or density) for the period.

    Ignores f.cell_ids on purpose: the map always shows the whole region so
    the user can see and change the selection.
    """
    f_all = Filters(**{**f.__dict__, "cell_ids": ()})
    where, params = _where(f_all)
    cells_clause, cell_params = "region = ?", [f.region]
    if f.landcovers:
        cells_clause += f" AND landcover IN ({','.join('?' * len(f.landcovers))})"
        cell_params += list(f.landcovers)
    df = _query(
        f"""
        WITH agg AS (
            SELECT d.cell_id, sum(d.{f.metric}) AS total, count(DISTINCT d.date) AS fire_days
            FROM daily d JOIN cells c USING (cell_id)
            WHERE {where}
            GROUP BY 1
        )
        SELECT c.cell_id, c.lat, c.lon, c.landcover, c.area_km2,
               coalesce(a.total, 0) AS total, coalesce(a.fire_days, 0) AS fire_days
        FROM cells c LEFT JOIN agg a USING (cell_id)
        WHERE {cells_clause}
        """,
        params + cell_params,
    )
    yrs = _query(
        f"SELECT count(DISTINCT year(d.date)) AS n FROM daily d JOIN cells c USING (cell_id) "
        f"WHERE {where} AND d.{f.metric} IS NOT NULL", params)
    n_years = max(int(yrs["n"].iloc[0] or 0), 1)
    df["value"] = df["total"] / n_years
    if f.density:
        df["value"] = df["value"] * 1000.0 / df["area_km2"]
    return df


# --- Headline numbers -----------------------------------------------------------

@st.cache_data(show_spinner=False)
def headline(f: Filters) -> dict:
    where, params = _where(f)
    df = _query(
        f"""
        SELECT sum(d.{f.metric}) AS total,
               count(DISTINCT d.date) FILTER (WHERE d.{f.metric} > 0) AS fire_days,
               sum(d.harmonized_frp) FILTER (WHERE d.source <> 'MODIS') AS converted,
               sum(d.harmonized_frp) AS harm_total,
               count(DISTINCT year(d.date)) FILTER (WHERE d.{f.metric} IS NOT NULL) AS n_years
        FROM daily d JOIN cells c USING (cell_id)
        WHERE {where}
        """,
        params,
    )
    peak = _query(
        f"""
        SELECT month(d.date) AS m, sum(d.{f.metric}) AS v
        FROM daily d JOIN cells c USING (cell_id)
        WHERE {where} GROUP BY 1 ORDER BY v DESC NULLS LAST LIMIT 1
        """,
        params,
    )
    row = df.iloc[0]
    # Average over years the sensor actually observed (raw VIIRS starts in 2012).
    n_years = max(int(row["n_years"] or 0), 1)
    harm = row["harm_total"] or 0.0
    return {
        "annual_mean": (row["total"] or 0.0) / n_years * _scale(f),
        "fire_days": int(row["fire_days"] or 0),
        "peak_month": int(peak["m"].iloc[0]) if len(peak) and pd.notna(peak["v"].iloc[0]) else None,
        "converted_share": (row["converted"] or 0.0) / harm if harm else 0.0,
    }
