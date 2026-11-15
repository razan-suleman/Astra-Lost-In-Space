from fastapi import Body, Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
import csv
import duckdb
import io
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal, Optional
from pydantic import BaseModel

app = FastAPI(title="Fire Data API", version="1.0.0")

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BACKEND_DIR = Path(__file__).resolve().parent
MODIS_DB_PATH = BACKEND_DIR / "australia_fires.duckdb"
VIIRS_DB_PATH = BACKEND_DIR / "australia_viirs.duckdb"
DB_PATH = BACKEND_DIR / "fires.duckdb"

REGION_DEFINITIONS = {
    "MODIS": "Points within the Natural Earth Australia boundary.",
    "VIIRS": "Rows from NASA FIRMS Australia-labeled country files.",
}
SENSOR_DEFINITIONS = {
    "MODIS": "MODIS active-fire product, 1 km nominal resolution.",
    "VIIRS": "VIIRS active-fire product, 375 m nominal resolution.",
}
DETECTION_DEFINITION = "Raw satellite detections, not individual fires or burned area."
FRP_DEFINITION = "Sum of instantaneous FRP values in MW, not fire energy."
Sensor = Literal["MODIS", "VIIRS"]
AUSTRALIA_DRAWING_BOUNDS = (-45.0, -9.0, 110.0, 155.0)
POLYGON_MAX_VERTICES = 100
POLYGON_EPSILON = 1e-12


class PolygonHistoryRequest(BaseModel):
    region: Literal["Australia"]
    sensor: Sensor
    coordinates: list[list[Any]]


@dataclass(frozen=True)
class ActivityFilters:
    region: Literal["Australia"]
    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float
    start_date: date
    end_date: date
    sensor: Optional[Sensor]


def activity_filters(
    min_lat: float = Query(..., ge=-90, le=90),
    max_lat: float = Query(..., ge=-90, le=90),
    min_lon: float = Query(..., ge=-180, le=180),
    max_lon: float = Query(..., ge=-180, le=180),
    start_date: date = Query(...),
    end_date: date = Query(...),
    region: Literal["Australia"] = "Australia",
    sensor: Optional[Sensor] = None,
) -> ActivityFilters:
    if min_lat > max_lat or min_lon > max_lon:
        raise HTTPException(status_code=422, detail="Invalid bounding box; minimums must not exceed maximums")
    if start_date > end_date:
        raise HTTPException(status_code=422, detail="start_date must not be after end_date")
    return ActivityFilters(region, min_lat, max_lat, min_lon, max_lon, start_date, end_date, sensor)


def selected_datasets(sensor: Optional[Sensor] = None) -> list[tuple[Path, str]]:
    datasets = [
        (MODIS_DB_PATH, "all_fires", "MODIS"),
        (VIIRS_DB_PATH, "viirs_observations", "VIIRS"),
    ]
    selected = [(path, table) for path, table, name in datasets if sensor is None or sensor == name]
    for path, _ in selected:
        if not path.is_file():
            raise HTTPException(status_code=503, detail=f"Database not found: {path.name}")
    return selected


def filter_parameters(filters: ActivityFilters) -> list[float | date]:
    return [
        filters.min_lat, filters.max_lat, filters.min_lon, filters.max_lon,
        filters.start_date, filters.end_date,
    ]


FILTER_SQL = """
    latitude BETWEEN ? AND ? AND longitude BETWEEN ? AND ?
    AND acq_date BETWEEN ? AND ?
"""


def open_database(path: Path) -> duckdb.DuckDBPyConnection:
    if not path.is_file():
        raise HTTPException(status_code=503, detail=f"Database not found: {path.name}")
    return duckdb.connect(str(path), read_only=True)


def get_db():
    """Create a read-only connection to the original MODIS database."""
    return open_database(DB_PATH)

@app.get("/health")
def health():
    """Check if API is running"""
    return {"status": "ok", "message": "API is running"}


@app.get("/api/regions")
def get_regions():
    """List regions currently supported by the calendar."""
    return {"regions": ["Australia"]}


@app.get("/api/summary")
def get_summary():
    """Get database summary"""
    db = get_db()
    
    all_fires_count = db.execute("SELECT COUNT(*) FROM all_fires").fetchone()[0]
    monthly_count = db.execute("SELECT COUNT(*) FROM monthly_activity").fetchone()[0]
    
    return {
        "all_fires_records": all_fires_count,
        "monthly_activity_records": monthly_count,
        "total_records": all_fires_count + monthly_count
    }

