"""Generate SYNTHETIC placeholder data that follows the frontend data contract.

This lets the frontend be built and demoed before the real harmonization
pipeline is ready. The numbers are invented: they only imitate the shape
of real fire data (seasonality, MODIS/VIIRS overlap, sensor differences).

Output (see ARCHITECTURE.md, "Data contract"):
    data/cells.parquet       one row per grid cell
    data/fire_daily.parquet  one row per cell per day with any fire activity

Run:
    python scripts/generate_sample_data.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

OUT_DIR = Path(__file__).resolve().parents[1] / "data"

START, END = "2003-01-01", "2025-12-31"
MODIS_START = pd.Timestamp("2003-01-01")
VIIRS_START = pd.Timestamp("2012-01-20")      # S-NPP VIIRS 375 m record
TRANSITION = pd.Timestamp("2022-01-01")       # harmonized series switches to VIIRS→MODIS
CELL_DEG = 0.5
GRID_N = 12                                   # 12 x 12 cells per region
EARTH_R_KM = 6371.0088

# name, centre lat, centre lon, peak day-of-year, season width (days), base rate, trend/yr
REGIONS = [
    ("Cerrado, Brazil", -12.0, -47.0, 245, 35, 0.060, -0.015),
    ("Sahel, West Africa", 11.0, 2.0, 10, 40, 0.080, 0.005),
    ("Mainland SE Asia", 19.0, 101.0, 80, 25, 0.050, 0.010),
]
LANDCOVERS = np.array(["Savanna", "Cropland", "Forest", "Grassland"])


def cell_area_km2(lat_min: np.ndarray, lat_max: np.ndarray, dlon_deg: float) -> np.ndarray:
    """Exact area of a lat/lon cell on a sphere: R^2 * dlon * (sin(lat2) - sin(lat1))."""
    return (
        EARTH_R_KM**2
        * np.deg2rad(dlon_deg)
        * (np.sin(np.deg2rad(lat_max)) - np.sin(np.deg2rad(lat_min)))
    )


def seasonal_weight(doy: np.ndarray, peak: int, width: int) -> np.ndarray:
    """Circular Gaussian on the day of year, so seasons can wrap over New Year."""
    d = np.abs(doy - peak)
    d = np.minimum(d, 365 - d)
    return np.exp(-0.5 * (d / width) ** 2)


def main() -> None:
    rng = np.random.default_rng(42)
    dates = pd.date_range(START, END, freq="D")
    doy = dates.dayofyear.to_numpy()
    years = dates.year.to_numpy()

    cell_rows, daily_frames = [], []

    for r_idx, (name, clat, clon, peak, width, base, trend) in enumerate(REGIONS):
        offs = (np.arange(GRID_N) - GRID_N / 2 + 0.5) * CELL_DEG
        lat_c, lon_c = np.meshgrid(clat + offs, clon + offs, indexing="ij")
        lat_c, lon_c = lat_c.ravel(), lon_c.ravel()
        n_cells = lat_c.size

        cell_ids = np.array([f"R{r_idx}_{i:03d}" for i in range(n_cells)])
        lc = rng.choice(LANDCOVERS, size=n_cells, p=[0.4, 0.3, 0.15, 0.15])
        cell_weight = rng.gamma(2.0, 0.5, size=n_cells)  # some cells burn much more
        area = cell_area_km2(lat_c - CELL_DEG / 2, lat_c + CELL_DEG / 2, CELL_DEG)

        cell_rows.append(pd.DataFrame({
            "cell_id": cell_ids, "lat": lat_c, "lon": lon_c, "region": name,
            "landcover": lc, "area_km2": area,
        }))

        # Year-to-year variability plus a slow trend
        uniq_years = np.unique(years)
        yfac = np.exp(trend * (uniq_years - 2003) + rng.normal(0, 0.25, uniq_years.size))
        year_factor = yfac[np.searchsorted(uniq_years, years)]

        p_fire = base * seasonal_weight(doy, peak, width) * year_factor          # (days,)
        p = np.clip(np.outer(cell_weight, p_fire), 0, 0.95)                      # (cells, days)
        burning = rng.random(p.shape) < p
        ci, di = np.nonzero(burning)

        # "True" FRP (MW): many small fires, a few big ones
        true_frp = rng.lognormal(mean=3.0, sigma=1.2, size=ci.size)
        day = dates[di]

        # VIIRS sees more small fires; MODIS misses many of them
        p_modis = 1 - np.exp(-true_frp / 25.0)
        modis_seen = rng.random(ci.size) < p_modis
        modis_frp = np.where(modis_seen, true_frp * rng.lognormal(-0.4, 0.3, ci.size), 0.0)
        viirs_frp = true_frp * rng.lognormal(0.35, 0.25, ci.size)

        # Aqua orbit drift after 2021: MODIS sees less later in the afternoon
        drift = np.clip((np.asarray(day.year) - 2021) * 0.12, 0, 0.6)
        modis_frp *= 1 - drift

        has_modis = np.asarray(day >= MODIS_START)
        has_viirs = np.asarray(day >= VIIRS_START)
        modis_col = np.where(has_modis, modis_frp, np.nan)
        viirs_col = np.where(has_viirs, viirs_frp, np.nan)

        # Placeholder harmonization: VIIRS -> MODIS-equivalent via a fixed scale.
        # The real pipeline replaces this with the fitted two-part model.
        converted = viirs_frp * 0.42
        use_viirs = np.asarray(day >= TRANSITION)
        harmonized = np.where(use_viirs, converted, modis_frp)
        rel_unc = np.where(use_viirs, 0.35, 0.0)   # log-space 1-sigma for modelled values
        lo = harmonized * np.exp(-rel_unc)
        hi = harmonized * np.exp(rel_unc)

        df = pd.DataFrame({
            "cell_id": cell_ids[ci],
            "date": day,
            "modis_frp": modis_col,
            "viirs_frp": viirs_col,
            "harmonized_frp": harmonized,
            "harmonized_lo": lo,
            "harmonized_hi": hi,
            "source": np.where(use_viirs, "VIIRS→MODIS", "MODIS"),
            "n_valid": rng.integers(1, 5, size=ci.size).astype("int16"),
        })
        daily_frames.append(df)

    cells = pd.concat(cell_rows, ignore_index=True)
    daily = pd.concat(daily_frames, ignore_index=True).sort_values(["date", "cell_id"])
    daily["date"] = daily["date"].dt.date

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cells.to_parquet(OUT_DIR / "cells.parquet", index=False)
    daily.to_parquet(OUT_DIR / "fire_daily.parquet", index=False)
    print(f"cells: {len(cells):,} rows   fire_daily: {len(daily):,} rows -> {OUT_DIR}")


if __name__ == "__main__":
    main()
