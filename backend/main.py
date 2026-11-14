from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import duckdb
from pathlib import Path
import csv
import io
from datetime import datetime

app = FastAPI(
    title="ASTRA Fire Data API",
    version="1.0.0",
    description="NASA satellite fire observation data for calendar visualization"
)

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = Path(__file__).resolve().parent / "fires.duckdb"

def get_db():
    """Create read-only database connection"""
    if not DB_PATH.exists():
        raise RuntimeError(f"Database not found: {DB_PATH}")
    return duckdb.connect(str(DB_PATH), read_only=True)

@app.get("/health")
def health():
    """Check if API is running"""
    return {"status": "ok", "message": "ASTRA API is running"}

@app.get("/api/regions")
def get_regions():
    """Get available regions"""
    con = get_db()
    try:
        regions = con.execute("""
            SELECT DISTINCT region
            FROM all_fires
            WHERE region IS NOT NULL
            ORDER BY region
        """).fetchall()
        return {
            "regions": [r[0] for r in regions]
        }
    finally:
        con.close()

@app.get("/api/calendar")
def get_calendar(
    region: str = Query(..., description="Region name (e.g., 'USA', 'Global')"),
    year: int = Query(2024, ge=2000, le=2100, description="Year")
):
    """
    Get monthly fire detections by sensor for a region and year.
    
    OPTIMIZED: Uses pre-computed monthly_sensor_counts table instead of scanning 82M rows.
    Response time: <100ms (was 30+ seconds with raw data).
    """
    con = get_db()
    
    try:
        # Query pre-computed summary table (FAST!)
        rows = con.execute("""
            SELECT month, instrument, detection_count
            FROM monthly_sensor_counts
            WHERE region = ? AND year = ?
            ORDER BY month, instrument
        """, [region, year]).fetchall()
    finally:
        con.close()
    
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"No observations for region '{region}' in {year}"
        )
    
    return {
        "region": region,
        "year": year,
        "harmonized": False,
        "metric": "raw_hotspot_detections",
        "data": [
            {
                "month": month,
                "sensor": instrument,
                "count": count
            }
            for month, instrument, count in rows
        ]
    }

@app.get("/api/summary")
def get_summary():
    """Get database summary"""
    con = get_db()
    try:
        all_fires_count = con.execute("SELECT COUNT(*) FROM all_fires").fetchone()[0]
        monthly_count = con.execute("SELECT COUNT(*) FROM monthly_activity").fetchone()[0]
        
        return {
            "all_fires_records": all_fires_count,
            "monthly_activity_records": monthly_count,
            "total_records": all_fires_count + monthly_count
        }
    finally:
        con.close()

@app.get("/api/statistics")
def get_statistics():
    """Get statistics from database"""
    con = get_db()
    try:
        stats = con.execute("""
            SELECT 
                COUNT(*) as total_fires,
                AVG(confidence) as avg_confidence,
                MAX(brightness) as max_brightness,
                MIN(brightness) as min_brightness,
                COUNT(DISTINCT region) as unique_regions,
                MIN(acq_date) as min_date,
                MAX(acq_date) as max_date
            FROM all_fires
        """).fetchone()
        
        return {
            "total_fires": stats[0],
            "avg_confidence": round(stats[1], 2) if stats[1] else 0,
            "max_brightness": round(stats[2], 2) if stats[2] else 0,
            "min_brightness": round(stats[3], 2) if stats[3] else 0,
            "unique_regions": stats[4],
            "date_range": {
                "start": str(stats[5]),
                "end": str(stats[6])
            }
        }
    finally:
        con.close()

@app.get("/api/hotspots")
def get_hotspots(
    min_lat: float = Query(..., ge=-90, le=90, description="Min latitude"),
    max_lat: float = Query(..., ge=-90, le=90, description="Max latitude"),
    min_lon: float = Query(..., ge=-180, le=180, description="Min longitude"),
    max_lon: float = Query(..., ge=-180, le=180, description="Max longitude"),
    start_date: str = Query("2020-01-01", description="Start date (YYYY-MM-DD)"),
    end_date: str = Query("2025-12-31", description="End date (YYYY-MM-DD)"),
    instrument: str = Query(None, description="Filter by instrument (MODIS, VIIRS, etc)"),
    limit: int = Query(10000, ge=1, le=100000, description="Max points to return")
):
    """
    Get hotspot coordinates for map visualization.
    
    Returns geographic points with date, confidence, and sensor info.
    Limited to prevent overwhelming the frontend.
    """
    con = get_db()
    
    try:
        query = """
            SELECT 
                latitude,
                longitude,
                acq_date,
                acq_time,
                confidence,
                brightness,
                instrument,
                satellite,
                frp
            FROM all_fires
            WHERE latitude BETWEEN ? AND ?
              AND longitude BETWEEN ? AND ?
              AND acq_date BETWEEN ? AND ?
        """
        params = [min_lat, max_lat, min_lon, max_lon, start_date, end_date]
        
        if instrument:
            query += " AND instrument = ?"
            params.append(instrument)
        
        query += f" LIMIT {limit}"
        
        rows = con.execute(query, params).fetchall()
        
    finally:
        con.close()
    
    if not rows:
        raise HTTPException(
            status_code=404,
            detail="No observations found for the specified area and date range"
        )
    
    return {
        "bounds": {
            "min_lat": min_lat,
            "max_lat": max_lat,
            "min_lon": min_lon,
            "max_lon": max_lon
        },
        "date_range": {
            "start": start_date,
            "end": end_date
        },
        "count": len(rows),
        "limit": limit,
        "data": [
            {
                "lat": row[0],
                "lon": row[1],
                "date": str(row[2]),
                "time": str(row[3]),
                "confidence": row[4],
                "brightness": row[5],
                "instrument": row[6],
                "satellite": row[7],
                "frp": row[8]
            }
            for row in rows
        ]
    }