@app.get("/api/tables")
def list_tables():
    """List all tables in database"""
    db = get_db()
    tables = db.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
    ).fetchall()
    return {"tables": [t[0] for t in tables]}

@app.get("/api/data")
def get_data(limit: int = Query(10, ge=1, le=1000)):
    """Get fire data with limit"""
    db = get_db()
    result = db.execute(f"SELECT * FROM all_fires LIMIT {limit}").fetchall()
    columns = [desc[0] for desc in db.description]
    
    return {
        "columns": columns,
        "data": result,
        "count": len(result)
    }

@app.get("/api/query")
def query(sql: str = Query(...)):
    """Run custom SQL query (SELECT only)"""
    if not sql.strip().upper().startswith("SELECT"):
        return {"error": "Only SELECT queries allowed"}
    
    db = get_db()
    try:
        result = db.execute(sql).fetchall()
        return {
            "query": sql,
            "results": result,
            "count": len(result)
        }
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/statistics")
def get_statistics():
    """Get statistics from database"""
    db = get_db()
    
    stats = db.execute("""
        SELECT 
            COUNT(*) as total_fires,
            AVG(confidence) as avg_confidence,
            MAX(brightness) as max_brightness,
            MIN(brightness) as min_brightness,
            COUNT(DISTINCT region) as unique_regions
        FROM all_fires
    """).fetchone()
    
    return {
        "total_fires": stats[0],
        "avg_confidence": round(stats[1], 2) if stats[1] else 0,
        "max_brightness": round(stats[2], 2) if stats[2] else 0,
        "min_brightness": round(stats[3], 2) if stats[3] else 0,
        "unique_regions": stats[4]
    }

@app.get("/api/monthly-activity")
def get_monthly_activity():
    """Get monthly activity summary"""
    db = get_db()
    result = db.execute("SELECT * FROM monthly_activity ORDER BY month DESC").fetchall()
    columns = [desc[0] for desc in db.description]
    
    return {
        "columns": columns,
        "data": result,
        "count": len(result)
    }

@app.get("/api/calendar")
def get_calendar(
    region: Literal["Australia"] = "Australia",
    year: Optional[int] = Query(None, ge=2000, le=2100),
    granularity: Literal["day", "month"] = "month",
):
    """Get raw daily or monthly detections, separately by sensor and satellite."""
    period = "acq_date" if granularity == "day" else "CAST(date_trunc('month', acq_date) AS DATE)"
    where = "" if year is None else "WHERE acq_date >= ? AND acq_date < ?"
    params = [] if year is None else [date(year, 1, 1), date(year + 1, 1, 1)]
    data = []
    for path, table in selected_datasets():
        with open_database(path) as db:
            rows = db.execute(f"""
                SELECT {period} AS period, instrument, satellite,
                       COUNT(*) AS detection_count, SUM(frp) AS sum_frp_mw
                FROM {table}
                {where}
                GROUP BY 1, 2, 3
                ORDER BY 1, 2, 3
            """, params).fetchall()
        data.extend(
            {
                "date": row[0].isoformat(),
                "sensor": row[1],
                "satellite": row[2],
                "detection_count": row[3],
                "sum_frp_mw": row[4],
            }
            for row in rows
        )

    data.sort(key=lambda row: (row["date"], row["sensor"], row["satellite"]))
    return {
        "region": region,
        "year": year,
        "granularity": granularity,
        "harmonized": False,
        "definitions": {
            "detection_count": "Number of raw satellite detections, not number of fires or burned area.",
            "sum_frp_mw": "Sum of observed instantaneous fire radiative power values in MW; not fire energy.",
            "region": REGION_DEFINITIONS,
            "missing_periods": "No row does not establish that there were no fires or observations.",
        },
        "data": data,
    }


