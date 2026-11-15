import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from frontend import polygon_drawer


class PolygonDrawerTests(unittest.TestCase):
    def test_component_renders_in_streamlit(self):
        app = AppTest.from_string(
            "from frontend.polygon_drawer import draw_polygon\n"
            "draw_polygon([{'min_lon': 130.0, 'min_lat': -30.0}], None, key='map')"
        ).run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.get("component_instance")), 1)

    def test_apply_is_delivered_once_and_clear_is_distinct_from_none(self):
        polygon = [[130.0, -30.0], [131.0, -30.0], [130.0, -31.0]]
        state = {}
        with patch.object(polygon_drawer.st, "session_state", state):
            with patch.object(polygon_drawer, "_component", return_value={
                "event_id": "first", "coordinates": polygon
            }):
                self.assertEqual(polygon_drawer.draw_polygon([], None, "map"), polygon)
                self.assertIsNone(polygon_drawer.draw_polygon([], polygon, "map"))
            with patch.object(polygon_drawer, "_component", return_value={
                "event_id": "clear", "coordinates": []
            }):
                self.assertEqual(polygon_drawer.draw_polygon([], polygon, "map"), [])
                self.assertIsNone(polygon_drawer.draw_polygon([], None, "map"))

    def test_rejects_bad_polygon_events(self):
        invalid = [
            [[130, -30], [131, -30]],
            [[130, -30]] * 51,
            [[130, -30], [131, -30], [156, -31]],
            [[130, -30], [131, -30], [float("nan"), -31]],
            [[130, -30], [131, -30], [True, -31]],
        ]
        with patch.object(polygon_drawer.st, "session_state", {}):
            for coordinates in invalid:
                with self.subTest(coordinates=coordinates):
                    with patch.object(polygon_drawer, "_component", return_value={
                        "event_id": "bad", "coordinates": coordinates
                    }):
                        self.assertIsNone(polygon_drawer.draw_polygon([], None, "map"))


if __name__ == "__main__":
    unittest.main()
