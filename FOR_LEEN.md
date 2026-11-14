# 🔥 Fire Data Backend - Ready to Use!

## Quick Start

### 1. Start the server
```bash
cd backend
python main.py
```

### 2. Access the API

**Option A: Browser (Easiest)**
- Open: http://localhost:8000/docs
- Click any endpoint, test it out
- See responses in real-time

**Option B: Command Line**
```bash
curl http://localhost:8000/api/summary
curl http://localhost:8000/api/calendar
```

**Option C: Python**
```python
import duckdb
db = duckdb.connect('backend/fires.duckdb')
fires = db.execute("SELECT * FROM all_fires LIMIT 10").fetchall()
print(fires)
```

---

## Available Endpoints

| Endpoint | What it does |
|----------|-------------|
| `GET /api/calendar` | Fire data by month/region (for calendar viz) |
| `GET /api/summary` | Database stats |
| `GET /api/statistics` | Fire statistics |
| `GET /api/data?limit=10` | Raw fire records |
| `GET /api/query?sql=...` | Custom SQL queries |
| `GET /health` | Check if server is running |

---

## Calendar Endpoint (Main)

```
GET http://localhost:8000/api/calendar?region=Australia&year=2024
```

**Response:**
```json
{
  "months": [
    {
      "month": "2024-01-01",
      "region": "Australia",
      "fire_count": 1234,
      "days_active": 28,
      "avg_confidence": 87.5
    }
  ],
  "summary": {
    "total_fires": 1234,
    "regions": ["Australia", "Brazil", ...]
  }
}
```

---

## Database

**File:** `backend/fires.duckdb`

**Tables:**
- `all_fires` - Individual fire records
- `monthly_sensor_counts` - Monthly aggregated data
- `monthly_activity` - Monthly summary

**Columns in each fire record:**
- latitude, longitude (GPS location)
- acq_date, acq_time (detection date/time)
- confidence (0-100, how sure)
- brightness (temperature)
- instrument (MODIS/VIIRS)
- satellite (which satellite)
- region (geographic region)
- frp (fire radiative power)

---

## Frontend Integration (React Example)

```javascript
// Fetch calendar data
const response = await fetch('http://localhost:8000/api/calendar');
const data = await response.json();

// Filter by region and year
const response = await fetch('http://localhost:8000/api/calendar?region=Australia&year=2024');
const data = await response.json();

// Display data
data.months.forEach(month => {
  console.log(`${month.month}: ${month.fire_count} fires`);
});
```

---

## Troubleshooting

**"Connection refused"**
- Make sure server is running: `python main.py` in backend folder

**"Module not found"**
- Install dependencies: `pip install -r requirements.txt`

**No data showing**
- Database file exists: `backend/fires.duckdb`
- Check: http://localhost:8000/api/summary

---

## That's it! 🚀

Server is ready. Start it and integrate with your frontend!
