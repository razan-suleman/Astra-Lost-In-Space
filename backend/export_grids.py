"""Export daily Australia observations on a shared EPSG:6933 grid."""

import argparse
import math
from pathlib import Path

import duckdb
import numpy as np
import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq
from pyproj import Transformer

BACKEND_DIR = Path(__file__).resolve().parent
DATASETS = (
    ("MODIS", BACKEND_DIR / "australia_fires.duckdb", "all_fires"),
    ("VIIRS", BACKEND_DIR / "australia_viirs.duckdb", "viirs_observations"),
)
GRID_SIZES_KM = (1, 2, 5, 10, 20)
SCHEMA = pa.schema([
    ("date", pa.date32()),
    ("sensor", pa.string()),
    ("satellite", pa.string()),
    ("grid_x", pa.int32()),
    ("grid_y", pa.int32()),
    ("detection_count", pa.int64()),
    ("frp_sum", pa.float64()),
    ("frp_mean", pa.float64()),
    ("frp_valid_count", pa.int64()),
    ("scan_mean", pa.float64()),
    ("scan_valid_count", pa.int64()),
    ("track_mean", pa.float64()),
    ("track_valid_count", pa.int64()),
    ("footprint_area_mean", pa.float64()),
    ("footprint_valid_count", pa.int64()),
])


def grid_observations(rows: pa.Table, size_km: int) -> pa.Table:
    """Project source rows and aggregate one sensor and year at a given size."""
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:6933", always_xy=True)
    longitude = rows["longitude"].combine_chunks().to_numpy()
    latitude = rows["latitude"].combine_chunks().to_numpy()
    x, y = transformer.transform(longitude, latitude, errcheck=True)
    if not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError("Projection returned non-finite coordinates")
    frame = pl.from_arrow(rows).with_columns(
        pl.Series("grid_x", np.floor(x / (size_km * 1000)).astype(np.int32)),
        pl.Series("grid_y", np.floor(y / (size_km * 1000)).astype(np.int32)),
    )
    result = frame.group_by("date", "sensor", "satellite", "grid_x", "grid_y").agg(
        pl.len().cast(pl.Int64).alias("detection_count"),
        pl.when(pl.col("frp").count() > 0).then(pl.col("frp").sum()).otherwise(None).alias("frp_sum"),
        pl.col("frp").mean().alias("frp_mean"),
        pl.col("frp").count().cast(pl.Int64).alias("frp_valid_count"),
        pl.col("scan").mean().alias("scan_mean"),
        pl.col("scan").count().cast(pl.Int64).alias("scan_valid_count"),
        pl.col("track").mean().alias("track_mean"),
        pl.col("track").count().cast(pl.Int64).alias("track_valid_count"),
        (pl.col("scan") * pl.col("track")).mean().alias("footprint_area_mean"),
        (pl.col("scan") * pl.col("track")).count().cast(pl.Int64).alias("footprint_valid_count"),
    )
    return result.select(SCHEMA.names).to_arrow().cast(SCHEMA)


def source_summary(sensor: str, db: duckdb.DuckDBPyConnection, table: str, year: int | None):
    where = "" if year is None else "WHERE year(acq_date) = ?"
    params = [] if year is None else [year]
    summary = db.execute(f"""
        SELECT COUNT(*), MIN(latitude), MAX(latitude), MIN(longitude), MAX(longitude),
               MIN(acq_date), MAX(acq_date),
               COUNT(*) FILTER (WHERE latitude IS NULL OR longitude IS NULL OR acq_date IS NULL
                   OR satellite IS NULL OR instrument IS NULL OR instrument <> ?
                   OR NOT isfinite(latitude) OR NOT isfinite(longitude)
                   OR latitude NOT BETWEEN -86 AND 86 OR longitude NOT BETWEEN -180 AND 180),
               COUNT(*) FILTER (WHERE frp IS NULL),
               COUNT(*) FILTER (WHERE scan IS NULL),
               COUNT(*) FILTER (WHERE track IS NULL),
               COUNT(*) FILTER (WHERE frp < 0),
               COUNT(*) FILTER (WHERE NOT isfinite(frp) OR NOT isfinite(scan) OR NOT isfinite(track))
        FROM {table} {where}
    """, [sensor] + params).fetchone()
    if summary[0] == 0:
        raise ValueError(f"No {sensor} observations match the requested period")
    if summary[7] or summary[12]:
        raise ValueError(f"{sensor} contains invalid coordinates, dates, sensor, satellite or numeric values")
    groups = db.execute(f"""
        SELECT year(acq_date), satellite, COUNT(*), SUM(frp), COUNT(frp)
        FROM {table} {where} GROUP BY 1, 2 ORDER BY 1, 2
    """, params).fetchall()
    return summary, groups


