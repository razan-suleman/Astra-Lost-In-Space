"""Burning calendar: an interval picker and a grid of month "calendar pages".

Each month is a small wall-calendar card: one square per day (weeks start on
Monday), colored from dim ember to bright flame by that day's fire activity.
Hover a day to see its date and value.

The picker has:
- quick presets: Fire season, Last 3 / 6 / 12 months, Last 2 years
- ◀ ▶ buttons that move the whole interval back or forward by its own length
- a slider to pick any range of months

The cards are plain HTML + CSS (st.markdown), so they're fast and easy to style.
All colors come from frontend/config.py.
"""

from __future__ import annotations

import calendar as _cal

import numpy as np
import pandas as pd
import streamlit as st

from frontend import config

RANGE_KEY = "cal_sel"      # the chosen interval: (first month label, last month label)
VERSION_KEY = "cal_ver"    # bumped whenever code changes the interval, to redraw the slider
PRESET_KEY = "cal_preset"
PRESETS = ["Fire season", "Last 3 months", "Last 6 months", "Last 12 months", "Last 2 years"]
DEFAULT_PRESET = "Last 12 months"
WEEKDAYS = ["M", "T", "W", "T", "F", "S", "S"]


# --- Interval picker ------------------------------------------------------------

def _labels(year_from: int, year_to: int) -> list[str]:
    return [p.strftime("%b %Y") for p in pd.period_range(f"{year_from}-01", f"{year_to}-12", freq="M")]


def _preset_range(name: str, labels: list[str], peak_month: int | None) -> tuple[str, str]:
    last = len(labels) - 1
    if name == "Fire season":
        # Six months around the peak month of the latest year: 2 before, 3 after.
        peak = peak_month or 8
        peak_idx = last - (12 - peak)
        s, e = peak_idx - 2, peak_idx + 3
        if e > last:  # season runs past the end of the data: slide it back
            s, e = s - (e - last), last
    else:
        n = {"Last 3 months": 3, "Last 6 months": 6, "Last 12 months": 12, "Last 2 years": 24}[name]
        s, e = last - n + 1, last
    s = max(0, s)
    return labels[s], labels[min(e, last)]


def _set_range(rng: tuple[str, str]) -> None:
    """Change the interval from code (presets, arrows) and redraw the slider at it."""
    st.session_state[RANGE_KEY] = rng
    st.session_state[VERSION_KEY] = st.session_state.get(VERSION_KEY, 0) + 1


def _shift(labels: list[str], direction: int) -> None:
    """Move the interval by its own length; stop at the ends of the data."""
    a, b = (labels.index(x) for x in st.session_state[RANGE_KEY])
    n = b - a + 1
    a2 = int(np.clip(a + direction * n, 0, len(labels) - n))
    _set_range((labels[a2], labels[a2 + n - 1]))
    st.session_state[PRESET_KEY] = None


