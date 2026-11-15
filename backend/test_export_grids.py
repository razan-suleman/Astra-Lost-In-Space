import tempfile
import unittest
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

import export_grids


class GridExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.datasets = (
            ("MODIS", root / "modis.duckdb", "all_fires"),
            ("VIIRS", root / "viirs.duckdb", "viirs_observations"),
        )
        for sensor, path, table in self.datasets:
            with duckdb.connect(str(path)) as db:
                db.execute(f"""CREATE TABLE {table} (
                    acq_date DATE, instrument VARCHAR, satellite VARCHAR,
                    latitude DOUBLE, longitude DOUBLE, frp DOUBLE, scan DOUBLE, track DOUBLE
                )""")
                if sensor == "MODIS":
                    rows = [
                        ("2024-01-01", sensor, "Terra", 0.0, 0.0, 2.0, 1.0, 2.0),
                        ("2024-01-01", sensor, "Terra", 0.0, 0.0, None, 3.0, None),
                        ("2024-01-01", sensor, "Aqua", 0.0, 0.0, -1.0, None, 2.0),
                        ("2024-01-02", sensor, "Terra", -0.0001, -0.0001, None, None, None),
                        ("2023-01-01", sensor, "Terra", 0.0, 0.0, 4.0, 1.0, 1.0),
                    ]
                else:
                    rows = [
                        ("2024-01-01", sensor, "N20", 0.0, 0.0, 5.0, 0.4, 0.5),
                        ("2024-01-01", sensor, "N", 0.0, 0.0, 6.0, 0.5, 0.5),
                        ("2023-01-01", sensor, "N", 0.0, 0.0, 7.0, 0.5, 0.5),
                    ]
                db.executemany(f"INSERT INTO {table} VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
        self.output = root / "delivery"

    def test_daily_sensor_satellite_cells_nulls_and_negative_floor(self):
        counts = export_grids.export_grids(self.output, self.datasets, sizes=(1, 5), year=2024)
        self.assertEqual(counts, {1: 5, 5: 5})
        for size in (1, 5):
            rows = pq.read_table(self.output / f"grid_{size}km.parquet").to_pylist()
            self.assertEqual(sum(row["detection_count"] for row in rows), 6)
            terra = next(row for row in rows if row["sensor"] == "MODIS" and row["satellite"] == "Terra"
                         and row["date"].isoformat() == "2024-01-01")
            self.assertEqual((terra["grid_x"], terra["grid_y"]), (0, 0))
            self.assertEqual((terra["detection_count"], terra["frp_valid_count"]), (2, 1))
            self.assertEqual((terra["frp_sum"], terra["frp_mean"]), (2.0, 2.0))
            self.assertEqual((terra["scan_mean"], terra["scan_valid_count"]), (2.0, 2))
            self.assertEqual((terra["track_mean"], terra["track_valid_count"]), (2.0, 1))
            self.assertEqual((terra["footprint_area_mean"], terra["footprint_valid_count"]), (2.0, 1))
            south_west = next(row for row in rows if row["date"].isoformat() == "2024-01-02")
            self.assertEqual((south_west["grid_x"], south_west["grid_y"]), (-1, -1))
            self.assertIsNone(south_west["frp_sum"])
            self.assertIsNone(south_west["footprint_area_mean"])
            self.assertEqual(south_west["frp_valid_count"], 0)
            self.assertEqual({row["satellite"] for row in rows}, {"Terra", "Aqua", "N", "N20"})
        report = (self.output / "data_quality_report.md").read_text(encoding="utf-8")
        self.assertIn("EPSG:6933", report)
        self.assertIn("N20 only", report)
        self.assertIn("Negative FRP values retained: 1", report)
        self.assertIn("| 2024 | Terra | 3 |", report)
        with self.assertRaises(FileExistsError):
            export_grids.export_grids(self.output, self.datasets, sizes=(1,), year=2024)

    def test_missing_database_and_invalid_coordinates_fail_without_output(self):
        self.datasets[1][1].unlink()
        with self.assertRaises(FileNotFoundError):
            export_grids.export_grids(self.output, self.datasets)
        self.assertFalse(self.output.exists())
        with duckdb.connect(str(self.datasets[0][1])) as db:
            db.execute("UPDATE all_fires SET latitude = 90 WHERE satellite = 'Aqua'")
        with self.assertRaises(ValueError):
            export_grids.export_grids(self.output, self.datasets[:1], sizes=(1,))
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