def verify_output(path: Path, expected: dict):
    with duckdb.connect() as db:
        groups = db.execute("""
            SELECT sensor, year(date), satellite, SUM(detection_count), SUM(frp_sum), SUM(frp_valid_count)
            FROM read_parquet(?) GROUP BY 1, 2, 3
        """, [str(path)]).fetchall()
        row_count = db.execute("SELECT COUNT(*) FROM read_parquet(?)", [str(path)]).fetchone()[0]
    actual = {(sensor, year, satellite): (count, frp, valid) for sensor, year, satellite, count, frp, valid in groups}
    if actual.keys() != expected.keys():
        raise ValueError(f"{path.name}: sensor/year/satellite groups do not match source")
    for key, (count, frp, valid) in actual.items():
        expected_count, expected_frp, expected_valid = expected[key]
        if count != expected_count or valid != expected_valid:
            raise ValueError(f"{path.name}: detection or FRP valid count mismatch for {key}")
        if (frp is None) != (expected_frp is None) or (
            frp is not None and not math.isclose(frp, expected_frp, rel_tol=1e-8, abs_tol=1e-5)
        ):
            raise ValueError(f"{path.name}: FRP sum mismatch for {key}")
    return row_count


def export_grids(output: Path, datasets=DATASETS, sizes=GRID_SIZES_KM, year: int | None = None):
    if not sizes or any(size not in GRID_SIZES_KM for size in sizes) or len(set(sizes)) != len(sizes):
        raise ValueError("Grid sizes must be unique values from 1, 2, 5, 10 and 20 km")
    for _, path, _ in datasets:
        if not path.is_file():
            raise FileNotFoundError(f"Source database not found: {path}")

    summaries = []
    expected = {}
    for sensor, path, table in datasets:
        with duckdb.connect(str(path), read_only=True) as db:
            summary, groups = source_summary(sensor, db, table, year)
        summaries.append((sensor, path, summary, groups))
        for source_year, satellite, count, frp, valid in groups:
            expected[(sensor, source_year, satellite)] = (count, frp, valid)

    output.mkdir(parents=True, exist_ok=False)
    partial_paths = {size: output / f"grid_{size}km.parquet.partial" for size in sizes}
    writers = {}
    try:
        for size in sizes:
            writers[size] = pq.ParquetWriter(str(partial_paths[size]), SCHEMA, compression="zstd")
        for sensor, path, summary, groups in summaries:
            table = next(table for name, _, table in datasets if name == sensor)
            with duckdb.connect(str(path), read_only=True) as db:
                for source_year in sorted({group[0] for group in groups}):
                    rows = db.execute(f"""
                        SELECT acq_date AS date, instrument AS sensor, satellite,
                               latitude, longitude, frp, scan, track
                        FROM {table} WHERE year(acq_date) = ?
                    """, [source_year]).to_arrow_table()
                    print(f"Processing {sensor} {source_year}: {rows.num_rows:,} observations", flush=True)
                    for size in sizes:
                        grid = grid_observations(rows, size)
                        writers[size].write_table(grid)
                        print(f"  {size} km: {grid.num_rows:,} occupied daily satellite cells", flush=True)
                        del grid
    finally:
        for writer in writers.values():
            writer.close()

    output_counts = {}
    for size, path in partial_paths.items():
        output_counts[size] = verify_output(path, expected)
        print(f"Verified {size} km: {output_counts[size]:,} rows", flush=True)

    report = [
        "# ASTRA Australia daily grid data quality report",
        "",
        "## Scope and source",
        "",
        f"- Period: {year if year is not None else 'all available years'}; "
        "the two source databases are read-only Australia extracts.",
        "- MODIS uses the Natural Earth Australia boundary; VIIRS uses NASA FIRMS "
        "Australia-labeled country files. These extents are not identical.",
        "- The imported S-NPP VIIRS archive for 2019 is missing; the available 2019 VIIRS records are N20 only.",
        "- Satellite codes are preserved as stored: MODIS Terra/Aqua and VIIRS N/N20.",
        "",
        "## Grid and aggregation",
        "",
        "- CRS: EPSG:6933 (WGS 84 / NSIDC EASE-Grid 2.0 Global), coordinates in metres.",
        "- Fixed grid origin: projected x = 0 m, y = 0 m for every sensor and grid size.",
        "- grid_x = floor(x / cell_size_m), grid_y = floor(y / cell_size_m). "
        "A cell spans [index × size, (index + 1) × size) along each axis.",
        f"- Cell sizes: {', '.join(str(size) for size in sizes)} km.",
        "- One row per UTC acquisition date, sensor, satellite and occupied cell. "
        "No unobserved or empty cells are filled with zero.",
        "- detection_count counts raw detections, not distinct fires. FRP sum and mean use "
        "non-null instantaneous FRP values in MW; the sum is not fire energy.",
        "- scan_mean and track_mean average non-null source pixel dimensions in km. "
        "footprint_area_mean averages scan × track in km² only where both are present; "
        "it is a footprint proxy, not burned area or a viewing-angle correction.",
        "- Each *_valid_count is the number of source detections used for that statistic; "
        "a statistic with no valid inputs is null. Negative source FRP values are retained.",
        "- Sensors are not harmonized. MODIS and VIIRS have different resolutions and detection characteristics.",
        "",
        "## Source quality",
        "",
    ]
    for sensor, path, summary, groups in summaries:
        count, min_lat, max_lat, min_lon, max_lon, min_date, max_date, _, null_frp, null_scan, null_track, negative_frp, _ = summary
        report.extend([
            f"### {sensor}",
            f"- Source: {path.name}; {count:,} observations, {min_date} to {max_date}.",
            f"- Observed bounds (WGS 84): latitude {min_lat} to {max_lat}; longitude {min_lon} to {max_lon}.",
            f"- Null values: FRP {null_frp:,}; scan {null_scan:,}; track {null_track:,}. "
            f"Negative FRP values retained: {negative_frp:,}.",
            "",
            "| Year | Satellite | Source detections |",
            "|---:|---|---:|",
        ])
        report.extend(f"| {source_year} | {satellite} | {count:,} |" for source_year, satellite, count, _, _ in groups)
        report.append("")
    report.extend([
        "## Verification and files",
        "",
        "For every file, detection counts, FRP valid counts, and FRP sums were independently "
        "re-read from Parquet and checked against the source for every sensor/year/satellite group.",
        "",
        "| File | Occupied daily satellite cells |",
        "|---|---:|",
    ])
    report.extend(f"| grid_{size}km.parquet | {output_counts[size]:,} |" for size in sizes)
    report.append("")
    report_path = output / "data_quality_report.md"
    report_path.write_text("\n".join(report), encoding="utf-8")
    for size, path in partial_paths.items():
        path.rename(output / f"grid_{size}km.parquet")
    return output_counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=BACKEND_DIR / "leen_grid_delivery")
    parser.add_argument("--year", type=int, help="Optional year for a smaller pilot")
    parser.add_argument("--sizes", type=int, nargs="+", default=list(GRID_SIZES_KM), choices=GRID_SIZES_KM)
    args = parser.parse_args()
    export_grids(args.output, sizes=args.sizes, year=args.year)


if __name__ == "__main__":
    main()
