import asyncio
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

import duckdb

import main


async def request(path, params=None, method="GET", body=None):
    messages = []
    request_body = json.dumps(body, allow_nan=True).encode("utf-8") if body is not None else b""
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": urlencode(params or {}).encode(),
        "headers": [(b"content-type", b"application/json")] if method == "POST" else [],
        "client": ("127.0.0.1", 1234),
        "server": ("test", 80),
        "root_path": "",
    }

    async def receive():
        return {"type": "http.request", "body": request_body, "more_body": False}

    async def send(message):
        messages.append(message)

    await main.app(scope, receive, send)
    response = next(message for message in messages if message["type"] == "http.response.start")
    body = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
    if dict(response["headers"])[b"content-type"].startswith(b"text/csv"):
        return response["status"], body.decode("utf-8")
    return response["status"], json.loads(body)


class CalendarTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.modis = root / "modis.duckdb"
        self.viirs = root / "viirs.duckdb"
        for path, table, rows in (
            (self.modis, "all_fires", [
                ("2024-01-02", "MODIS", "Terra", 2.0, -30.0, 130.0, "0900"),
                ("2024-01-02", "MODIS", "Terra", 3.5, -30.0, 130.0, "0910"),
                ("2023-12-31", "MODIS", "Aqua", 4.0, -30.0, 130.0, "0900"),
            ]),
            (self.viirs, "viirs_observations", [
                ("2024-01-02", "VIIRS", "N20", 8.0, -30.0, 130.0, "0800"),
                ("2024-02-29", "VIIRS", "N", 1.5, -20.0, 140.0, "1000"),
            ]),
        ):
            with duckdb.connect(str(path)) as db:
                db.execute(f"""CREATE TABLE {table} (
                    acq_date DATE, instrument VARCHAR, satellite VARCHAR, frp DOUBLE,
                    latitude DOUBLE, longitude DOUBLE, acq_time VARCHAR
                )""")
                db.executemany(f"INSERT INTO {table} VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
        self.paths = patch.multiple(main, MODIS_DB_PATH=self.modis, VIIRS_DB_PATH=self.viirs)
        self.paths.start()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.paths.stop)

    def get(self, path, **params):
        return asyncio.run(request(path, params))

    def post(self, path, body):
        return asyncio.run(request(path, method="POST", body=body))

    def test_regions_and_monthly_results_keep_sensors_separate(self):
        self.assertEqual(self.get("/api/regions"), (200, {"regions": ["Australia"]}))
        status, body = self.get("/api/calendar", region="Australia", year=2024)
        self.assertEqual(status, 200)
        self.assertFalse(body["harmonized"])
        self.assertEqual(body["data"], [
            {"date": "2024-01-01", "sensor": "MODIS", "satellite": "Terra", "detection_count": 2, "sum_frp_mw": 5.5},
            {"date": "2024-01-01", "sensor": "VIIRS", "satellite": "N20", "detection_count": 1, "sum_frp_mw": 8.0},
            {"date": "2024-02-01", "sensor": "VIIRS", "satellite": "N", "detection_count": 1, "sum_frp_mw": 1.5},
        ])

    def test_daily_results_and_empty_year(self):
        status, body = self.get("/api/calendar", year=2024, granularity="day")
        self.assertEqual(status, 200)
        self.assertEqual([row["date"] for row in body["data"]], ["2024-01-02", "2024-01-02", "2024-02-29"])
        status, body = self.get("/api/calendar", year=2025)
        self.assertEqual(status, 200)
        self.assertEqual(body["data"], [])

    def test_invalid_filters_and_missing_database(self):
        for params in ({"region": "Brazil"}, {"year": 1999}, {"granularity": "week"}):
            with self.subTest(params=params):
                self.assertEqual(self.get("/api/calendar", **params)[0], 422)
        self.viirs.unlink()
        status, body = self.get("/api/calendar", year=2024)
        self.assertEqual(status, 503)
        self.assertIn("viirs.duckdb", body["detail"])
        self.assertFalse(self.viirs.exists())

    def test_legacy_connection_is_read_only(self):
        with patch.object(main, "DB_PATH", self.modis):
            with main.get_db() as db:
                with self.assertRaises(duckdb.Error):
                    db.execute("CREATE TABLE should_not_exist (id INTEGER)")

    def test_hotspots_limit_order_and_sensor_filter(self):
        filters = {
            "min_lat": -31, "max_lat": -19, "min_lon": 129, "max_lon": 141,
            "start_date": "2024-01-02", "end_date": "2024-02-29",
        }
        status, body = self.get("/api/hotspots", **filters, limit=2)
        self.assertEqual(status, 200)
        self.assertEqual(body["count"], 2)
        self.assertTrue(body["truncated"])
        self.assertEqual([(row["sensor"], row["time_utc"]) for row in body["data"]],
                         [("VIIRS", "0800"), ("MODIS", "0900")])
        status, body = self.get("/api/hotspots", **filters, sensor="VIIRS")
        self.assertEqual(status, 200)
        self.assertEqual(body["count"], 2)
        self.assertFalse(body["truncated"])
        self.assertEqual(body["data"][1]["date"], "2024-02-29")

    def test_monthly_export_uses_same_filters(self):
        filters = {
            "min_lat": -30, "max_lat": -20, "min_lon": 130, "max_lon": 140,
            "start_date": "2024-01-02", "end_date": "2024-02-29",
        }
        status, body = self.get("/api/export", **filters)
        self.assertEqual(status, 200)
        rows = list(csv.DictReader(io.StringIO(body)))
        self.assertEqual([(r["month"], r["sensor"], r["satellite"], r["detection_count"]) for r in rows], [
            ("2024-01-01", "MODIS", "Terra", "2"),
            ("2024-01-01", "VIIRS", "N20", "1"),
            ("2024-02-01", "VIIRS", "N", "1"),
        ])
        self.assertEqual(rows[0]["sum_frp_mw"], "5.5")
        self.assertEqual(rows[0]["start_date"], "2024-01-02")
        self.assertIn("not individual fires", rows[0]["detection_definition"])
        self.assertIn("Natural Earth", rows[0]["region_definition"])
        self.assertIn("375 m", rows[1]["sensor_definition"])
        status, body = self.get("/api/export", **filters, sensor="VIIRS")
        self.assertEqual(status, 200)
        self.assertEqual({row["sensor"] for row in csv.DictReader(io.StringIO(body))}, {"VIIRS"})

    def test_cells_group_full_period_with_sensor_and_boundary_rules(self):
        with duckdb.connect(str(self.modis)) as db:
            db.executemany("INSERT INTO all_fires VALUES (?, ?, ?, ?, ?, ?, ?)", [
                ("2024-12-31", "MODIS", "Aqua", 1.0, -30.01, 130.49, "1200"),
                ("2024-12-31", "MODIS", "Aqua", 1.0, -30.0, 130.49, "1200"),
                ("2024-12-31", "MODIS", "Aqua", 1.0, -30.0, 130.5, "1200"),
                ("2024-12-31", "MODIS", "Aqua", 1.0, 90.0, 180.0, "1200"),
                ("2024-12-31", "MODIS", "Aqua", 1.0, -90.0, -180.0, "1200"),
            ])
        filters = {
            "min_lat": -90, "max_lat": 90, "min_lon": -180, "max_lon": 180,
            "start_date": "2024-01-01", "end_date": "2024-12-31",
        }
        status, body = self.get("/api/hotspot-cells", **filters, sensor="MODIS")
        self.assertEqual(status, 200)
        self.assertEqual(body["cell_size_degrees"], 0.5)
        self.assertEqual(body["detection_count"], 7)
        self.assertEqual(
            {(r["min_lat"], r["min_lon"]): r["detection_count"] for r in body["data"]},
            {(-90, -180): 1, (-30.5, 130): 1, (-30, 130): 3,
             (-30, 130.5): 1, (89.5, 179.5): 1},
        )
        status, body = self.get("/api/hotspot-cells", **filters)
        self.assertEqual(status, 200)
        self.assertFalse(body["harmonized"])
        self.assertIsNone(body["detection_count"])
        overlapping = [r for r in body["data"] if (r["min_lat"], r["min_lon"]) == (-30, 130)]
        self.assertEqual({r["sensor"]: r["detection_count"] for r in overlapping}, {"MODIS": 3, "VIIRS": 1})
        status, body = self.get("/api/hotspot-cells", **{**filters, "end_date": "2024-01-02", "min_lat": -30},
                                sensor="MODIS")
        self.assertEqual(status, 200)
        self.assertEqual(body["detection_count"], 2)

    def test_cell_history_matches_grid_boundaries_and_separates_satellites(self):
        with duckdb.connect(str(self.modis)) as db:
            db.executemany("INSERT INTO all_fires VALUES (?, ?, ?, ?, ?, ?, ?)", [
                ("2024-01-03", "MODIS", "Aqua", 1.0, -30.0, 130.49, "1200"),
                ("2024-01-04", "MODIS", "Aqua", 1.0, -29.5, 130.0, "1200"),
                ("2024-01-04", "MODIS", "Aqua", 1.0, -30.0, 130.5, "1200"),
                ("2024-01-04", "MODIS", "Aqua", 1.0, -30.01, 130.0, "1200"),
                ("2024-01-05", "MODIS", "Aqua", 1.0, 90.0, 180.0, "1200"),
            ])
        params = {"min_lat": -30, "min_lon": 130, "sensor": "MODIS"}
        status, body = self.get("/api/cell-history", **params)
        self.assertEqual(status, 200)
        self.assertEqual(body["data"], [
            {"date": "2023-12-01", "sensor": "MODIS", "satellite": "Aqua", "detection_count": 1},
            {"date": "2024-01-01", "sensor": "MODIS", "satellite": "Aqua", "detection_count": 1},
            {"date": "2024-01-01", "sensor": "MODIS", "satellite": "Terra", "detection_count": 2},
        ])
        status, body = self.get("/api/cell-history", **{**params, "sensor": "VIIRS"})
        self.assertEqual(status, 200)
        self.assertEqual(body["data"][0]["detection_count"], 1)
        self.assertEqual(len(body["data"]), 1)
        status, body = self.get("/api/cell-history", min_lat=89.5, min_lon=179.5, sensor="MODIS")
        self.assertEqual(status, 200)
        self.assertEqual(body["data"][0]["detection_count"], 1)
        for override in ({"min_lat": -30.1}, {"min_lon": 180}, {"sensor": "OTHER"}, {"region": "Brazil"}):
            self.assertEqual(self.get("/api/cell-history", **{**params, **override})[0], 422)
        self.viirs.unlink()
        self.assertEqual(self.get("/api/cell-history", **params)[0], 200)
        self.assertEqual(self.get("/api/cell-history", **{**params, "sensor": "VIIRS"})[0], 503)

    def test_polygon_history_includes_boundary_and_groups_by_satellite(self):
        with duckdb.connect(str(self.modis)) as db:
            db.executemany("INSERT INTO all_fires VALUES (?, ?, ?, ?, ?, ?, ?)", [
                ("2024-01-03", "MODIS", "Aqua", 1.0, -30.0, 129.0, "1200"),
                ("2024-01-04", "MODIS", "Aqua", 1.0, -29.5, 130.5, "1200"),
                ("2024-01-05", "MODIS", "Aqua", 1.0, -29.5, 131.5, "1200"),
            ])
        polygon = [[129, -31], [131, -31], [131, -29], [129, -29]]
        status, body = self.post("/api/polygon-history", {
            "region": "Australia", "sensor": "MODIS", "coordinates": polygon,
        })
        self.assertEqual(status, 200)
        self.assertEqual(body["region"], "Australia")
        self.assertEqual(body["sensor"], "MODIS")
        self.assertEqual(body["coordinates"], polygon)
        self.assertEqual(body["data"], [
            {"date": "2023-12-01", "sensor": "MODIS", "satellite": "Aqua", "detection_count": 1},
            {"date": "2024-01-01", "sensor": "MODIS", "satellite": "Aqua", "detection_count": 2},
            {"date": "2024-01-01", "sensor": "MODIS", "satellite": "Terra", "detection_count": 2},
        ])
        status, body = self.post("/api/polygon-history", {
            "region": "Australia", "sensor": "VIIRS", "coordinates": polygon,
        })
        self.assertEqual(status, 200)
        self.assertEqual(body["data"], [
            {"date": "2024-01-01", "sensor": "VIIRS", "satellite": "N20", "detection_count": 1},
        ])
        closed = polygon + [polygon[0]]
        status, body = self.post("/api/polygon-history", {
            "region": "Australia", "sensor": "MODIS", "coordinates": closed,
        })
        self.assertEqual(status, 200)
        self.assertEqual(body["coordinates"], polygon)

    def test_polygon_history_concave_boundaries_and_full_date_range(self):
        with duckdb.connect(str(self.viirs)) as db:
            db.executemany("INSERT INTO viirs_observations VALUES (?, ?, ?, ?, ?, ?, ?)", [
                ("1999-12-31", "VIIRS", "N", 1.0, -30.5, 129.5, "1200"),
                ("2101-02-01", "VIIRS", "N", 1.0, -30.0, 130.0, "1200"),
                ("2024-01-03", "VIIRS", "N", 1.0, -29.5, 130.5, "1200"),
                ("2024-01-04", "VIIRS", "N", 1.0, -29.5, 129.5, "1200"),
                ("2024-01-05", "VIIRS", "N", 1.0, -31.0, 130.0, "1200"),
                ("2024-01-06", "VIIRS", "N", 1.0, -29.0, 129.0, "1200"),
            ])
        # A concave notch excludes (-29.5, 130.5) despite being inside the bbox.
        polygon = [[129, -31], [131, -31], [131, -30], [130, -30],
                   [130, -29], [129, -29]]
        for coordinates in (polygon, list(reversed(polygon))):
            status, body = self.post("/api/polygon-history", {
                "region": "Australia", "sensor": "VIIRS", "coordinates": coordinates,
            })
            self.assertEqual(status, 200)
            self.assertEqual(body["data"], [
                {"date": "1999-12-01", "sensor": "VIIRS", "satellite": "N", "detection_count": 1},
                {"date": "2024-01-01", "sensor": "VIIRS", "satellite": "N", "detection_count": 3},
                {"date": "2024-01-01", "sensor": "VIIRS", "satellite": "N20", "detection_count": 1},
                {"date": "2101-02-01", "sensor": "VIIRS", "satellite": "N", "detection_count": 1},
            ])

    def test_polygon_history_diagonal_edges_and_vertices(self):
        with duckdb.connect(str(self.viirs)) as db:
            db.executemany("INSERT INTO viirs_observations VALUES (?, ?, ?, ?, ?, ?, ?)", [
                ("2024-01-03", "VIIRS", "N", 1.0, -30.0, 130.0, "1200"),
                ("2024-01-04", "VIIRS", "N", 1.0, -30.5, 129.5, "1200"),
                ("2024-01-05", "VIIRS", "N", 1.0, -29.5, 130.5, "1200"),
                ("2024-01-06", "VIIRS", "N", 1.0, -29.0, 131.0, "1200"),
            ])
        status, body = self.post("/api/polygon-history", {
            "region": "Australia", "sensor": "VIIRS",
            "coordinates": [[129, -31], [131, -31], [131, -29]],
        })
        self.assertEqual(status, 200)
        self.assertEqual(body["data"], [
            {"date": "2024-01-01", "sensor": "VIIRS", "satellite": "N", "detection_count": 4},
            {"date": "2024-01-01", "sensor": "VIIRS", "satellite": "N20", "detection_count": 1},
        ])

    def test_polygon_history_rejects_malformed_and_invalid_polygons(self):
        valid = {"region": "Australia", "sensor": "MODIS",
                 "coordinates": [[129, -31], [131, -31], [131, -29], [129, -29]]}
        invalid_requests = [
            {},
            {**valid, "region": "Brazil"},
            {**valid, "sensor": "OTHER"},
            {**valid, "coordinates": [[129, -31], [131, -31]]},
            {**valid, "coordinates": [[129, -31], [131, -31], [131]]},
            {**valid, "coordinates": [[129, -31], [float("inf"), -31], [131, -29]]},
            {**valid, "coordinates": [[129, -31], [float("nan"), -31], [131, -29]]},
            {**valid, "coordinates": [[129, -31], [131, -31], [131, -29], [129, -29], [129, -31], [130, -30]]},
            {**valid, "coordinates": [[129, -31], [131, -29], [129, -29], [131, -31]]},
            {**valid, "coordinates": [[129, -31], [130, -30], [131, -29]]},
            {**valid, "coordinates": [[129, -31], [131, -31], [130, -31], [130, -29], [129, -29]]},
            {**valid, "coordinates": [[109, -31], [131, -31], [131, -29]]},
            {**valid, "coordinates": [[129, -31], [131, -31], [131, -29], [129, -29]] * 26},
        ]
        for body in invalid_requests:
            with self.subTest(body=body):
                self.assertEqual(self.post("/api/polygon-history", body)[0], 422)

    def test_shared_filter_validation_and_empty_results(self):
        filters = {
            "min_lat": -30, "max_lat": -20, "min_lon": 130, "max_lon": 140,
            "start_date": "2024-01-02", "end_date": "2024-02-29",
        }
        for path in ("/api/hotspots", "/api/hotspot-cells", "/api/export"):
            for override in (
                {"min_lat": -10}, {"min_lon": 150},
                {"start_date": "2024-03-01"}, {"end_date": "bad-date"},
                {"region": "Brazil"}, {"sensor": "OTHER"},
            ):
                with self.subTest(path=path, override=override):
                    self.assertEqual(self.get(path, **{**filters, **override})[0], 422)
            status, body = self.get(path, **{**filters, "start_date": "2025-01-01", "end_date": "2025-01-31"})
            self.assertEqual(status, 200)
            if path == "/api/hotspots":
                self.assertEqual(body["data"], [])
                self.assertFalse(body["truncated"])
            elif path == "/api/hotspot-cells":
                self.assertEqual(body["data"], [])
            else:
                self.assertEqual(list(csv.DictReader(io.StringIO(body))), [])
        self.assertEqual(self.get("/api/hotspots", **filters, limit=10001)[0], 422)

    def test_map_and_export_report_missing_selected_database(self):
        filters = {
            "min_lat": -30, "max_lat": -20, "min_lon": 130, "max_lon": 140,
            "start_date": "2024-01-02", "end_date": "2024-02-29",
        }
        self.viirs.unlink()
        for path in ("/api/hotspots", "/api/hotspot-cells", "/api/export"):
            with self.subTest(path=path):
                self.assertEqual(self.get(path, **filters)[0], 503)
                self.assertEqual(self.get(path, **filters, sensor="MODIS")[0], 200)


if __name__ == "__main__":
    unittest.main()
