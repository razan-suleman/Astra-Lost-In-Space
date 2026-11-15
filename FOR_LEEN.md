# Fire data backend

## Run

Install `backend/requirements.txt`, place `australia_fires.duckdb` and
`australia_viirs.duckdb` in `backend/`, then run:

```powershell
python backend\main.py
```

API documentation: http://localhost:8000/docs

## Australia activity

- `GET /health`: server status.
- `GET /api/regions`: available calendar regions (currently Australia only).
- `GET /api/calendar?region=Australia&year=2024`: monthly activity.
- `GET /api/calendar?region=Australia&year=2024&granularity=day`: daily activity.

`year` is optional; omit it to query the available history. The `data` array
contains one row per period, sensor, and satellite. `date` is the day or the
first day of the month. `detection_count` counts raw satellite detections, not
individual fires or burned area. `sum_frp_mw` sums instantaneous FRP values in
MW; it is not fire energy. Values have not been harmonized between sensors.

MODIS uses the Natural Earth Australia boundary; VIIRS uses NASA FIRMS
Australia-labeled country files. These geographic definitions may differ.
Periods without rows are not necessarily fire-free or observed.
The imported S-NPP VIIRS archives do not include 2019; N20 has 2019 data.

## Map and CSV

All three endpoints use the same required filters: `min_lat`, `max_lat`, `min_lon`,
`max_lon`, `start_date` and `end_date` (inclusive, `YYYY-MM-DD`). `region`
defaults to Australia. The optional `sensor` is `MODIS` or `VIIRS`.
Longitude bounds must not cross the antimeridian.

```text
/api/hotspots?min_lat=-40&max_lat=-10&min_lon=110&max_lon=155&start_date=2024-01-01&end_date=2024-01-31&limit=1000
/api/hotspot-cells?min_lat=-40&max_lat=-10&min_lon=110&max_lon=155&start_date=2024-01-01&end_date=2024-12-31&sensor=MODIS
/api/export?min_lat=-40&max_lat=-10&min_lon=110&max_lon=155&start_date=2024-01-01&end_date=2024-01-31
```

`/api/hotspots` returns coordinates, date, UTC acquisition time, sensor,
satellite and FRP in MW. The default limit is 1,000 and the maximum is 10,000.
When `truncated` is true, the returned points are the earliest matching
observations, not a representative sample.

`/api/hotspot-cells` accepts the same filters and groups all matching
detections into 0.5-degree latitude/longitude cells. Each cell reports its
southwest corner (`min_lat`, `min_lon`) and `detection_count`; the response
includes the total detection count when a sensor is selected. If omitted,
the total is null and rows are separated by sensor (satellites are combined
within each sensor). Cells are half-open, except that the north/east world
edges include 90° latitude and 180° longitude. The real-data map uses these
cells for the entire selected year rather than the limited point endpoint.

`/api/cell-history?min_lat=-30&min_lon=130&sensor=MODIS` returns monthly
counts by satellite across all years for one 0.5-degree map cell. Minimum
coordinates must align to the grid. The same half-open cell boundaries used
by `/api/hotspot-cells` apply, including the north and east world edges.

`/api/export` downloads monthly counts and summed FRP, separated by sensor and
satellite. Rows include the filters and sensor, metric and region definitions.
For partial months, totals include only the selected dates. An empty result
downloads a CSV containing only the column headers.

The database files are local data and are not included in the repository.
The existing `/api/query` endpoint accepts arbitrary SQL and is for trusted
local development only; do not expose it publicly.

## Daily grids for harmonization

Install `backend/requirements.txt`, then run:

```powershell
python backend\export_grids.py
```

This creates `backend/leen_grid_delivery/` with daily 1, 2, 5, 10 and 20 km
Parquet grids and a data-quality report. The output directory must not already
exist; generated data files are not tracked by Git. To make a pilot instead,
specify a new output directory, for example:

```powershell
python backend\export_grids.py --year 2024 --sizes 5 10 --output backend\grid_pilot_2024
```

Each dataset keeps sensors and satellites separate, retains missing values, and
contains only occupied cells. The report documents the shared EPSG:6933 grid
origin, units, data limitations, source counts and output verification. The
grids do not harmonize the sensors or correct viewing geometry.