@app.get("/api/export")
def export_data(
    min_lat: float = Query(..., ge=-90, le=90, description="Min latitude"),
    max_lat: float = Query(..., ge=-90, le=90, description="Max latitude"),
    min_lon: float = Query(..., ge=-180, le=180, description="Min longitude"),
    max_lon: float = Query(..., ge=-180, le=180, description="Max longitude"),
    start_date: str = Query("2020-01-01", description="Start date (YYYY-MM-DD)"),
    end_date: str = Query("2025-12-31", description="End date (YYYY-MM-DD)"),
    instrument: str = Query(None, description="Filter by instrument"),
    limit: int = Query(100000, ge=1, le=1000000, description="Max rows to export")
):
    """
    Export fire detection data as CSV.
    
    Includes metadata headers with definitions and sensor information.
    """
    con = get_db()
    
    try:
        query = """
            SELECT 
                latitude,
                longitude,
                acq_date,
                acq_time,
                confidence,
                brightness,
                instrument,
                satellite,
                frp,
                daynight
            FROM all_fires
            WHERE latitude BETWEEN ? AND ?
              AND longitude BETWEEN ? AND ?
              AND acq_date BETWEEN ? AND ?
        """
        params = [min_lat, max_lat, min_lon, max_lon, start_date, end_date]
        
        if instrument:
            query += " AND instrument = ?"
            params.append(instrument)
        
        query += f" LIMIT {limit}"
        
        rows = con.execute(query, params).fetchall()
        
    finally:
        con.close()
    
    if not rows:
        raise HTTPException(
            status_code=404,
            detail="No observations found for the specified area and date range"
        )
    
    # Build CSV in memory
    output = io.StringIO()
    
    # Write metadata headers
    output.write("# ASTRA Fire Detection Export\n")
    output.write(f"# Generated: {datetime.now().isoformat()}\n")
    output.write(f"# Bounding box: lat [{min_lat}, {max_lat}], lon [{min_lon}, {max_lon}]\n")
    output.write(f"# Date range: {start_date} to {end_date}\n")
    output.write("#\n")
    output.write("# COLUMN DEFINITIONS:\n")
    output.write("# latitude: GPS latitude (-90 to 90)\n")
    output.write("# longitude: GPS longitude (-180 to 180)\n")
    output.write("# acq_date: Acquisition date (YYYY-MM-DD)\n")
    output.write("# acq_time: Acquisition time (HHMM UTC)\n")
    output.write("# confidence: Detection confidence (0-100, higher = more certain)\n")
    output.write("# brightness: Brightness temperature (Kelvin)\n")
    output.write("# instrument: Sensor (MODIS, VIIRS)\n")
    output.write("# satellite: Satellite platform (Terra, Aqua, SNPP, JPSS-1)\n")
    output.write("# frp: Fire Radiative Power (MW, megawatts)\n")
    output.write("# daynight: Observation type (D=day, N=night)\n")
    output.write("#\n")
    output.write("# SENSOR INFO:\n")
    output.write("# MODIS: Moderate Resolution Imaging Spectroradiometer\n")
    output.write("#   - Platforms: Terra, Aqua\n")
    output.write("#   - Resolution: 1km (fire product)\n")
    output.write("# VIIRS: Visible Infrared Imaging Radiometer Suite\n")
    output.write("#   - Platforms: SNPP (Suomi NPP), JPSS-1\n")
    output.write("#   - Resolution: 375m (fire product)\n")
    output.write("#\n")
    
    # Write CSV data
    writer = csv.writer(output)
    writer.writerow([
        "latitude", "longitude", "acq_date", "acq_time",
        "confidence", "brightness", "instrument", "satellite", "frp", "daynight"
    ])
    
    for row in rows:
        writer.writerow(row)
    
    # Return as downloadable file
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=fire_detections.csv"}
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)