def interval_picker(year_from: int, year_to: int, peak_month: int | None) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Draw the controls and return (first day, last day) of the chosen interval."""
    labels = _labels(year_from, year_to)

    def apply_preset() -> None:
        choice = st.session_state.get(PRESET_KEY)
        if choice:
            _set_range(_preset_range(choice, labels, peak_month))

    def from_slider() -> None:
        st.session_state[RANGE_KEY] = tuple(st.session_state[slider_key])
        st.session_state[PRESET_KEY] = None

    # First visit, or the sidebar years changed so the old range no longer exists.
    current = st.session_state.get(RANGE_KEY)
    if not current or any(x not in labels for x in current):
        st.session_state[PRESET_KEY] = DEFAULT_PRESET
        _set_range(_preset_range(DEFAULT_PRESET, labels, peak_month))
    elif st.session_state.get(PRESET_KEY):
        # Keep a preset in sync when other filters (like the region) change its meaning.
        rng = _preset_range(st.session_state[PRESET_KEY], labels, peak_month)
        if rng != tuple(current):
            _set_range(rng)

    left, prev_col, next_col = st.columns([10, 1, 1], vertical_alignment="center")
    with left:
        st.pills("Quick pick", PRESETS, key=PRESET_KEY, on_change=apply_preset,
                 label_visibility="collapsed")
    prev_col.button("◀", key="cal_prev", help="Move the interval back", width="stretch",
                    on_click=_shift, args=(labels, -1))
    next_col.button("▶", key="cal_next", help="Move the interval forward", width="stretch",
                    on_click=_shift, args=(labels, 1))

    slider_key = f"cal_slider_{st.session_state[VERSION_KEY]}_{year_from}_{year_to}"
    start_lbl, end_lbl = st.select_slider(
        "Months to show", options=labels, value=tuple(st.session_state[RANGE_KEY]),
        key=slider_key, on_change=from_slider, label_visibility="collapsed",
    )
    start = pd.Timestamp(pd.Period(start_lbl, freq="M").start_time.date())
    end = pd.Timestamp(pd.Period(end_lbl, freq="M").end_time.date())

    n_months = (end.year - start.year) * 12 + end.month - start.month + 1
    if n_months > config.CALENDAR_MAX_MONTHS:
        end = (start + pd.DateOffset(months=config.CALENDAR_MAX_MONTHS)) - pd.Timedelta(days=1)
        st.caption(f"Showing the first {config.CALENDAR_MAX_MONTHS} months. "
                   "Pick a shorter range to see the rest, or use ▶ to move forward.")
    return start, end


# --- Month cards ----------------------------------------------------------------

def _fmt(v: float) -> str:
    if abs(v) >= 10_000:
        return f"{v / 1000:,.0f}k"
    if abs(v) >= 1000:
        return f"{v / 1000:,.1f}k"
    if abs(v) >= 10:
        return f"{v:,.0f}"
    return f"{v:.2g}"


def _bins(values: pd.Series) -> tuple[np.ndarray, float, float]:
    """Bin index (0..6) for each day on a log scale; -1 = no fire, -2 = no data."""
    v = values.to_numpy(dtype=float)
    idx = np.full(v.shape, -1)
    idx[np.isnan(v)] = -2
    pos = v > 0
    if not pos.any():
        return idx, 0.0, 0.0
    logv = np.log10(v[pos])
    lo, hi = logv.min(), logv.max()
    n = len(config.FIRE_RAMP)
    idx[pos] = n - 1 if hi == lo else np.clip(((logv - lo) / (hi - lo) * n).astype(int), 0, n - 1)
    return idx, float(10**lo), float(10**hi)


_CSS = f"""
<style>
.cal-sum {{ display:flex; flex-wrap:wrap; gap:8px 28px; margin:4px 0 14px; color:{config.INK_SECONDARY}; font-size:.9rem; }}
.cal-sum b {{ color:{config.INK_PRIMARY}; font-weight:600; }}
.cal-grid {{ display:grid; grid-template-columns:repeat(auto-fill, minmax(215px, 1fr)); gap:14px; }}
.cal-card {{
  background:linear-gradient(180deg, rgba(255,255,255,.055), rgba(255,255,255,.02));
  border:1px solid rgba(205,226,251,.13); border-radius:14px; padding:12px 12px 11px;
  transition:border-color .25s ease, transform .25s ease, box-shadow .25s ease;
}}
.cal-card:hover {{ border-color:rgba(205,226,251,.32); transform:translateY(-2px);
  box-shadow:0 8px 24px rgba(0,0,0,.25); }}
.cal-h {{ display:flex; align-items:baseline; gap:6px; margin-bottom:4px; white-space:nowrap; }}
.cal-m {{ color:{config.INK_PRIMARY}; font-weight:650; font-size:1rem; }}
.cal-y {{ color:{config.INK_MUTED}; font-size:.85rem; }}
.cal-tot {{ margin-left:auto; color:{config.INK_SECONDARY}; font-size:.78rem; white-space:nowrap; }}
.cal-bar {{ height:3px; border-radius:2px; background:rgba(205,226,251,.08); margin:2px 0 8px; overflow:hidden; }}
.cal-bar i {{ display:block; height:100%; border-radius:2px;
  background:linear-gradient(90deg, {config.FIRE_RAMP[2]}, {config.FIRE_RAMP[-1]}); }}
.cal-src {{ display:inline-block; font-size:.62rem; letter-spacing:.06em; padding:1px 6px; border-radius:999px;
  color:{config.INK_SECONDARY}; border:1px solid rgba(205,226,251,.28); margin-left:2px; }}
