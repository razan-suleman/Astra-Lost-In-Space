# Optimization Guide: Monthly Sensor Counts

## 

The calendar view needs the number of fire detections for each **month**, **region**, and **sensor/instrument**. The raw `all_fires` table contains one row per satellite observation. At the full NASA FIRMS data volume, that is approximately **82 million records**. Counting those rows for every calendar request is unnecessarily expensive.

This backend solves the problem with a pre-aggregated DuckDB table named `monthly_sensor_counts`. The API reads the small summary table instead of scanning the raw observations.

> **Repository note:** The checked-in sample database is intentionally small (`all_fires` has 1,000 rows), but the same query pattern is designed for the approximately 82M-row production dataset.

---

## 1. The Problem: 82M Records

A calendar request traditionally calculates counts directly from raw data:

```sql
-- Slow approach: scans and groups the raw observations on every request
SELECT
    MONTH(acq_date) AS month,
    instrument,
    COUNT(*) AS detection_count
FROM all_fires
WHERE region = 'USA'
  AND YEAR(acq_date) = 2024
GROUP BY MONTH(acq_date), instrument
ORDER BY month, instrument;
```

This approach has several costs:

- It reads a very large portion of `all_fires` for every request.
- `YEAR(acq_date)` and `MONTH(acq_date)` must be computed repeatedly.
- The same aggregation is recalculated when many users request the same year and region.
- API latency becomes unpredictable as the raw table grows.
- Database CPU and I/O are spent repeating work whose result changes only when source data changes.

For the full dataset, the raw query took **30+ seconds** in the original implementation. That is too slow for an interactive calendar.

---

## 2. The Solution: `monthly_sensor_counts`

The backend creates one compact row for each unique combination of:

- `year`
- `month`
- `region`
- `instrument`

The table schema is:

| Column | Meaning |
|---|---|
| `year` | Calendar year from `all_fires.acq_date` |
| `month` | Month number, 1–12 |
| `region` | Geographic region |
| `instrument` | Sensor/instrument, such as `MODIS` or `VIIRS` |
| `detection_count` | Number of raw observations in that group |

It is built by `backend/create_monthly_summary.py`:

```sql
CREATE TABLE monthly_sensor_counts AS
SELECT
    YEAR(acq_date) AS year,
    MONTH(acq_date) AS month,
    region,
    instrument,
    COUNT(*) AS detection_count
FROM all_fires
GROUP BY YEAR(acq_date), MONTH(acq_date), region, instrument;
```

This is a lossless summary for the calendar use case: it preserves every count the calendar needs, without retaining individual fire coordinates or other raw columns in the response path.

---

## 3. How the Optimization Works

### Before: aggregate on every request

```text
HTTP request
    -> scan up to 82M raw rows
    -> compute year/month for rows
    -> filter by region and year
    -> group by month and instrument
    -> return result
```

### After: look up precomputed groups

```text
Data load/update
    -> scan all_fires once
    -> group by year/month/region/instrument
    -> store monthly_sensor_counts

HTTP request
    -> filter a small summary table by region and year
    -> return rows immediately
```

The optimized API query is:

```sql
SELECT month, instrument, detection_count
FROM monthly_sensor_counts
WHERE region = ? AND year = ?
ORDER BY month, instrument;
```

Parameters are passed separately by the FastAPI handler, so `region` and `year` are not interpolated into SQL. The endpoint returns the sensor name as `sensor` in the JSON response:

```json
{
  "region": "USA",
  "year": 2024,
  "harmonized": false,
  "metric": "raw_hotspot_detections",
  "data": [
    {"month": 1, "sensor": "MODIS", "count": 19},
    {"month": 1, "sensor": "VIIRS", "count": 21}
  ]
}
```

`detection_count` is a raw hotspot-detection count. It is not a deduplicated fire count and should not be described as a count of unique incidents.

---

## 4. Performance Impact

| Operation | Before | After |
|---|---:|---:|
| Calendar query | Scans and groups raw observations | Reads precomputed groups |
| Work repeated per request | Yes | No |
| Full-data response time | 30+ seconds in the original implementation | Typically under 100 ms in the optimized implementation |
| Result size | Only requested rows, but expensive to produce | Only requested summary rows |

The exact result depends on hardware, DuckDB version, database storage, and cache state. The key improvement is reducing the request-time data volume from potentially tens of millions of rows to the small number of monthly groups for one region and year.

For example, with two instruments, one region, and one year, the response contains at most about 24 month/instrument groups (and fewer when a month has no observations), rather than reading all 82M records during the request.

To measure the local database:

```bash
cd backend
python create_monthly_summary.py
```

Then use the API or DuckDB to validate the lookup:

```bash
python -c "import duckdb; c=duckdb.connect('fires.duckdb', read_only=True); print(c.execute(\"SELECT COUNT(*) FROM monthly_sensor_counts\").fetchone()[0]); c.close()"
```

---

## 5. API Endpoints

### `GET /api/calendar` — optimized calendar data

Required query parameter: `region`  
Optional query parameter: `year` (default `2024`, allowed range `2000`–`2100`)

