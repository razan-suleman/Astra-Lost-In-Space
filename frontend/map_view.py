"""3D globe of grid cells, colored by fire activity, clickable to select cells.

Uses deck.gl's GlobeView, so cells are drawn on the curved surface of the
Earth instead of on a flat map. A globe can't use normal map tiles, so the
ocean, countries and a latitude/longitude grid are drawn as layers:

    1. ocean      SolidPolygonLayer covering the whole sphere
    2. countries  GeoJsonLayer from static/countries_50m.geojson
    3. graticule  PathLayer, a line every 15 degrees
    4. cells      PolygonLayer of fire cells (pickable, optionally extruded as 3D bars)

Later layers draw on top of earlier ones.
"""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np
import pandas as pd
import pydeck as pdk

from frontend import config

LAYER_ID = "cells"
DETECTION_LAYER_ID = "detection_cells"
DETECTION_RAMP = (
    (68, 1, 84), (59, 82, 139), (33, 145, 140), (94, 201, 98), (253, 231, 37),
)
# Served by Streamlit static file serving (enableStaticServing in .streamlit/config.toml).
COUNTRIES_URL = "app/static/countries_50m.geojson"

OCEAN_RGB = config.OCEAN_RGB
LAND_RGB = config.LAND_RGB
BORDER_RGB = config.BORDER_RGB
GRATICULE_RGBA = config.GRATICULE_RGBA


def _cell_size_deg(df: pd.DataFrame) -> float:
    lats = np.sort(df["lat"].unique())
    return float(np.min(np.diff(lats))) if lats.size > 1 else 0.5


def _bin_colors(values: pd.Series) -> list[list[int]]:
    """Bin into the sequential ramp on a log scale. Zero = no fill."""
    v = values.to_numpy(dtype=float)
    pos = v > 0
    if not pos.any():
        return [[0, 0, 0, 0]] * len(v)
    logv = np.log10(v[pos])
    lo, hi = logv.min(), logv.max()
    n = len(config.FIRE_RAMP_RGB)
    idx = np.zeros_like(logv, dtype=int) if hi == lo else np.clip(
        ((logv - lo) / (hi - lo) * n).astype(int), 0, n - 1)
    it = iter(list(config.FIRE_RAMP_RGB[i]) + [235] for i in idx)
    return [next(it) if p else [0, 0, 0, 0] for p in pos]


def detection_colors_and_legend(values: pd.Series) -> tuple[list[list[int]], list[tuple[str, int, int]]]:
    """Use a colorblind-friendly log ramp and report the observed range in each band."""
    counts = values.to_numpy(dtype=float)
    if not len(counts):
        return [], []
    if not np.isfinite(counts).all() or (counts <= 0).any():
        raise ValueError("Detection counts must be positive finite values")
    log_counts = np.log10(counts)
    lo, hi = log_counts.min(), log_counts.max()
    indices = np.zeros(len(counts), dtype=int) if lo == hi else np.clip(
        ((log_counts - lo) / (hi - lo) * len(DETECTION_RAMP)).astype(int), 0, len(DETECTION_RAMP) - 1
    )
    colors = [list(DETECTION_RAMP[index]) + [255] for index in indices]
    legend = []
    for index, rgb in enumerate(DETECTION_RAMP):
        band = counts[indices == index]
        if len(band):
            legend.append(("#" + "".join(f"{channel:02x}" for channel in rgb), int(band.min()), int(band.max())))
    return colors, legend


def cell_for_coordinates(latitude: float, longitude: float) -> tuple[float, float]:
    """Find the southwest corner of the half-degree cell containing a point."""
    if not math.isfinite(latitude) or not math.isfinite(longitude) or not (
        -90 <= latitude <= 90 and -180 <= longitude <= 180
    ):
        raise ValueError("Latitude must be between -90 and 90; longitude between -180 and 180.")
    return min(math.floor(latitude * 2), 179) / 2, min(math.floor(longitude * 2), 359) / 2


