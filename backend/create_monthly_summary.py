import duckdb
import time

print("Creating monthly_sensor_counts summary table from 111M records...")
print("This will take 1-2 minutes...\n")

con = duckdb.connect("fires.duckdb", read_only=False)

start = time.time()

try:
    con.execute("DROP TABLE IF EXISTS monthly_sensor_counts")
except Exception as e:
    print(f"Warning: Could not drop existing table: {e}")

try:
    con.execute("""
        CREATE TABLE monthly_sensor_counts AS
        SELECT
            YEAR(acq_date) as year,
            MONTH(acq_date) as month,
            instrument,
            satellite,
            COUNT(*) as detection_count
        FROM all_fires
        GROUP BY YEAR(acq_date), MONTH(acq_date), instrument, satellite
    """)
    
    elapsed = time.time() - start
    
    total = con.execute("SELECT COUNT(*) FROM monthly_sensor_counts").fetchone()[0]
    print(f"[OK] Created monthly_sensor_counts with {total:,} rows in {elapsed:.1f}s\n")
    
    sample = con.execute("""
        SELECT year, month, instrument, satellite, detection_count
        FROM monthly_sensor_counts
        ORDER BY year DESC, month DESC
        LIMIT 10
    """).fetchall()
    
    print("Sample data:")
    for row in sample:
        print(f"  {row[0]}-{row[1]:02d} | {row[2]:8s} | {row[3]:8s} | {row[4]:,} detections")
    
    print("\n[OK] Done! Your /api/calendar endpoint is now optimized!")
    
except Exception as e:
    print(f"[ERROR] Failed to create summary table: {e}")
    raise
finally:
    con.close()