```bash
curl "http://localhost:8000/api/calendar?region=USA&year=2024"
```

Returns monthly counts by sensor. If no summary rows exist, the API returns HTTP `404`.

### `GET /api/regions`

Lists regions available in the raw table:

```bash
curl http://localhost:8000/api/regions
```

### `GET /api/summary`

Returns raw and monthly-activity row counts. This endpoint is useful for a basic database check:

```bash
curl http://localhost:8000/api/summary
```

### `GET /api/statistics`

Returns raw-data statistics, including total detections, confidence, brightness, regions, and date range:

```bash
curl http://localhost:8000/api/statistics
```

### `GET /health`

Checks that the API process is running:

```bash
curl http://localhost:8000/health
```

Start the service with:

```bash
cd backend
python main.py
```

Interactive OpenAPI documentation is available at `http://localhost:8000/docs`.

---

## 6. Examples for Narmeen

These examples show the normal workflow for Narmeen when integrating the calendar with a frontend or checking a result manually.

### Request USA data for 2024

```bash
curl "http://localhost:8000/api/calendar?region=USA&year=2024"
```

### Request Global data for 2024

```bash
curl "http://localhost:8000/api/calendar?region=Global&year=2024"
```

### JavaScript calendar integration

```javascript
async function loadCalendar(region, year = 2024) {
  const params = new URLSearchParams({ region, year: String(year) });
  const response = await fetch(
    `http://localhost:8000/api/calendar?${params}`
  );

  if (!response.ok) {
    throw new Error(`Calendar request failed: ${response.status}`);
  }

  const result = await response.json();
  return result.data;
}

const rows = await loadCalendar("USA", 2024);
for (const row of rows) {
  console.log(`Month ${row.month}: ${row.sensor} = ${row.count}`);
}
```

### Python client example

```python
import requests

response = requests.get(
    "http://localhost:8000/api/calendar",
    params={"region": "USA", "year": 2024},
    timeout=10,
)
response.raise_for_status()
calendar = response.json()
print(calendar["region"], calendar["year"])
print(calendar["data"])
```

### Direct DuckDB verification

Use this when Narmeen needs to compare the summary against raw data:

```sql
-- Optimized lookup
SELECT month, instrument, detection_count
FROM monthly_sensor_counts
WHERE region = 'USA' AND year = 2024
ORDER BY month, instrument;

-- Correctness check against raw observations
SELECT
    MONTH(acq_date) AS month,
    instrument,
    COUNT(*) AS detection_count
FROM all_fires
WHERE region = 'USA' AND YEAR(acq_date) = 2024
GROUP BY MONTH(acq_date), instrument
ORDER BY month, instrument;
```

The two result sets should match. If they do not, rebuild the summary table.

---

## 7. Maintaining the Table

### Rebuild after loading or changing raw data

`monthly_sensor_counts` is derived data. Whenever rows are inserted, deleted, corrected, or replaced in `all_fires`, rebuild it before relying on calendar results:

```bash
cd backend
python create_monthly_summary.py
```

The script drops the existing summary and recreates it from the current `all_fires` table. It also prints the number of summary rows and a sample of the newest data.

### Recommended update procedure

1. Back up `backend/fires.duckdb` before a production rebuild.
2. Load or modify `all_fires`.
3. Run `python create_monthly_summary.py`.
4. Check the script reports `[SUCCESS]`.
5. Verify a known region/year through `/api/calendar`.
6. Restart the API only if the deployment process requires it; each request opens a read-only DuckDB connection.

Example backup on Windows PowerShell:

```powershell
Copy-Item backend\fires.duckdb backend\fires_backup.duckdb
python backend\create_monthly_summary.py
```

### Basic integrity checks

```sql
-- Confirm the table exists and has rows
SELECT COUNT(*) FROM monthly_sensor_counts;

-- Look for invalid month values
SELECT *
FROM monthly_sensor_counts
WHERE month < 1 OR month > 12;

-- Confirm no duplicate summary keys
SELECT year, month, region, instrument, COUNT(*) AS rows_in_group
FROM monthly_sensor_counts
GROUP BY year, month, region, instrument
HAVING COUNT(*) > 1;
```

The final query should return no rows. A rebuild is preferred over manually editing the summary table because the summary is entirely reproducible from `all_fires`.

### Operational notes

- Keep `monthly_sensor_counts` in the same `fires.duckdb` file as `all_fires`.
- Do not treat the summary as an independent source of truth.
- Run rebuilds after each complete data import, not after every individual row.
- For a very large import, build once after the import finishes to avoid repeated full-table scans.
- Coordinate rebuilds with writes because the current script drops and recreates the table; do not run it concurrently with API traffic against a database that must remain continuously available.
- If future requirements need daily data, confidence averages, or deduplicated incidents, create a separate summary with explicitly documented semantics rather than changing the meaning of `detection_count`.

---

## File Reference

- `backend/main.py` — FastAPI endpoints, including the optimized `/api/calendar` query.
- `backend/create_monthly_summary.py` — rebuild script for `monthly_sensor_counts`.
- `backend/fires.duckdb` — DuckDB database containing `all_fires` and derived tables.