def _square(lat: float, lon: float, half: float, steps: int = 4) -> list[list[float]]:
    """Cell outline with extra points along each edge, so it follows the sphere's curve."""
    t = np.linspace(-half, half, steps + 1)
    s = [[lon + x, lat - half] for x in t]
    e = [[lon + half, lat + y] for y in t[1:]]
    n = [[lon + x, lat + half] for x in t[::-1][1:]]
    w = [[lon - half, lat + y] for y in t[::-1][1:]]
    return s + e + n + w


@lru_cache(maxsize=1)
def _graticule(step: int = 15) -> list[dict]:
    """Meridians and parallels, densely sampled so they curve around the globe."""
    lines = []
    for lon in range(-180, 180, step):
        lines.append({"path": [[lon, lat] for lat in range(-90, 91, 2)]})
    for lat in range(-75, 76, step):
        lines.append({"path": [[lon, lat] for lon in range(-180, 181, 2)]})
    return lines


def _base_layers() -> list[pdk.Layer]:
    ocean = pdk.Layer(
        "SolidPolygonLayer",
        id="ocean",
        data=[{"polygon": [[-180, 90], [0, 90], [180, 90], [180, -90], [0, -90], [-180, -90]]}],
        get_polygon="polygon",
        get_fill_color=OCEAN_RGB,
    )
    countries = pdk.Layer(
        "GeoJsonLayer",
        id="countries",
        data=COUNTRIES_URL,
        filled=True,
        stroked=True,
        get_fill_color=LAND_RGB,
        get_line_color=BORDER_RGB,
        line_width_min_pixels=0.6,
        get_line_width=1,
    )
    graticule = pdk.Layer(
        "PathLayer",
        id="graticule",
        data=_graticule(),
        get_path="path",
        get_color=GRATICULE_RGBA,
        width_min_pixels=0.5,
        get_width=1,
    )
    return [ocean, countries, graticule]


def cell_map(df: pd.DataFrame, unit: str, extrude: bool = False) -> pdk.Deck:
    """Globe with the region's cells. Streamlit dims unselected cells on selection."""
    half = _cell_size_deg(df) / 2
    data = df.copy()
    data["polygon"] = [_square(lat, lon, half) for lat, lon in zip(data["lat"], data["lon"])]
    data["fill"] = _bin_colors(data["value"])
    data["value_txt"] = [f"{v:,.1f}" for v in data["value"]]

    # 3D bars: tallest cell = 400 km, so heights read clearly at globe zoom.
    vmax = float(data["value"].max()) or 1.0
    data["height"] = np.where(data["value"] > 0, np.sqrt(data["value"] / vmax) * 400_000, 0.0)

    cells = pdk.Layer(
        "PolygonLayer",
        data=data[["cell_id", "landcover", "fire_days", "value_txt", "polygon", "fill", "height"]],
        id=LAYER_ID,
        get_polygon="polygon",
        get_fill_color="fill",
        filled=True,
        stroked=False,
        extruded=extrude,
        get_elevation="height",
        pickable=True,
        auto_highlight=True,
        highlight_color=[42, 120, 214, 120],
    )

    lat0, lon0 = float(df["lat"].mean()), float(df["lon"].mean())
    # GlobeView has no camera tilt, so for 3D bars rotate the globe instead:
    # looking from 35 degrees further from the equator puts the region near the
    # globe's edge, where bar heights are visible from the side.
    if extrude:
        lat0 = float(np.clip(lat0 + (35 if lat0 <= 0 else -35), -80, 80))
    view = pdk.ViewState(latitude=lat0, longitude=lon0, zoom=1.25)
    tooltip = {
        "html": "<b>{cell_id}</b> · {landcover}<br/>{value_txt} " + unit + " per year<br/>{fire_days} fire days",
        "style": {"fontFamily": config.FONT, "fontSize": "12px"},
    }
    return pdk.Deck(
        layers=_base_layers() + [cells],
        views=[pdk.View(type="_GlobeView", controller=True)],
        initial_view_state=view,
        tooltip=tooltip,
        map_provider=None,          # no flat basemap: the layers above are the map
        map_style=None,
        parameters={"cull": True},  # hide the far side of the globe
    )


