"""Single place for paths, dates, labels and colors used by the frontend.

Swap the data paths for the real pipeline output, and the colors for your
brand, here. Nothing else in the app should hard-code these values.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

# --- Data --------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("FIRE_DATA_DIR", ROOT / "data"))
CELLS_PATH = DATA_DIR / "cells.parquet"
DAILY_PATH = DATA_DIR / "fire_daily.parquet"

# Set to False once the real pipeline output replaces the sample data.
IS_SAMPLE_DATA = os.environ.get("FIRE_SAMPLE_DATA", "1") == "1"

# --- Sensor timeline ---------------------------------------------------------
VIIRS_START = pd.Timestamp("2012-01-20")   # S-NPP VIIRS 375 m record begins
TRANSITION = pd.Timestamp("2022-01-01")    # harmonized series switches MODIS -> VIIRS→MODIS

# --- Metrics -----------------------------------------------------------------
METRICS = {
    "Harmonized": "harmonized_frp",
    "MODIS (raw)": "modis_frp",
    "VIIRS (raw)": "viirs_frp",
}
UNITS = {
    "Total FRP": "MW",
    "FRP density": "MW per 1,000 km²",
}
# Longest interval the calendar shows at once, in months.
CALENDAR_MAX_MONTHS = 24

# --- Colors: "night sky" theme matching the intro screen ----------------------
# Replace with brand values here; nothing else hard-codes colors.
BG = "#14253f"             # page background (also in .streamlit/config.toml)
PANEL = "#1b3152"          # cards and sidebar
INK_PRIMARY = "#f0efec"
INK_SECONDARY = "#c3cad6"
INK_MUTED = "#93a0b5"
GRID = "#263c60"
AXIS = "#3a5278"
SURFACE = BG

# Categorical slots, fixed order: a series keeps its color whatever is filtered.
# Dark-mode steps of the reference palette, validated on BG.
SERIES_COLORS = {
    "Harmonized": "#3987e5",   # slot 1 blue
    "MODIS (raw)": "#d95926",  # slot 2 orange
    "VIIRS (raw)": "#199e70",  # slot 3 aqua
}
BAND_FILL = "rgba(57, 135, 229, 0.22)"   # harmonized uncertainty band

# Fire intensity, one warm hue from dim ember to bright flame (more = brighter,
# like fires seen from space at night). Used by both the calendar and the globe.
FIRE_RAMP = ["#5a2318", "#82301c", "#ab3f20", "#d35225", "#ee6b2c", "#f88a35", "#ffab3d"]
FIRE_RAMP_RGB = [tuple(int(h[i:i + 2], 16) for i in (1, 3, 5)) for h in FIRE_RAMP]
NO_FIRE = "rgba(205, 226, 251, 0.08)"     # calendar day with no fire

# Globe colors, the same as the intro screen's globe.
OCEAN_RGB = [29, 79, 138]
LAND_RGB = [207, 224, 211]
BORDER_RGB = [150, 168, 158]
GRATICULE_RGBA = [205, 226, 251, 45]

FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'
