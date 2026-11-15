import json
import os
import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import pandas as pd
from streamlit.testing.v1 import AppTest

from frontend import api, charts, map_view, real_view

APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


class BackendHandler(BaseHTTPRequestHandler):
    calls = []
    empty_hotspots = False

    def log_message(self, format, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.calls.append((self.path, body))
        if self.path != "/api/polygon-history":
            self.send_error(404)
            return
        sensor = body["sensor"]
        payload = {"data": [
            {"date": "2023-01-01", "sensor": sensor, "satellite": "A", "detection_count": 4},
            {"date": "2024-01-01", "sensor": sensor, "satellite": "B", "detection_count": 10},
        ]}
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urlsplit(self.path)
        params = parse_qs(parsed.query)
        self.calls.append((parsed.path, params))
        if parsed.path == "/api/regions":
            payload = {"regions": ["Australia"]}
        elif parsed.path == "/api/calendar":
            if "year" not in params:
                payload = {"data": [
                    {"date": "2023-01-01", "sensor": "MODIS", "satellite": "Terra",
                     "detection_count": 7, "sum_frp_mw": 3.0},
                    {"date": "2024-01-01", "sensor": "MODIS", "satellite": "Terra",
                     "detection_count": 83, "sum_frp_mw": 5.0},
                    {"date": "2024-01-01", "sensor": "VIIRS", "satellite": "N20",
                     "detection_count": 12, "sum_frp_mw": 2.0},
                ]}
            else:
                year = params["year"][0]
                payload = {"data": [{
                    "date": f"{year}-01-01", "sensor": "MODIS", "satellite": "Terra",
                    "detection_count": 83 if year == "2024" else 7, "sum_frp_mw": 5.0,
                }, {
                    "date": f"{year}-01-01", "sensor": "VIIRS", "satellite": "N20",
                    "detection_count": 12, "sum_frp_mw": 2.0,
                }]}
        elif parsed.path == "/api/hotspot-cells":
            cells = [] if self.empty_hotspots else [{
                "min_lat": -30.0, "min_lon": 130.0, "sensor": params["sensor"][0], "detection_count": 12,
            }]
            payload = {"cell_size_degrees": 0.5, "detection_count": 0 if self.empty_hotspots else 12, "data": cells}
        elif parsed.path == "/api/cell-history":
            sensor = params["sensor"][0]
            data = [
                {"date": "2023-01-01", "sensor": sensor, "satellite": "A", "detection_count": 2},
                {"date": "2024-01-01", "sensor": sensor, "satellite": "A", "detection_count": 3},
                {"date": "2024-01-01", "sensor": sensor, "satellite": "B", "detection_count": 4},
            ]
            payload = {"data": [] if params["min_lat"] == ["-90.0"] else data}
        elif parsed.path == "/api/export":
            data = b"month,sensor,detection_count\n2024-01-01,MODIS,83\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/csv")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        else:
            self.send_error(404)
            return
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class RealViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), BackendHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        BackendHandler.calls.clear()
        BackendHandler.empty_hotspots = False
        api._get.clear()
        api._post.clear()
        self.environment = patch.dict(os.environ, {
            "ASTRA_API_URL": f"http://127.0.0.1:{self.server.server_port}",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_real_filters_update_calendar_map_and_export(self):
        app = AppTest.from_file(str(APP_PATH), default_timeout=30)
        app.session_state["started"] = True
        app.run()
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertEqual(app.selectbox("real_year").value, 2024)
        self.assertTrue(any("83 detections" in item.value for item in app.markdown))

        app.selectbox("real_year").set_value(2023)
        app.selectbox("real_sensor").set_value("VIIRS")
        app.run()
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertTrue(any("12 detections" in item.value for item in app.markdown))
        calls = BackendHandler.calls
        self.assertTrue(any("12 detections · occupied cells: 1" in item.value for item in app.caption))
        for path in ("/api/hotspot-cells", "/api/export"):
            self.assertTrue(any(
                route == path and params.get("region") == ["Australia"]
                and params.get("sensor") == ["VIIRS"]
                and params.get("start_date") == ["2023-01-01"]
                and params.get("end_date") == ["2023-12-31"]
                for route, params in calls
            ), calls)
        self.assertFalse(any(route == "/api/hotspots" for route, _ in calls))
        self.assertTrue(any(
            route == "/api/calendar" and params.get("year") == ["2023"]
            and params.get("granularity") == ["day"]
            for route, params in calls
        ), calls)

    def test_unavailable_backend_is_reported(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        with patch.dict(os.environ, {"ASTRA_API_URL": f"http://127.0.0.1:{port}"}):
            app = AppTest.from_file(str(APP_PATH), default_timeout=30)
            app.session_state["started"] = True
            app.run()
            self.assertFalse(app.exception)
            self.assertTrue(any("Cannot reach the backend" in item.value for item in app.error))

    def test_polygon_request_reports_backend_errors(self):
        with self.assertRaisesRegex(api.APIError, "HTTP 404"):
            api.post_json("/missing", {"coordinates": [[130, -30]]})

    def test_map_month_filters_and_yearly_export(self):
        app = AppTest.from_file(str(APP_PATH), default_timeout=30)
        app.session_state["started"] = True
        app.run()
        self.assertEqual(app.selectbox("real_map_month").value, 0)
        self.assertTrue(any("all of 2024" in item.value for item in app.caption))

        for year, month, start, end, label in (
            (2024, 2, "2024-02-01", "2024-02-29", "February 2024"),
            (2023, 2, "2023-02-01", "2023-02-28", "February 2023"),
            (2023, 12, "2023-12-01", "2023-12-31", "December 2023"),
            (2023, 0, "2023-01-01", "2023-12-31", "all of 2023"),
        ):
            with self.subTest(year=year, month=month):
                app.selectbox("real_year").set_value(year)
                app.selectbox("real_map_month").set_value(month)
                app.run()
                self.assertFalse(app.exception)
                self.assertFalse(app.error)
                self.assertTrue(any(label in item.value for item in app.caption))
                self.assertTrue(any(
                    route == "/api/hotspot-cells"
                    and params.get("start_date") == [start] and params.get("end_date") == [end]
                    and params.get("sensor") == ["MODIS"] and params.get("region") == ["Australia"]
                    for route, params in BackendHandler.calls
                ), BackendHandler.calls)
                self.assertTrue(any(
                    route == "/api/export"
                    and params.get("start_date") == [f"{year}-01-01"]
                    and params.get("end_date") == [f"{year}-12-31"]
                    for route, params in BackendHandler.calls
                ), BackendHandler.calls)

    def test_scientist_and_land_manager_modes_share_filters(self):
        app = AppTest.from_file(str(APP_PATH), default_timeout=30)
        app.session_state["started"] = True
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(app.radio("real_user_mode").value, "Scientist")
        self.assertTrue(any("not a live fire alert" in item.value for item in app.warning))
        self.assertTrue(any(item.value == "Monthly summed FRP" for item in app.subheader))
        self.assertTrue(any(item.value == "Yearly detection history by sensor" for item in app.subheader))
        self.assertTrue(any("not fire energy" in item.value for item in app.caption))

        app.selectbox("real_sensor").set_value("VIIRS")
        app.selectbox("real_year").set_value(2023)
        app.selectbox("real_map_month").set_value(2)
        app.radio("real_user_mode").set_value("Land manager")
        app.run()
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertEqual(app.selectbox("real_sensor").value, "VIIRS")
        self.assertEqual(app.selectbox("real_year").value, 2023)
        self.assertEqual(app.selectbox("real_map_month").value, 2)
        self.assertTrue(any("fire history" in item.value for item in app.title))
        self.assertFalse(any(item.value == "Monthly summed FRP" for item in app.subheader))
        self.assertTrue(any("not a live fire alert" in item.value for item in app.warning))
        self.assertTrue(any(
            route == "/api/hotspot-cells" and params.get("sensor") == ["VIIRS"]
            and params.get("start_date") == ["2023-02-01"] and params.get("end_date") == ["2023-02-28"]
            for route, params in BackendHandler.calls
        ))
        self.assertTrue(any(route == "/api/export" and params.get("sensor") == ["VIIRS"]
                            for route, params in BackendHandler.calls))

    def test_scientific_aggregates_keep_sensors_and_missing_frp_separate(self):
        history = pd.DataFrame([
            {"date": "2024-01-01", "sensor": "MODIS", "detection_count": 2},
            {"date": "2024-01-01", "sensor": "MODIS", "detection_count": 3},
            {"date": "2024-02-01", "sensor": "VIIRS", "detection_count": 10},
            {"date": "2022-01-01", "sensor": "MODIS", "detection_count": 4},
        ])
        self.assertEqual(real_view._annual_detections(history, "MODIS").to_dict(), {"2022": 4, "2024": 5})
        self.assertEqual(real_view._annual_detections(history, "VIIRS").to_dict(), {"2024": 10})
        monthly = real_view._monthly_frp([
            {"date": "2024-01-01", "sum_frp_mw": 1.5},
            {"date": "2024-01-01", "sum_frp_mw": 2.0},
            {"date": "2024-03-01", "sum_frp_mw": None},
        ])
        self.assertEqual(monthly.loc["2024-01-01"], 3.5)
        self.assertTrue(pd.isna(monthly.loc["2024-02-01"]))
        self.assertTrue(pd.isna(monthly.loc["2024-03-01"]))

    def test_comparison_respects_sensor_satellites_month_and_missing_data(self):
        rows = [
            {"date": "2024-01-01", "sensor": "MODIS", "detection_count": 3},
            {"date": "2024-01-01", "sensor": "MODIS", "detection_count": 4},
            {"date": "2023-01-01", "sensor": "MODIS", "detection_count": 2},
            {"date": "2024-01-01", "sensor": "VIIRS", "detection_count": 99},
            {"date": "2024-02-01", "sensor": "MODIS", "detection_count": 5},
        ]
        result = real_view._year_comparison(rows, "MODIS", 2024, 2023, 0)
        self.assertEqual(result.loc["January", "2024"], 7)
        self.assertEqual(result.loc["January", "2023"], 2)
        self.assertEqual(result.loc["February", "2024"], 5)
        self.assertTrue(pd.isna(result.loc["February", "2023"]))
        self.assertEqual(list(real_view._year_comparison(rows, "MODIS", 2024, 2023, 2).index), ["February"])
        fig = charts.year_comparison(result)
        self.assertEqual(list(fig.layout.xaxis.categoryarray)[:3], ["January", "February", "March"])
        self.assertEqual(fig.data[0].y[0], 7)
        self.assertTrue(pd.isna(fig.data[1].y[1]))
        self.assertIsNone(map_view.selected_detection_cell({"selection": {"objects": {}}}))

    def test_monthly_anomaly_uses_previous_ten_years_without_inventing_zeros(self):
        rows = [
            {"date": "2013-01-01", "sensor": "VIIRS", "detection_count": 1000},
            {"date": "2014-01-01", "sensor": "VIIRS", "detection_count": 10},
            {"date": "2014-01-01", "sensor": "VIIRS", "detection_count": 20},
            {"date": "2019-01-01", "sensor": "VIIRS", "detection_count": 500},
            {"date": "2023-01-01", "sensor": "VIIRS", "detection_count": 10},
            {"date": "2024-01-01", "sensor": "VIIRS", "detection_count": 30},
            {"date": "2024-01-01", "sensor": "MODIS", "detection_count": 999},
            {"date": "2023-02-01", "sensor": "VIIRS", "detection_count": 50},
        ]
        result = real_view._monthly_anomaly(rows, "VIIRS", 2024, 1)
        self.assertEqual(result["baseline_years"], [2014, 2023])
        self.assertEqual(result["excluded_years"], [2019])
        self.assertIn(2022, result["missing_years"])
        self.assertEqual((result["current"], result["baseline"], result["difference"], result["percent"]),
                         (30, 20, 10, 50))
        missing_current = real_view._monthly_anomaly(rows, "VIIRS", 2024, 2)
        self.assertIsNone(missing_current["current"])
        self.assertIsNone(missing_current["difference"])
        missing_baseline = real_view._monthly_anomaly(rows, "MODIS", 2024, 1)
        self.assertIsNone(missing_baseline["baseline"])
        self.assertIsNone(missing_baseline["percent"])

    def test_anomaly_ui_uses_selected_cell_and_explains_coverage(self):
        app = AppTest.from_file(str(APP_PATH), default_timeout=30)
        app.session_state["started"] = True
        app.session_state["real_selected_cell"] = (-30.0, 130.0)
        app.run()
        self.assertFalse(app.exception)
        self.assertTrue(any("Coverage is not verified" in item.value for item in app.warning))
        self.assertTrue(any("Baseline uses 1 of 10" in item.value for item in app.caption))
        self.assertTrue(any(item.label == "Reported detections" and item.value == "7" for item in app.metric))
        self.assertTrue(any(item.label == "Baseline mean" and item.value == "2.0" for item in app.metric))
        app.selectbox("real_anomaly_month").set_value(2)
        app.run()
        self.assertFalse(app.exception)
        self.assertTrue(any("anomaly is unknown" in item.value for item in app.info))

    def test_drawn_polygon_scopes_history_and_anomaly(self):
        polygon = [[130.0, -30.0], [131.0, -30.0], [130.0, -29.0]]
        app = AppTest.from_file(str(APP_PATH), default_timeout=30)
        app.session_state["started"] = True
        with patch("frontend.polygon_drawer.draw_polygon", return_value=polygon):
            app.run()
            self.assertFalse(app.exception)
            self.assertFalse(app.error)
            self.assertEqual(app.session_state["real_selected_polygon"], polygon)
            self.assertIsNone(app.session_state["real_selected_cell"])
            self.assertTrue(any(
                route == "/api/polygon-history" and params["coordinates"] == polygon
                and params["sensor"] == "MODIS"
                for route, params in BackendHandler.calls
            ))
            self.assertTrue(any(item.label == "Reported detections" and item.value == "10" for item in app.metric))
            self.assertTrue(any(item.label == "Baseline mean" and item.value == "4.0" for item in app.metric))
            app.selectbox("real_sensor").set_value("VIIRS")
            app.selectbox("real_map_month").set_value(2)
            app.run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state["real_selected_polygon"], polygon)
            self.assertTrue(any(
                route == "/api/polygon-history" and params["coordinates"] == polygon
                and params["sensor"] == "VIIRS"
                for route, params in BackendHandler.calls
            ))
        with patch("frontend.polygon_drawer.draw_polygon", return_value=None):
            app.button("real_clear_polygon").click()
            app.run()
        self.assertFalse(app.exception)
        self.assertIsNone(app.session_state["real_selected_polygon"])
        self.assertTrue(any("all Australia" in item.value for item in app.caption))

    def test_polygon_editor_clear_restores_australia_history(self):
        app = AppTest.from_file(str(APP_PATH), default_timeout=30)
        app.session_state["started"] = True
        app.session_state["real_selected_polygon"] = [[130.0, -30.0], [131.0, -30.0], [130.0, -29.0]]
        with patch("frontend.polygon_drawer.draw_polygon", return_value=[]):
            app.run()
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertIsNone(app.session_state["real_selected_polygon"])
        self.assertTrue(any("all Australia" in item.value for item in app.caption))

    def test_selected_cell_history_and_clear_selection(self):
        clicked = SimpleNamespace(selection={"objects": {
            "detection_cells": [{"min_lat": -30.0, "min_lon": 130.0}],
        }})
        empty = SimpleNamespace(selection={"objects": {}})
        app = AppTest.from_file(str(APP_PATH), default_timeout=30)
        app.session_state["started"] = True
        with patch("frontend.real_view.st.pydeck_chart", return_value=clicked) as chart:
            app.run()
            self.assertFalse(app.exception)
            self.assertFalse(app.error)
            self.assertEqual(app.session_state["real_selected_cell"], (-30.0, 130.0))
            self.assertTrue(any("selected cell" in item.value for item in app.caption))
            self.assertTrue(any(item.value == "Selected cell history" for item in app.subheader))
            self.assertTrue(any(
                route == "/api/cell-history" and params.get("sensor") == ["MODIS"]
                and params.get("min_lat") == ["-30.0"] and params.get("min_lon") == ["130.0"]
                for route, params in BackendHandler.calls
            ), BackendHandler.calls)
            initial_map_key = chart.call_args.kwargs["key"]
            chart.return_value = empty
            app.selectbox("real_sensor").set_value("VIIRS")
            app.selectbox("real_map_month").set_value(2)
            app.run()
            self.assertFalse(app.exception)
            self.assertNotEqual(chart.call_args.kwargs["key"], initial_map_key)
            self.assertEqual(app.session_state["real_selected_cell"], (-30.0, 130.0))
            self.assertTrue(any(
                route == "/api/cell-history" and params.get("sensor") == ["VIIRS"]
                for route, params in BackendHandler.calls
            ), BackendHandler.calls)
            app.button("real_clear_cell").click()
            app.run()
            self.assertFalse(app.exception)
            self.assertIsNone(app.session_state["real_selected_cell"])
            self.assertFalse(any(item.value == "Selected cell history" for item in app.subheader))
            self.assertTrue(any("all Australia" in item.value for item in app.caption))

    def test_coordinate_entry_selects_cell_and_keeps_history_filters(self):
        app = AppTest.from_file(str(APP_PATH), default_timeout=30)
        app.session_state["started"] = True
        app.run()
        self.assertTrue(any("Map legend: detections per cell" in item.value for item in app.markdown))
        app.number_input("real_latitude").set_value(-30.01)
        app.number_input("real_longitude").set_value(130.51)
        next(button for button in app.button if button.label == "Select location").click()
        app.run()
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertEqual(app.session_state["real_selected_cell"], (-30.5, 130.5))
        self.assertTrue(any("Selected cell: latitude -30.5° to -30°" in item.value for item in app.caption))
        self.assertTrue(any(
            route == "/api/cell-history" and params.get("min_lat") == ["-30.5"]
            and params.get("min_lon") == ["130.5"] and params.get("sensor") == ["MODIS"]
            for route, params in BackendHandler.calls
        ), BackendHandler.calls)
        self.assertTrue(any("Map cell coordinates and counts" == item.label for item in app.expander))

    def test_coordinate_entry_with_empty_map_does_not_invent_detections(self):
        BackendHandler.empty_hotspots = True
        app = AppTest.from_file(str(APP_PATH), default_timeout=30)
        app.session_state["started"] = True
        app.run()
        app.number_input("real_latitude").set_value(-90.0)
        app.number_input("real_longitude").set_value(-180.0)
        next(button for button in app.button if button.label == "Select location").click()
        app.run()
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertEqual(app.session_state["real_selected_cell"], (-90.0, -180.0))
        self.assertTrue(any("No detections were reported for this cell" in item.value for item in app.info))
        self.assertEqual(len(app.get("deck_gl_json_chart")), 1)

    def test_coordinate_boundaries_and_map_legend_match_colors(self):
        self.assertEqual(map_view.cell_for_coordinates(-30.01, 130.5), (-30.5, 130.5))
        self.assertEqual(map_view.cell_for_coordinates(90, 180), (89.5, 179.5))
        self.assertEqual(map_view.cell_for_coordinates(-90, -180), (-90, -180))
        for latitude, longitude in ((91, 0), (0, -181), (float("nan"), 0)):
            with self.assertRaises(ValueError):
                map_view.cell_for_coordinates(latitude, longitude)
        counts = pd.Series([1, 2, 10, 100, 1000, 10000])
        colors, legend = map_view.detection_colors_and_legend(counts)
        self.assertGreater(len(legend), 1)
        for count, color in zip(counts, colors):
            hex_color = "#" + "".join(f"{channel:02x}" for channel in color[:3])
            self.assertTrue(any(hex_color == c and low <= count <= high for c, low, high in legend))
        colors, legend = map_view.detection_colors_and_legend(pd.Series([7, 7]))
        self.assertEqual(len(legend), 1)
        self.assertEqual(legend[0][1:], (7, 7))
        self.assertEqual(colors[0], colors[1])
        deck = json.loads(map_view.detection_cell_map([], 0.5, (-30.5, 130.5)).to_json())
        self.assertTrue(any(layer["id"] == "selected_cell_outline" for layer in deck["layers"]))
        self.assertEqual(deck["initialViewState"]["latitude"], -30.25)
        self.assertEqual(deck["initialViewState"]["longitude"], 130.75)


if __name__ == "__main__":
    unittest.main()
