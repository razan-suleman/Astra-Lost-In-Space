"""Build static/countries_50m.geojson from the world-atlas TopoJSON.

The globe map has no background tiles, so it draws country shapes itself.
This script only needs to run once; its output is committed to the repo.

Source: world-atlas (Natural Earth 1:50m, public domain), from npm:
    npm pack world-atlas@2 && tar -xzf world-atlas-*.tgz
Run:
    python scripts/build_world_geojson.py path/to/package/countries-50m.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "static" / "countries_50m.geojson"


def decode_arcs(topo: dict) -> list[list[list[float]]]:
    """Undo TopoJSON quantization and delta encoding."""
    sx, sy = topo["transform"]["scale"]
    tx, ty = topo["transform"]["translate"]
    arcs = []
    for arc in topo["arcs"]:
        x = y = 0
        pts = []
        for dx, dy in arc:
            x += dx
            y += dy
            pts.append([round(x * sx + tx, 3), round(y * sy + ty, 3)])
        arcs.append(pts)
    return arcs


def ring(indexes: list[int], arcs: list) -> list[list[float]]:
    pts: list[list[float]] = []
    for i in indexes:
        a = arcs[i] if i >= 0 else arcs[~i][::-1]
        pts.extend(a if not pts else a[1:])  # shared endpoints appear once
    return pts


def to_geometry(g: dict, arcs: list) -> dict | None:
    if g["type"] == "Polygon":
        return {"type": "Polygon", "coordinates": [ring(r, arcs) for r in g["arcs"]]}
    if g["type"] == "MultiPolygon":
        return {"type": "MultiPolygon",
                "coordinates": [[ring(r, arcs) for r in poly] for poly in g["arcs"]]}
    return None


def main(src: str) -> None:
    topo = json.loads(Path(src).read_text())
    arcs = decode_arcs(topo)
    feats = []
    for g in topo["objects"]["countries"]["geometries"]:
        geom = to_geometry(g, arcs)
        if geom:
            feats.append({"type": "Feature",
                          "properties": {"name": g.get("properties", {}).get("name", "")},
                          "geometry": geom})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":")))
    print(f"{len(feats)} countries -> {OUT} ({OUT.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main(sys.argv[1])
