"""Build static/splash_land.svg: a flat (equirectangular) world map for the splash globe.

The splash screen's globe is a circle with this map scrolling sideways inside
it, which looks like a rotating Earth. This script only needs to run once;
its output is committed to the repo.

Source: world-atlas land-110m.json (Natural Earth 1:110m, public domain), from npm:
    npm pack world-atlas@2 && tar -xzf world-atlas-*.tgz
Run:
    python scripts/build_splash_globe.py path/to/package/land-110m.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "static" / "splash_land.svg"
W, H = 1024, 512
LAND = "#cfe0d3"


def decode_arcs(topo: dict) -> list[list[tuple[float, float]]]:
    sx, sy = topo["transform"]["scale"]
    tx, ty = topo["transform"]["translate"]
    arcs = []
    for arc in topo["arcs"]:
        x = y = 0
        pts = []
        for dx, dy in arc:
            x += dx
            y += dy
            pts.append((x * sx + tx, y * sy + ty))
        arcs.append(pts)
    return arcs


def ring(indexes: list[int], arcs: list) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for i in indexes:
        a = arcs[i] if i >= 0 else arcs[~i][::-1]
        pts.extend(a if not pts else a[1:])
    return pts


def to_path(pts: list[tuple[float, float]]) -> str:
    """SVG path for one ring.

    Rings that cross the 180° line jump from +180 to -180, which would draw a
    line across the whole map. Unwrap them into continuous longitudes, then
    draw the ring again shifted by 360°, so both map edges show their half.
    """
    lons = [pts[0][0]]
    for (lon, _), (prev, _) in zip(pts[1:], pts[:-1]):
        d = lon - prev
        d -= 360 * round(d / 360)
        lons.append(lons[-1] + d)
    out = []
    shifts = [0, -360] if max(lons) > 180 else [0, 360] if min(lons) < -180 else [0]
    for shift in shifts:
        xy = [((lon + shift + 180) / 360 * W, (90 - lat) / 180 * H)
              for lon, (_, lat) in zip(lons, pts)]
        out.append("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in xy) + "Z")
    return "".join(out)


def main(src: str) -> None:
    topo = json.loads(Path(src).read_text())
    arcs = decode_arcs(topo)
    paths = []
    for g in topo["objects"]["land"]["geometries"]:
        polys = [g["arcs"]] if g["type"] == "Polygon" else g["arcs"]
        for poly in polys:
            paths.append("".join(to_path(ring(r, arcs)) for r in poly))
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">'
        f'<path fill="{LAND}" fill-rule="evenodd" d="{"".join(paths)}"/></svg>'
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(svg)
    print(f"-> {OUT} ({OUT.stat().st_size / 1e3:.0f} KB)")


if __name__ == "__main__":
    main(sys.argv[1])