@app.get("/api/hotspots")
def get_hotspots(
    filters: ActivityFilters = Depends(activity_filters),
    limit: int = Query(1000, ge=1, le=10000),
):
    """Return the earliest matching points, up to a strict limit."""
    rows = []
    for path, table in selected_datasets(filters.sensor):
        with open_database(path) as db:
            rows.extend(db.execute(f"""
                SELECT latitude, longitude, acq_date, acq_time, instrument, satellite, frp
                FROM {table}
                WHERE {FILTER_SQL}
                ORDER BY acq_date, acq_time NULLS LAST, instrument NULLS LAST,
                         satellite NULLS LAST, latitude, longitude, frp NULLS LAST
                LIMIT ?
            """, filter_parameters(filters) + [limit + 1]).fetchall())

    def sort_key(row):
        def nullable(value):
            return (value is None, value if value is not None else "")

        return (row[2], nullable(row[3]), nullable(row[4]), nullable(row[5]),
                row[0], row[1], (row[6] is None, row[6] if row[6] is not None else 0))

    rows.sort(key=sort_key)
    truncated = len(rows) > limit
    rows = rows[:limit]
    return {
        "region": filters.region,
        "bounds": {
            "min_lat": filters.min_lat, "max_lat": filters.max_lat,
            "min_lon": filters.min_lon, "max_lon": filters.max_lon,
        },
        "start_date": filters.start_date.isoformat(),
        "end_date": filters.end_date.isoformat(),
        "sensor": filters.sensor,
        "limit": limit,
        "count": len(rows),
        "truncated": truncated,
        "data": [
            {
                "latitude": lat, "longitude": lon, "date": day.isoformat(),
                "time_utc": time, "sensor": instrument, "satellite": satellite, "frp_mw": frp,
            }
            for lat, lon, day, time, instrument, satellite, frp in rows
        ],
    }


@app.get("/api/hotspot-cells")
def get_hotspot_cells(filters: ActivityFilters = Depends(activity_filters)):
    """Aggregate all matching detections into half-degree geographic cells."""
    counts = {}
    for path, table in selected_datasets(filters.sensor):
        with open_database(path) as db:
            rows = db.execute(f"""
                SELECT
                    CASE WHEN latitude = 90 THEN 179 ELSE CAST(floor(latitude * 2) AS INTEGER) END AS lat_index,
                    CASE WHEN longitude = 180 THEN 359 ELSE CAST(floor(longitude * 2) AS INTEGER) END AS lon_index,
                    instrument,
                    COUNT(*) AS detection_count
                FROM {table}
                WHERE {FILTER_SQL}
                GROUP BY 1, 2, 3
            """, filter_parameters(filters)).fetchall()
        for lat_index, lon_index, instrument, count in rows:
            key = (instrument, lat_index, lon_index)
            counts[key] = counts.get(key, 0) + count

    return {
        "region": filters.region,
        "sensor": filters.sensor,
        "start_date": filters.start_date.isoformat(),
        "end_date": filters.end_date.isoformat(),
        "cell_size_degrees": 0.5,
        "harmonized": False,
        "detection_count": sum(counts.values()) if filters.sensor else None,
        "data": [
            {
                "sensor": instrument,
                "min_lat": lat_index / 2,
                "min_lon": lon_index / 2,
                "detection_count": count,
            }
            for (instrument, lat_index, lon_index), count in sorted(counts.items())
        ],
    }


@app.get("/api/cell-history")
def get_cell_history(
    min_lat: float = Query(..., ge=-90, le=89.5),
    min_lon: float = Query(..., ge=-180, le=179.5),
    sensor: Sensor = Query(...),
    region: Literal["Australia"] = "Australia",
):
    """Return monthly detections for one half-degree map cell."""
    if not (min_lat * 2).is_integer() or not (min_lon * 2).is_integer():
        raise HTTPException(status_code=422, detail="Cell coordinates must align to the 0.5-degree grid")
    max_lat, max_lon = min_lat + 0.5, min_lon + 0.5
    data = []
    for path, table in selected_datasets(sensor):
        with open_database(path) as db:
            rows = db.execute(f"""
                SELECT CAST(date_trunc('month', acq_date) AS DATE), instrument, satellite, COUNT(*)
                FROM {table}
                WHERE latitude >= ? AND (latitude < ? OR (latitude = 90 AND ? = 90))
                  AND longitude >= ? AND (longitude < ? OR (longitude = 180 AND ? = 180))
                GROUP BY 1, 2, 3
                ORDER BY 1, 2, 3
            """, [min_lat, max_lat, max_lat, min_lon, max_lon, max_lon]).fetchall()
        data.extend(
            {"date": month.isoformat(), "sensor": instrument, "satellite": satellite, "detection_count": count}
            for month, instrument, satellite, count in rows
        )
    return {
        "region": region,
        "sensor": sensor,
        "min_lat": min_lat,
        "min_lon": min_lon,
        "cell_size_degrees": 0.5,
        "data": data,
    }


