"""Offline Australia polygon drawing component.

``cells`` contains 0.5-degree cells with ``min_lon`` and ``min_lat`` keys.
The map covers 110–155° E and 45–9° S in a simple equirectangular projection.
On Apply, the return value is an open ring of [longitude, latitude] pairs.
Apply after Reset with no vertices returns [] as an explicit clear request;
None means no new request, so callers should retain their previous state.
The caller should pass the applied polygon back as ``initial`` on later runs.
The component does not validate self-intersections or restrict points to land.

Example::

    if "area" not in st.session_state:
        st.session_state.area = None
    result = draw_polygon(cells, st.session_state.area, key="area_drawer")
    if result is not None:
        st.session_state.area = result or None
"""

from __future__ import annotations

import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

_component = components.declare_component(
    "polygon_drawer", path=str(Path(__file__).parent / "static")
)


@lru_cache(maxsize=1)
def _australia_geometry() -> dict:
    source = Path(__file__).resolve().parents[2] / "static" / "countries_50m.geojson"
    with source.open(encoding="utf-8") as file:
        collection = json.load(file)
    return next(
        feature["geometry"]
        for feature in collection["features"]
        if feature.get("properties", {}).get("name") == "Australia"
    )


def draw_polygon(
    cells: list[dict], initial: list[list[float]] | None, key: str
) -> list[list[float]] | None:
    """Return a new polygon only on Apply, [] for an applied clear, else None."""
    event = _component(
        cells=cells,
        initial=initial,
        geometry=_australia_geometry(),
        key=key,
        default=None,
    )
    if not isinstance(event, dict):
        return None
    event_id = event.get("event_id")
    points = event.get("coordinates")
    if not isinstance(event_id, str) or not event_id or not isinstance(points, list):
        return None
    if points and not 3 <= len(points) <= 50:
        return None
    result = []
    for point in points:
        if not isinstance(point, list) or len(point) != 2:
            return None
        if any(isinstance(n, bool) or not isinstance(n, (int, float)) for n in point):
            return None
        lon, lat = point
        if not (math.isfinite(lon) and math.isfinite(lat) and 110 <= lon <= 155 and -45 <= lat <= -9):
            return None
        result.append([float(lon), float(lat)])
    state_key = "_polygon_drawer_event_" + hashlib.sha256(key.encode("utf-8")).hexdigest()
    if st.session_state.get(state_key) == event_id:
        return None
    st.session_state[state_key] = event_id
    return result