def hotspot_map(points: list[dict]) -> pdk.Deck:
    """Globe displaying raw satellite detection points."""
    layer = pdk.Layer(
        "ScatterplotLayer",
        data=points,
        id="hotspots",
        get_position="[longitude, latitude]",
        get_fill_color=[255, 120, 45, 180],
        get_radius=5000,
        radius_min_pixels=2,
        radius_max_pixels=6,
        pickable=True,
    )
    return pdk.Deck(
        layers=_base_layers() + [layer],
        views=[pdk.View(type="_GlobeView", controller=True)],
        initial_view_state=pdk.ViewState(latitude=-25, longitude=135, zoom=1.25),
        tooltip={
            "html": "<b>{sensor} · {satellite}</b><br/>{date} {time_utc} UTC<br/>FRP: {frp_mw} MW",
            "style": {"fontFamily": config.FONT, "fontSize": "12px"},
        },
        map_provider=None,
        map_style=None,
        parameters={"cull": True},
    )


def detection_cell_map(
    cells: list[dict], cell_size: float, selected_cell: tuple[float, float] | None = None,
) -> pdk.Deck:
    """Globe of geographic cells colored by raw detection count."""
    half = cell_size / 2
    frame = pd.DataFrame(cells) if cells else pd.DataFrame(columns=["min_lat", "min_lon", "detection_count"])
    frame["polygon"] = [_square(lat + half, lon + half, half)
                        for lat, lon in zip(frame["min_lat"], frame["min_lon"])]
    frame["fill"], _ = detection_colors_and_legend(frame["detection_count"])
    frame["count_text"] = frame["detection_count"].map("{:,}".format)
    layer = pdk.Layer(
        "PolygonLayer",
        data=frame,
        id=DETECTION_LAYER_ID,
        get_polygon="polygon",
        get_fill_color="fill",
        filled=True,
        stroked=False,
        pickable=True,
        auto_highlight=True,
    )
    layers = _base_layers() + [layer]
    view_lat, view_lon = -25.0, 135.0
    if selected_cell is not None:
        lat, lon = selected_cell
        outline = [{"polygon": _square(lat + half, lon + half, half)}]
        for layer_id, color, width in (
            ("selected_cell_border", [0, 0, 0, 255], 5),
            ("selected_cell_outline", [255, 255, 255, 255], 2),
        ):
            layers.append(pdk.Layer(
                "PolygonLayer", id=layer_id, data=outline, get_polygon="polygon",
                filled=False, stroked=True, get_line_color=color, get_line_width=width,
                line_width_units="pixels", pickable=False,
            ))
        view_lat, view_lon = lat + half, lon + half
    return pdk.Deck(
        layers=layers,
        views=[pdk.View(type="_GlobeView", controller=True)],
        initial_view_state=pdk.ViewState(latitude=view_lat, longitude=view_lon, zoom=1.25),
        tooltip={
            "html": "<b>{count_text} detections</b><br/>Cell southwest corner: {min_lat}, {min_lon}",
            "style": {"fontFamily": config.FONT, "fontSize": "12px"},
        },
        map_provider=None,
        map_style=None,
        parameters={"cull": True},
    )


def selected_ids(event) -> list[str]:
    """Pull selected cell ids out of Streamlit's pydeck selection event."""
    try:
        objs = event.selection["objects"].get(LAYER_ID, [])
    except (AttributeError, KeyError, TypeError):
        return []
    return [o["cell_id"] for o in objs if "cell_id" in o]


def selected_detection_cell(event) -> tuple[float, float] | None:
    """Return the southwest corner of a selected real-data cell."""
    selection = event["selection"] if isinstance(event, dict) else event.selection
    objects = selection["objects"].get(DETECTION_LAYER_ID, [])
    if not objects:
        return None
    return objects[0]["min_lat"], objects[0]["min_lon"]