def polygon_edges(coordinates: list[tuple[float, float]]) -> list[tuple[float, float, float, float]]:
    return [
        (coordinates[index][0], coordinates[index][1],
         coordinates[(index + 1) % len(coordinates)][0], coordinates[(index + 1) % len(coordinates)][1])
        for index in range(len(coordinates))
    ]


def orientation(a, b, c) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def point_on_segment(point, start, end) -> bool:
    return (
        abs(orientation(start, end, point)) <= POLYGON_EPSILON
        and min(start[0], end[0]) - POLYGON_EPSILON <= point[0] <= max(start[0], end[0]) + POLYGON_EPSILON
        and min(start[1], end[1]) - POLYGON_EPSILON <= point[1] <= max(start[1], end[1]) + POLYGON_EPSILON
    )


def segments_intersect(a, b, c, d) -> bool:
    ab_c, ab_d = orientation(a, b, c), orientation(a, b, d)
    cd_a, cd_b = orientation(c, d, a), orientation(c, d, b)
    if (
        ((ab_c > POLYGON_EPSILON and ab_d < -POLYGON_EPSILON)
         or (ab_c < -POLYGON_EPSILON and ab_d > POLYGON_EPSILON))
        and ((cd_a > POLYGON_EPSILON and cd_b < -POLYGON_EPSILON)
             or (cd_a < -POLYGON_EPSILON and cd_b > POLYGON_EPSILON))
    ):
        return True
    return (
        (abs(ab_c) <= POLYGON_EPSILON and point_on_segment(c, a, b))
        or (abs(ab_d) <= POLYGON_EPSILON and point_on_segment(d, a, b))
        or (abs(cd_a) <= POLYGON_EPSILON and point_on_segment(a, c, d))
        or (abs(cd_b) <= POLYGON_EPSILON and point_on_segment(b, c, d))
    )


def validate_polygon(raw_coordinates: list[list[Any]]) -> list[tuple[float, float]]:
    if not isinstance(raw_coordinates, list) or not 3 <= len(raw_coordinates) <= POLYGON_MAX_VERTICES:
        raise HTTPException(
            status_code=422,
            detail=f"coordinates must contain between 3 and {POLYGON_MAX_VERTICES} vertices",
        )

    coordinates = []
    min_lat, max_lat, min_lon, max_lon = AUSTRALIA_DRAWING_BOUNDS
    for point in raw_coordinates:
        if not isinstance(point, list) or len(point) != 2:
            raise HTTPException(status_code=422, detail="Each coordinate must be [longitude, latitude]")
        longitude, latitude = point
        if (
            isinstance(longitude, bool) or not isinstance(longitude, (int, float))
            or isinstance(latitude, bool) or not isinstance(latitude, (int, float))
            or not math.isfinite(longitude) or not math.isfinite(latitude)
        ):
            raise HTTPException(status_code=422, detail="Coordinates must be finite longitude/latitude numbers")
        longitude, latitude = float(longitude), float(latitude)
        if not (min_lon <= longitude <= max_lon and min_lat <= latitude <= max_lat):
            raise HTTPException(status_code=422, detail="Coordinates must be within the Australia drawing bounds")
        coordinates.append((longitude, latitude))

    if len(coordinates) > 1 and coordinates[0] == coordinates[-1]:
        coordinates.pop()
    if len(coordinates) < 3 or any(
        coordinates[index] == coordinates[(index + 1) % len(coordinates)]
        for index in range(len(coordinates))
    ):
        raise HTTPException(status_code=422, detail="Polygon must have at least three distinct consecutive vertices")

    twice_area = sum(
        coordinates[index][0] * coordinates[(index + 1) % len(coordinates)][1]
        - coordinates[(index + 1) % len(coordinates)][0] * coordinates[index][1]
        for index in range(len(coordinates))
    )
    if abs(twice_area) <= POLYGON_EPSILON:
        raise HTTPException(status_code=422, detail="Polygon must enclose a non-zero area")

    for index, current in enumerate(coordinates):
        previous = coordinates[index - 1]
        following = coordinates[(index + 1) % len(coordinates)]
        if (
            abs(orientation(previous, current, following)) <= POLYGON_EPSILON
            and (current[0] - previous[0]) * (following[0] - current[0])
            + (current[1] - previous[1]) * (following[1] - current[1]) < 0
        ):
            raise HTTPException(status_code=422, detail="Polygon edges must not overlap")

    edges = polygon_edges(coordinates)
    for first in range(len(edges)):
        a, b = edges[first][:2], edges[first][2:]
        for second in range(first + 1, len(edges)):
            if second == first + 1 or (first == 0 and second == len(edges) - 1):
                continue
            c, d = edges[second][:2], edges[second][2:]
            if segments_intersect(a, b, c, d):
                raise HTTPException(status_code=422, detail="Polygon must not self-intersect")
    return coordinates


