"""Harmonized Burning Activity Calendar — Streamlit entry point.

Run:  streamlit run app.py

This file only does layout and wiring:
  sidebar filters -> Filters object -> data.py queries -> charts.py / map_view.py
"""

from __future__ import annotations

import calendar as _cal

import streamlit as st

from frontend import calendar_view, charts, config, data, map_view, splash
from frontend.data import Filters

st.set_page_config(
    page_title="Fire Activity Calendar",
    page_icon="🔥",
    layout="wide",
)

# --- Intro screen: shown until the user clicks Start ---------------------------------
if not st.session_state.get("started"):
    splash.render()
    st.stop()

mode = st.sidebar.radio("Data source", ["Real observations", "Sample demo"])
if mode == "Real observations":
    from frontend import real_view

    real_view.render()
    st.stop()

if not config.DAILY_PATH.exists():
    st.error(
        f"No data found at `{config.DAILY_PATH}`. "
        "Run `python scripts/generate_sample_data.py` for sample data, "
        "or set `FIRE_DATA_DIR` to the pipeline output folder."
    )
    st.stop()

# --- Sidebar: every filter in one place -------------------------------------------
with st.sidebar:
    st.header("Filters")
    region = st.selectbox("Region", data.regions())
    y_lo, y_hi = data.year_bounds()
    year_from, year_to = st.slider("Years", y_lo, y_hi, (y_lo, y_hi))
    series_label = st.radio(
        "Series", list(config.METRICS), index=0,
        help="Harmonized = MODIS until 2021, then VIIRS converted to the MODIS scale. "
             "The raw series are shown for comparison.",
    )
    unit_label = st.radio(
        "Unit", list(config.UNITS), index=0, horizontal=True,
        help="Density divides by the area of the selected cells, so regions of different size can be compared.",
    )
    lcs = data.landcovers(region)
    chosen_lcs = st.multiselect("Land cover", lcs, default=lcs)

    st.divider()
    if st.button("← Back to intro", width="stretch"):
        st.session_state.started = False
        st.rerun()
    with st.expander("How the harmonization works"):
        st.markdown(
            "- **2003–2011:** MODIS only.\n"
            "- **2012–2021:** both sensors. This overlap is used to fit the VIIRS → MODIS model.\n"
            "- **2022 onward:** VIIRS converted to MODIS scale, because the Aqua MODIS orbit drifted "
            "and the satellites are being retired.\n\n"
            "Converted values are modeled, so they carry an uncertainty band in the time series."
        )

unit = config.UNITS[unit_label]
metric = config.METRICS[series_label]

# --- Map selection (read before drawing, so every chart uses it) ------------------
if "map_reset" not in st.session_state:
    st.session_state.map_reset = 0
map_key = f"map_{region}_{st.session_state.map_reset}"
selected = map_view.selected_ids(st.session_state.get(map_key))

f = Filters(
    region=region, year_from=year_from, year_to=year_to, metric=metric,
    density=unit_label == "FRP density", landcovers=tuple(chosen_lcs),
    cell_ids=tuple(sorted(selected)),
)

# --- Header --------------------------------------------------------------------------
st.title("Harmonized Burning Activity Calendar")
st.caption(
    f"{region} · {year_from}–{year_to} · {series_label} · fire radiative power (FRP) from active fire hotspots"
)
if config.IS_SAMPLE_DATA:
    st.warning("Showing **synthetic sample data** for development. These are not real fire observations.", icon="⚠️")
if not chosen_lcs:
    st.info("Pick at least one land cover type in the sidebar.")
    st.stop()

if selected:
    c1, c2 = st.columns([5, 1], vertical_alignment="center")
    c1.markdown(f"Showing **{len(selected)} selected cell{'s' if len(selected) > 1 else ''}** from the map.")
    if c2.button("Clear selection", width="stretch"):
        st.session_state.map_reset += 1
        st.rerun()

# --- Headline numbers ----------------------------------------------------------------
h = data.headline(f)
k1, k2, k3, k4 = st.columns(4)
k1.metric(f"Mean annual FRP ({unit})", charts._fmt(h["annual_mean"]))
k2.metric("Days with fire", f"{h['fire_days']:,}")
k3.metric("Peak month", _cal.month_name[h["peak_month"]] if h["peak_month"] else "–")
k4.metric(
    "Harmonized from VIIRS", f"{h['converted_share']:.0%}",
    help="Share of harmonized FRP in this view that comes from converted VIIRS, not observed MODIS.",
)

# --- Burning calendar ------------------------------------------------------------------
st.subheader("Burning calendar")
st.caption(
    "Pick a time interval. Each square is one day; brighter = more fire. "
    "Hover a day for its value."
)
cal_start, cal_end = calendar_view.interval_picker(year_from, year_to, h["peak_month"])
day_values = data.daily_values(f, cal_start.date(), cal_end.date())
sources = data.source_by_month(f, cal_start.date(), cal_end.date()) if metric == "harmonized_frp" else None
st.markdown(calendar_view.month_grid_html(day_values, unit, sources), unsafe_allow_html=True)

# --- Map + time series ---------------------------------------------------------------
left, right = st.columns([1, 1.25], gap="large")
with left:
    st.subheader("Where it burns")
    st.caption(
        f"Mean {unit} per year in each cell. Drag to spin the globe, scroll to zoom, "
        "click cells to filter the calendar and chart."
    )
    extrude = st.toggle("3D bars (height = fire activity)", value=False)
    cells_df = data.cell_totals(f)
    st.pydeck_chart(
        map_view.cell_map(cells_df, unit, extrude=extrude),
        on_select="rerun", selection_mode="multi-object", key=map_key, height=420,
    )
    pos = cells_df.loc[cells_df["value"] > 0, "value"]
    if len(pos):
        ramp = ", ".join(config.FIRE_RAMP)
        st.markdown(
            f"<div style='display:flex;align-items:center;gap:8px;font-size:12px;color:{config.INK_SECONDARY}'>"
            f"<span>{charts._fmt(pos.min())}</span>"
            f"<span style='flex:0 0 120px;height:10px;border-radius:2px;background:linear-gradient(90deg,{ramp})'></span>"
            f"<span>{charts._fmt(pos.max())} {unit}/yr · log scale</span></div>",
            unsafe_allow_html=True,
        )
with right:
    st.subheader("Is the record consistent?")
    st.caption(
        "Monthly totals. The harmonized line should continue smoothly across the dotted "
        "line where VIIRS takes over. A jump there means the conversion needs work."
    )
    ts = data.monthly_series(f)
    visible = st.pills(
        "Series shown", list(config.SERIES_COLORS), selection_mode="multi",
        default=list(config.SERIES_COLORS), label_visibility="collapsed",
    )
    st.plotly_chart(charts.time_series(ts, unit, visible or []), width="stretch",
                    config={"displaylogo": False})

# --- Table view (accessibility + download) ---------------------------------------------
with st.expander("Data table and download"):
    table = ts.rename(columns={"lo": "Harmonized low", "hi": "Harmonized high", "month": "Month"})
    st.dataframe(table, hide_index=True, width="stretch",
                 column_config={"Month": st.column_config.DateColumn(format="YYYY-MM")})
    st.download_button(
        "Download monthly series (CSV)", table.to_csv(index=False).encode(),
        file_name=f"fire_monthly_{region.split(',')[0].lower().replace(' ', '_')}_{year_from}_{year_to}.csv",
        mime="text/csv",
    )