.cal-src.mod {{ border-style:dashed; }}
.cal-days {{ display:grid; grid-template-columns:repeat(7, 1fr); gap:3px; }}
.cal-wd {{ font-size:.62rem; color:{config.INK_MUTED}; text-align:center; padding-bottom:2px; }}
.cal-d {{
  position:relative; aspect-ratio:1; border-radius:4px; display:flex; align-items:center; justify-content:center;
  font-size:.62rem; font-weight:500; background:{config.NO_FIRE}; color:rgba(205,226,251,.42);
  transition:transform .15s ease, box-shadow .15s ease;
}}
.cal-d:hover {{ transform:scale(1.35); z-index:5; box-shadow:0 0 0 1.5px #fff, 0 0 14px rgba(255,171,61,.55); }}
.cal-d.na {{ background:repeating-linear-gradient(45deg, rgba(205,226,251,.13) 0 2px, transparent 2px 5px); }}
.cal-d:hover::after {{
  content:attr(data-t); position:absolute; bottom:135%; left:50%; transform:translateX(-50%) scale(.74);
  transform-origin:bottom center; white-space:nowrap; pointer-events:none;
  background:#0b1a33; color:{config.INK_PRIMARY}; border:1px solid rgba(205,226,251,.25);
  padding:5px 9px; border-radius:7px; font-size:.95rem; font-weight:500; box-shadow:0 6px 18px rgba(0,0,0,.35);
}}
.cal-legend {{ display:flex; align-items:center; flex-wrap:wrap; gap:6px; margin:14px 0 26px;
  font-size:.78rem; color:{config.INK_SECONDARY}; }}
.cal-legend i {{ display:inline-block; width:13px; height:13px; border-radius:3px; }}
.cal-legend .gap {{ width:14px; }}
</style>
"""


def month_grid_html(values: pd.Series, unit: str, sources: dict[str, str] | None) -> str:
    """HTML for the summary line, the month cards and the legend.

    values: one value per day (NaN = no data). sources: month "YYYY-MM" ->
    "MODIS" or "VIIRS→MODIS", shown as a small tag; None hides the tags.
    """
    idx, vmin, vmax = _bins(values)
    by_day = dict(zip(values.index.date, zip(values.to_numpy(dtype=float), idx)))
    monthly = values.groupby([values.index.year, values.index.month]).sum(min_count=1)
    top_month = float(np.nanmax(monthly.to_numpy())) if monthly.notna().any() else 0.0

    # Summary line
    fire_days = int((values > 0).sum())
    total = float(np.nansum(values.to_numpy()))
    parts = [f"<span><b>{_fmt(total)} {unit}</b> in this interval</span>",
             f"<span><b>{fire_days}</b> of {values.notna().sum()} days with fire</span>"]
    if fire_days:
        peak_day = values.idxmax()
        parts.append(f"<span>Busiest day <b>{peak_day:%d %b %Y}</b> · {_fmt(values.max())} {unit}</span>")
    html = [_CSS, f'<div class="cal-sum">{"".join(parts)}</div>', '<div class="cal-grid">']

    for (y, m), mtotal in monthly.items():
        first = pd.Timestamp(y, m, 1)
        n_days = _cal.monthrange(y, m)[1]
        src = ""
        if sources:
            s = sources.get(f"{y}-{m:02d}")
            if s:
                modeled = s != "MODIS"
                tag, cls = ("VIIRS", "mod") if modeled else ("MODIS", "")
                tip = ("converted from VIIRS to the MODIS scale (modeled)" if modeled
                       else "observed by MODIS")
                src = f'<span class="cal-src {cls}" title="Values for this month are {tip}">{tag}</span>'
        width = 0 if not top_month or np.isnan(mtotal) else max(2, mtotal / top_month * 100)
        tot_txt = "no data" if np.isnan(mtotal) else f"{_fmt(mtotal)} {unit}"
        cells = [f'<div class="cal-wd">{d}</div>' for d in WEEKDAYS]
        cells += ['<div></div>'] * first.weekday()
        for d in range(1, n_days + 1):
            day = first + pd.Timedelta(days=d - 1)
            v, b = by_day.get(day.date(), (np.nan, -2))
            if b == -2:
                cells.append(f'<div class="cal-d na" data-t="{day:%a %d %b %Y} · no data">{d}</div>')
            elif b == -1:
                cells.append(f'<div class="cal-d" data-t="{day:%a %d %b %Y} · no fire">{d}</div>')
            else:
                ink = "#2a1206" if b >= 4 else "rgba(255,240,225,.85)"
                cells.append(
                    f'<div class="cal-d" style="background:{config.FIRE_RAMP[b]};color:{ink}" '
                    f'data-t="{day:%a %d %b %Y} · {_fmt(v)} {unit}">{d}</div>'
                )
        html.append(
            '<div class="cal-card">'
            f'<div class="cal-h"><span class="cal-m">{_cal.month_name[m]}</span>'
            f'<span class="cal-y">{y}</span>{src}<span class="cal-tot">{tot_txt}</span></div>'
            f'<div class="cal-bar"><i style="width:{width:.0f}%"></i></div>'
            f'<div class="cal-days">{"".join(cells)}</div></div>'
        )
    html.append("</div>")

    # Legend
    swatches = "".join(f'<i style="background:{c}"></i>' for c in config.FIRE_RAMP)
    rng = f"{_fmt(vmin)} – {_fmt(vmax)} {unit} per day, log scale" if vmax else "no fire in this interval"
    html.append(
        f'<div class="cal-legend"><span>Less</span>{swatches}<span>More</span>'
        f'<span class="gap"></span><span>({rng})</span><span class="gap"></span>'
        f'<i style="background:{config.NO_FIRE}"></i><span>No fire</span><span class="gap"></span>'
        '<i style="background:repeating-linear-gradient(45deg, rgba(205,226,251,.3) 0 2px, transparent 2px 5px)"></i>'
        "<span>No data</span></div>"
    )
    return "".join(html)
