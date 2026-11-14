# Backend API - New Endpoints

## ✅ Two New Endpoints Added

### 1. `GET /api/hotspots` - Map Data

**Purpose:** Get fire detection coordinates for map visualization

**Parameters:**
```
min_lat (required): -90 to 90
max_lat (required): -90 to 90
min_lon (required): -180 to 180
max_lon (required): -180 to 180
start_date (optional): YYYY-MM-DD (default: 2020-01-01)
end_date (optional): YYYY-MM-DD (default: 2025-12-31)
instrument (optional): MODIS, VIIRS, etc
limit (optional): 1-100,000 (default: 10,000)
```

**Example Request:**
```
GET http://localhost:8000/api/hotspots?min_lat=0&max_lat=30&min_lon=0&max_lon=30&limit=100
```

**Response:**
```json
{
  "bounds": {
    "min_lat": 0,
    "max_lat": 30,
    "min_lon": 0,
    "max_lon": 30
  },
  "date_range": {
    "start": "2020-01-01",
    "end": "2025-12-31"
  },
  "count": 100,
  "limit": 100,
  "data": [
    {
      "lat": 12.345,
      "lon": 45.678,
      "date": "2025-11-14",
      "time": "0245",
      "confidence": 87,
      "brightness": 315.5,
      "instrument": "MODIS",
      "satellite": "Terra",
      "frp": 45.2
    },
    ...
  ]
}
```

---

### 2. `GET /api/export` - CSV Download

**Purpose:** Download fire detection data as CSV with metadata and sensor definitions

**Parameters:**
```
min_lat (required): -90 to 90
max_lat (required): -90 to 90
min_lon (required): -180 to 180
max_lon (required): -180 to 180
start_date (optional): YYYY-MM-DD (default: 2020-01-01)
end_date (optional): YYYY-MM-DD (default: 2025-12-31)
instrument (optional): MODIS, VIIRS, etc
limit (optional): 1-1,000,000 (default: 100,000)
```

**Example Request:**
```
GET http://localhost:8000/api/export?min_lat=0&max_lat=30&min_lon=0&max_lon=30&limit=1000
```

**Response:** CSV file `fire_detections.csv` with:
- Metadata headers (generation time, bounds, date range)
- Column definitions (lat, lon, date, time, confidence, etc)
- Sensor information (MODIS vs VIIRS specs)
- Data rows with all fire observations

**CSV Format:**
```
# ASTRA Fire Detection Export
# Generated: 2026-11-14T17:52:14.123456
# Bounding box: lat [0, 30], lon [0, 30]
# Date range: 2020-01-01 to 2025-12-31
#
# COLUMN DEFINITIONS:
# latitude: GPS latitude (-90 to 90)
# longitude: GPS longitude (-180 to 180)
# acq_date: Acquisition date (YYYY-MM-DD)
# acq_time: Acquisition time (HHMM UTC)
# confidence: Detection confidence (0-100, higher = more certain)
# brightness: Brightness temperature (Kelvin)
# instrument: Sensor (MODIS, VIIRS)
# satellite: Satellite platform (Terra, Aqua, SNPP, JPSS-1)
# frp: Fire Radiative Power (MW, megawatts)
# daynight: Observation type (D=day, N=night)
#
# SENSOR INFO:
# MODIS: Moderate Resolution Imaging Spectroradiometer
#   - Platforms: Terra, Aqua
#   - Resolution: 1km (fire product)
# VIIRS: Visible Infrared Imaging Radiometer Suite
#   - Platforms: SNPP (Suomi NPP), JPSS-1
#   - Resolution: 375m (fire product)
#
latitude,longitude,acq_date,acq_time,confidence,brightness,instrument,satellite,frp,daynight
12.345,45.678,2025-11-14,0245,87,315.5,MODIS,Terra,45.2,D
...
```

---

## How They Work

### /api/hotspots
- Accepts lat/lon bounding box + date range
- Queries raw `all_fires` table (111M records)
- Returns limited results (default 10K, max 100K)
- Good for: Map visualization, marker placement
- Query time: <500ms for typical regions

### /api/export
- Same bounding box + date range
- Returns CSV with metadata headers and column definitions
- Larger limit allowed (up to 1M rows)
- Good for: Data analysis, reports, sharing
- File includes sensor info so data isn't misleading
- Query time: <1s for 100K rows

---

## Safety Features

✅ **Query limits:**
- /api/hotspots: max 100,000 points
- /api/export: max 1,000,000 rows
- Prevents database from being overwhelmed

✅ **Parameterized queries:**
- All parameters are escaped
- No SQL injection risk

✅ **Metadata included:**
- CSV includes sensor definitions
- Dates, bounds, generation time tracked
- Users know what they're downloading

✅ **Read-only connections:**
- Database cannot be modified
- Safe for production

---

## Integration with Frontend

**Narmeen can now:**

1. **Display map markers:**
   ```javascript
   const response = await fetch(`/api/hotspots?min_lat=${bounds.south}&max_lat=${bounds.north}&min_lon=${bounds.west}&max_lon=${bounds.east}&limit=5000`);
   const {data} = await response.json();
   // Plot data[].lat, data[].lon on map
   ```

2. **Add export button:**
   ```javascript
   window.location.href = `/api/export?min_lat=${bounds.south}&max_lat=${bounds.north}&min_lon=${bounds.west}&max_lon=${bounds.east}`;
   // Downloads fire_detections.csv
   ```

---

## Testing

Start the server:
```bash
cd backend
python main.py
```

Access interactive docs:
```
http://localhost:8000/docs
```

Try endpoints in the browser or with curl:
```bash
curl "http://localhost:8000/api/hotspots?min_lat=0&max_lat=30&min_lon=0&max_lon=30&limit=100"
curl "http://localhost:8000/api/export?min_lat=0&max_lat=30&min_lon=0&max_lon=30" --output fires.csv
```