@app.post("/api/polygon-history")
def get_polygon_history(request: PolygonHistoryRequest = Body(...)):
    """Return all available monthly detections inside a drawn Australia polygon."""
    coordinates = validate_polygon(request.coordinates)
    edges = polygon_edges(coordinates)
    min_lon = min(point[0] for point in coordinates)
    max_lon = max(point[0] for point in coordinates)
    min_lat = min(point[1] for point in coordinates)
    max_lat = max(point[1] for point in coordinates)
    parameters = [min_lon, max_lon, min_lat, max_lat, POLYGON_EPSILON]
    boundary_checks = []
    crossings = []
    for edge in edges:
        first = len(parameters) + 1
        x1, y1, x2, y2 = (f"${first + offset}" for offset in range(4))
        parameters.extend(edge)
        boundary_checks.append(f"""(
            abs(({x2} - {x1}) * (latitude - {y1}) - ({y2} - {y1}) * (longitude - {x1})) <= $5
            AND longitude BETWEEN least({x1}, {x2}) - $5 AND greatest({x1}, {x2}) + $5
            AND latitude BETWEEN least({y1}, {y2}) - $5 AND greatest({y1}, {y2}) + $5
        )""")
        crossings.append(f"""CASE
            WHEN ({y1} > latitude) != ({y2} > latitude)
             AND longitude < {x1} + (latitude - {y1}) * ({x2} - {x1}) / nullif({y2} - {y1}, 0)
            THEN 1 ELSE 0 END""")

    boundary_sql = " OR ".join(boundary_checks)
    crossings_sql = " + ".join(crossings)
    data = []
    for path, table in selected_datasets(request.sensor):
        with open_database(path) as db:
            rows = db.execute(f"""
                SELECT CAST(date_trunc('month', acq_date) AS DATE), satellite, COUNT(*)
                FROM {table}
                WHERE longitude BETWEEN $1 AND $2 AND latitude BETWEEN $3 AND $4
                  AND acq_date IS NOT NULL
                  AND (({boundary_sql}) OR (({crossings_sql}) % 2 = 1))
                GROUP BY 1, 2
                ORDER BY 1, 2 NULLS LAST
            """, parameters).fetchall()
        data.extend(
            {"date": month.isoformat(), "sensor": request.sensor,
             "satellite": satellite, "detection_count": count}
            for month, satellite, count in rows
        )
    return {
        "region": request.region,
        "sensor": request.sensor,
        "coordinates": [[longitude, latitude] for longitude, latitude in coordinates],
        "data": data,
    }


@app.get("/api/export")
def export_monthly(filters: ActivityFilters = Depends(activity_filters)):
    """Download monthly raw activity for the same filters as the map."""
    rows = []
    for path, table in selected_datasets(filters.sensor):
        with open_database(path) as db:
            rows.extend(db.execute(f"""
                SELECT CAST(date_trunc('month', acq_date) AS DATE), instrument, satellite,
                       COUNT(*), SUM(frp)
                FROM {table}
                WHERE {FILTER_SQL}
                GROUP BY 1, 2, 3
                ORDER BY 1, 2, 3
            """, filter_parameters(filters)).fetchall())
    rows.sort(key=lambda row: (row[0], row[1], row[2]))

    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow([
        "region", "min_lat", "max_lat", "min_lon", "max_lon", "start_date", "end_date",
        "month", "sensor", "satellite", "detection_count", "sum_frp_mw",
        "sensor_definition", "detection_definition", "frp_definition", "region_definition",
    ])
    for month, sensor, satellite, count, frp in rows:
        writer.writerow([
            filters.region, filters.min_lat, filters.max_lat, filters.min_lon, filters.max_lon,
            filters.start_date.isoformat(), filters.end_date.isoformat(), month.isoformat(),
            sensor, satellite, count, frp, SENSOR_DEFINITIONS[sensor], DETECTION_DEFINITION,
            FRP_DEFINITION, REGION_DEFINITIONS[sensor],
        ])
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="monthly_fire_activity.csv"'},
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)
