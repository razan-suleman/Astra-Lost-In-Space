import duckdb
from pathlib import Path

DB_PATH = Path("fires.duckdb")

if not DB_PATH.exists():
    print(f"Error: Database not found at {DB_PATH.resolve()}")
    exit(1)

con = duckdb.connect(str(DB_PATH), read_only=True)

try:
    print("=" * 70)
    print("TABLES:")
    print("=" * 70)
    tables = con.execute("SHOW TABLES").fetchall()
    for t in tables:
        print(f"  - {t[0]}")

    print("\n" + "=" * 70)
    print("ALL_FIRES SCHEMA:")
    print("=" * 70)
    schema = con.execute("DESCRIBE all_fires").fetchall()
    for col_name, col_type, *rest in schema:
        print(f"  {col_name:20} {col_type}")

    print("\n" + "=" * 70)
    print("SAMPLE ALL_FIRES ROWS:")
    print("=" * 70)
    sample = con.execute("SELECT * FROM all_fires LIMIT 3").fetchall()
    for row in sample:
        print(f"  {row}")

    print("\n" + "=" * 70)
    print("DISTINCT REGIONS:")
    print("=" * 70)
    regions = con.execute("""
        SELECT DISTINCT region
        FROM all_fires
        WHERE region IS NOT NULL
        ORDER BY region
    """).fetchall()
    for r in regions:
        print(f"  - {r[0]}")

    print("\n" + "=" * 70)
    print("DATE RANGE:")
    print("=" * 70)
    date_range = con.execute("""
        SELECT 
            MIN(acq_date) as min_date,
            MAX(acq_date) as max_date
        FROM all_fires
    """).fetchall()
    print(f"  Min: {date_range[0][0]}")
    print(f"  Max: {date_range[0][1]}")

    print("\n" + "=" * 70)
    print("INSTRUMENTS:")
    print("=" * 70)
    instruments = con.execute("""
        SELECT DISTINCT instrument
        FROM all_fires
        WHERE instrument IS NOT NULL
        ORDER BY instrument
    """).fetchall()
    for i in instruments:
        print(f"  - {i[0]}")

    print("\n" + "=" * 70)
    print("TOTAL RECORDS:")
    print("=" * 70)
    count = con.execute("SELECT COUNT(*) FROM all_fires").fetchone()[0]
    print(f"  {count:,} records")
    
    print("\n" + "=" * 70)
    print("[OK] Database inspection complete")
    print("=" * 70)

except Exception as e:
    print(f"Error: {e}")
    raise
finally:
    con.close()
