"""Streamlit view backed by raw satellite observations."""

import calendar
from datetime import date

import pandas as pd
import streamlit as st

from frontend import api, calendar_view, charts, map_view, polygon_drawer


def _records(response: dict, key: str, endpoint: str) -> list:
    value = response.get(key)
    if not isinstance(value, list):
        raise api.APIError(f"Backend returned an invalid {key} field for {endpoint}")
    return value


def _annual_detections(history: pd.DataFrame, sensor: str) -> pd.Series:
    rows = history.loc[history["sensor"] == sensor]
    return rows.groupby(rows["date"].str[:4])["detection_count"].sum().rename("Detections")


def _monthly_frp(rows: list[dict]) -> pd.Series:
    frame = pd.DataFrame(rows)
    frame["date"] = pd.to_datetime(frame["date"])
    return frame.groupby("date")["sum_frp_mw"].sum(min_count=1).resample("MS").sum(min_count=1)


def _year_comparison(rows: list[dict], sensor: str, year: int, other_year: int, month: int) -> pd.DataFrame:
    totals = {}
    for row in rows:
        if row["sensor"] != sensor:
            continue
        day = date.fromisoformat(row["date"])
        if day.year in (year, other_year):
            key = (day.year, day.month)
            totals[key] = totals.get(key, 0) + row["detection_count"]
    months = [month] if month else list(range(1, 13))
    return pd.DataFrame(
        {
            str(selected_year): [totals.get((selected_year, number), float("nan")) for number in months]
            for selected_year in (year, other_year)
        },
        index=pd.Index([calendar.month_name[number] for number in months], name="Month"),
    )


def _monthly_anomaly(rows: list[dict], sensor: str, year: int, month: int) -> dict:
    totals: dict[int, int] = {}
    for row in rows:
        if row["sensor"] != sensor:
            continue
        day = date.fromisoformat(row["date"])
        if day.month == month and year - 10 <= day.year <= year:
            totals[day.year] = totals.get(day.year, 0) + row["detection_count"]
    baseline_years = [
        previous for previous in range(year - 10, year)
        if previous in totals and not (sensor == "VIIRS" and previous == 2019)
    ]
    excluded_years = [2019] if sensor == "VIIRS" and year - 10 <= 2019 < year else []
    missing_years = [
        previous for previous in range(year - 10, year)
        if previous not in totals and previous not in excluded_years
    ]
    mean = sum(totals[previous] for previous in baseline_years) / len(baseline_years) if baseline_years else None
    current = totals.get(year)
    difference = current - mean if current is not None and mean is not None else None
    return {
        "current": current, "baseline": mean, "difference": difference,
        "percent": difference / mean * 100 if difference is not None and mean else None,
        "baseline_years": baseline_years, "missing_years": missing_years,
        "excluded_years": excluded_years, "totals": totals,
    }


def _update_cell_selection(map_key: str) -> None:
    selected_cell = map_view.selected_detection_cell(st.session_state[map_key])
    st.session_state.real_selected_cell = selected_cell
    if selected_cell is not None:
        st.session_state.real_selected_polygon = None
        st.session_state.real_polygon_revision = st.session_state.get("real_polygon_revision", 0) + 1


def render() -> None:
    mode = st.radio(
        "Choose your view", ["Scientist", "Land manager"],
        horizontal=True, key="real_user_mode",
    )
    if mode == "Scientist":
        st.title("Satellite fire detections")
        st.caption("Explore unharmonized satellite observations, trends and FRP.")
    else:
        st.title("Explore Australia's fire history")
        st.caption("See where and when satellites have detected fire activity.")
    st.warning("Historical satellite detections only — not a live fire alert or operational safety tool.")

    with st.sidebar:
        st.header("Real-data filters")
        if st.button("← Back to intro", width="stretch"):
            st.session_state.started = False
            st.rerun()

    try:
        regions = _records(api.get_json("/api/regions"), "regions", "/api/regions")
        if not regions:
            st.warning("The backend has no available regions.")
            return
        region = st.sidebar.selectbox("Region", regions, key="real_region")
        history = _records(
            api.get_json("/api/calendar", {"region": region, "granularity": "month"}),
            "data", "/api/calendar",
        )
        years = sorted({int(row["date"][:4]) for row in history}, reverse=True)
        if not years:
            st.warning(f"No dated detections are available for {region}.")
            return
        sensor = st.sidebar.selectbox("Sensor", ["MODIS", "VIIRS"], key="real_sensor")
        year = st.sidebar.selectbox("Year", years, key="real_year")
        daily = _records(
            api.get_json("/api/calendar", {"region": region, "year": year, "granularity": "day"}),
            "data", "/api/calendar",
        )
    except api.APIError as exc:
        st.error(f"{exc}. Start the backend with `python backend\\main.py`.")
        return

    st.caption(
        "MODIS uses the Natural Earth Australia boundary; VIIRS uses NASA's Australia-labeled "
        "country files. The boundaries may differ."
    )
    st.info(
        "Counts are satellite detections, not individual fires or burned area. "
        "Missing detections do not establish that the area was observed or fire-free."
    )
    if sensor == "VIIRS" and year == 2019:
        st.warning("The imported S-NPP VIIRS archive for 2019 is missing; 2019 VIIRS data is from N20 only.")

    dates = pd.date_range(date(year, 1, 1), date(year, 12, 31), freq="D")
    values = pd.Series(float("nan"), index=dates, dtype=float)
    selected = [row for row in daily if row["sensor"] == sensor]
    if selected:
        frame = pd.DataFrame(selected)
        totals = frame.groupby("date")["detection_count"].sum()
        values.loc[pd.to_datetime(totals.index)] = totals.to_numpy()

    st.subheader("Burning calendar")
    st.caption(f"{region} · {year} · {sensor} raw detections")
    st.markdown(
        calendar_view.month_grid_html(values, "detections", None, raw_detections=True),
        unsafe_allow_html=True,
    )

    filters = {
        "region": region, "sensor": sensor,
        "min_lat": -90, "max_lat": 90, "min_lon": -180, "max_lon": 180,
        "start_date": date(year, 1, 1).isoformat(),
        "end_date": date(year, 12, 31).isoformat(),
    }
    left, right = st.columns([1, 1.25], gap="large")
    with left:
        st.subheader("Detection map")
        st.caption("Click a colored cell to explore its history. Only cells with reported detections are shown.")
        with st.expander("Find a location by coordinates"):
            st.caption("Enter decimal degrees (south and west are negative). Data currently cover Australia only.")
            with st.form("real_location_form"):
                latitude = st.number_input(
                    "Latitude", min_value=-90.0, max_value=90.0, value=-25.0,
                    format="%.4f", key="real_latitude",
                )
                longitude = st.number_input(
                    "Longitude", min_value=-180.0, max_value=180.0, value=135.0,
                    format="%.4f", key="real_longitude",
                )
                submitted = st.form_submit_button("Select location")
            if submitted:
                try:
                    st.session_state.real_selected_cell = map_view.cell_for_coordinates(latitude, longitude)
                    st.session_state.real_selected_polygon = None
                    st.session_state.real_map_revision = st.session_state.get("real_map_revision", 0) + 1
                    st.session_state.real_polygon_revision = st.session_state.get("real_polygon_revision", 0) + 1
                except ValueError as exc:
                    st.error(str(exc))
        month = st.selectbox(
            "Map period",
            range(13),
            format_func=lambda value: "All year" if value == 0 else calendar.month_name[value],
            key="real_map_month",
        )
        map_filters = filters.copy()
        if month:
            map_filters["start_date"] = date(year, month, 1).isoformat()
            map_filters["end_date"] = date(year, month, calendar.monthrange(year, month)[1]).isoformat()
        period = f"{calendar.month_name[month]} {year}" if month else f"all of {year}"
        cells = []
        try:
            grid = api.get_json("/api/hotspot-cells", map_filters)
            cells = _records(grid, "data", "/api/hotspot-cells")
            cell_size = grid.get("cell_size_degrees")
            count = grid.get("detection_count")
            if not isinstance(cell_size, (int, float)) or cell_size != 0.5 or not isinstance(count, int):
                raise api.APIError("Backend returned invalid cell metadata for /api/hotspot-cells")
            if cells:
                st.caption(
                    f"{count:,} detections · occupied cells: {len(cells):,} · {period}. "
                    f"Each cell is {cell_size:g}° × {cell_size:g}°; color shows detection count (log scale)."
                )
            else:
                st.info(f"No detections were returned for {period}.")
            area = st.session_state.get("real_selected_cell")
            if cells or area is not None:
                map_key = (
                    f"real_detection_map_{region}_{sensor}_{year}_{month}_"
                    f"{st.session_state.get('real_map_revision', 0)}"
                )
                event = st.pydeck_chart(
                    map_view.detection_cell_map(cells, cell_size, area),
                    width="stretch", height=420, on_select=lambda: _update_cell_selection(map_key),
                    selection_mode="single-object", key=map_key,
                )
                clicked_cell = map_view.selected_detection_cell(event)
                if clicked_cell is not None:
                    st.session_state.real_selected_cell = clicked_cell
            if cells:
                cell_frame = pd.DataFrame(cells)
                _, legend = map_view.detection_colors_and_legend(cell_frame["detection_count"])
                bands = []
                for color, minimum, maximum in legend:
                    label = f"{minimum:,}" if minimum == maximum else f"{minimum:,}–{maximum:,}"
                    bands.append(
                        f'<span style="display:inline-block;width:14px;height:14px;background:{color};'
                        f'border:1px solid #fff;vertical-align:middle" aria-hidden="true"></span> {label}'
                    )
                st.markdown("**Map legend: detections per cell**<br>" + " &nbsp; ".join(bands),
                            unsafe_allow_html=True)
                st.caption(
                    "Darker means fewer detections; lighter means more. The logarithmic scale changes "
                    "with the selected sensor and period, so colors cannot be compared directly between maps."
                )
                with st.expander("Map cell coordinates and counts"):
                    st.dataframe(
                        cell_frame[["min_lat", "min_lon", "detection_count"]].rename(columns={
                            "min_lat": "South latitude", "min_lon": "West longitude",
                            "detection_count": "Detections",
                        }),
                        hide_index=True, width="stretch",
                    )
        except api.APIError as exc:
            st.error(str(exc))
        area = st.session_state.get("real_selected_cell")
        if area is not None:
            st.caption(
                f"Selected cell: latitude {area[0]:g}° to {area[0] + 0.5:g}°, "
                f"longitude {area[1]:g}° to {area[1] + 0.5:g}°."
            )
            if st.button("Clear selected cell", key="real_clear_cell"):
                st.session_state.real_selected_cell = None
                st.session_state.real_map_revision = st.session_state.get("real_map_revision", 0) + 1
                st.rerun()
    with right:
        st.subheader("Monthly detections")
        if mode == "Land manager":
            st.caption("Explore when detections were recorded during the selected year.")
        if selected:
            monthly = values.resample("MS").sum(min_count=1).rename("Detections")
            st.bar_chart(monthly)
        else:
            st.info("No detections were returned for this sensor and year.")

    with st.expander("Draw an area on the map"):
        st.caption(
            "Draw a polygon to explore detections inside it. Selecting a polygon replaces the selected cell. "
            "The main calendar, monthly chart and CSV remain Australia-wide."
        )
        polygon = polygon_drawer.draw_polygon(
            cells, st.session_state.get("real_selected_polygon"),
            key=f"real_polygon_drawer_{st.session_state.get('real_polygon_revision', 0)}",
        )
        if polygon == [] and st.session_state.get("real_selected_polygon") is not None:
            st.session_state.real_selected_polygon = None
            st.session_state.real_polygon_revision = st.session_state.get("real_polygon_revision", 0) + 1
            st.rerun()
        elif polygon and polygon != st.session_state.get("real_selected_polygon"):
            st.session_state.real_selected_polygon = polygon
            st.session_state.real_selected_cell = None
            st.session_state.real_map_revision = st.session_state.get("real_map_revision", 0) + 1
            st.rerun()
        if st.session_state.get("real_selected_polygon") is not None:
            st.caption("A drawn area is selected for history and comparison.")
            if st.button("Clear drawn area", key="real_clear_polygon"):
                st.session_state.real_selected_polygon = None
                st.session_state.real_polygon_revision = st.session_state.get("real_polygon_revision", 0) + 1
                st.rerun()

    area = st.session_state.get("real_selected_cell")
    polygon = st.session_state.get("real_selected_polygon")
    area_label = "drawn area" if polygon is not None else "selected cell" if area is not None else "all Australia"
    comparison_history = history
    if area is not None or polygon is not None:
        st.subheader("Drawn area history" if polygon is not None else "Selected cell history")
        st.caption(
            f"The {area_label} is used for its history, year comparison and monthly anomaly below. "
            "The calendar, monthly chart and CSV above and below remain for all Australia."
        )
        if sensor == "VIIRS":
            st.caption("2019 VIIRS history is incomplete: the imported S-NPP archive is missing.")
        try:
            if polygon is not None:
                response = api.post_json("/api/polygon-history", {
                    "region": region, "sensor": sensor, "coordinates": polygon,
                })
                endpoint = "/api/polygon-history"
            else:
                response = api.get_json("/api/cell-history", {
                    "region": region, "sensor": sensor, "min_lat": area[0], "min_lon": area[1],
                })
                endpoint = "/api/cell-history"
            comparison_history = _records(response, "data", endpoint)
            if comparison_history:
                cell_totals = _annual_detections(pd.DataFrame(comparison_history), sensor)
                st.caption(f"{sensor} · reported detections by year in the {area_label}")
                st.bar_chart(cell_totals)
            else:
                st.info(f"No detections were reported for this {'area' if polygon is not None else 'cell'} and sensor.")
        except api.APIError as exc:
            comparison_history = None
            st.error(str(exc))

    st.subheader("Compare years")
    st.caption(
        f"{sensor} · {area_label} · "
        "same month or months in each year. Missing records mean unknown coverage, not zero. "
        "Differences may also reflect changes in observations or satellite coverage."
    )
    other_years = [value for value in years if value != year]
    if other_years:
        other_year = st.selectbox("Compare with year", other_years, key="real_compare_year")
        if sensor == "VIIRS" and other_year == 2019 and year != 2019:
            st.warning("The imported S-NPP VIIRS archive for 2019 is missing; 2019 VIIRS data is from N20 only.")
        if comparison_history is not None:
            comparison = _year_comparison(comparison_history, sensor, year, other_year, month)
            st.caption(f"Comparing {year} and {other_year} · {calendar.month_name[month] if month else 'all months'}")
            if comparison.notna().any().any():
                st.plotly_chart(charts.year_comparison(comparison), width="stretch")
            else:
                st.info("No detections were reported for these periods.")
            st.dataframe(comparison.astype("Int64"), width="stretch")
    else:
        st.info("Another year is needed for a comparison.")

    st.subheader("Historical monthly anomaly")
    anomaly_month = st.selectbox(
        "Anomaly month", range(1, 13), format_func=lambda value: calendar.month_name[value],
        key="real_anomaly_month",
    )
    st.caption(
        f"{sensor} · {area_label} · "
        f"{calendar.month_name[anomaly_month]} {year} versus the same month in {year - 10}–{year - 1}."
    )
    st.warning(
        "Coverage is not verified. The baseline uses only years with reported detections; missing months "
        "are not treated as zero. This can bias the average upward. Changes may reflect satellite coverage "
        "or observing conditions, not just fire activity."
    )
    if comparison_history is not None:
        anomaly = _monthly_anomaly(comparison_history, sensor, year, anomaly_month)
        baseline_years = anomaly["baseline_years"]
        st.caption(
            f"Baseline uses {len(baseline_years)} of 10 preceding years: "
            + (", ".join(str(value) for value in baseline_years) if baseline_years else "none")
            + "."
        )
        if anomaly["missing_years"]:
            st.caption("No reported detections for: " + ", ".join(map(str, anomaly["missing_years"])) + ".")
        if anomaly["excluded_years"]:
            st.warning("2019 VIIRS is excluded from the baseline because the imported S-NPP archive is missing.")
        if sensor == "VIIRS" and year == 2019:
            st.warning("The selected 2019 VIIRS value is incomplete: only imported N20 data are available.")
        current, baseline, difference, percent = (
            anomaly["current"], anomaly["baseline"], anomaly["difference"], anomaly["percent"]
        )
        if current is None:
            st.info("No detections were reported for the selected month; its anomaly is unknown.")
        elif baseline is None:
            st.info("No usable baseline months were reported; the anomaly cannot be calculated.")
        else:
            anomaly_columns = st.columns(3)
            anomaly_columns[0].metric("Reported detections", f"{current:,}")
            anomaly_columns[1].metric("Baseline mean", f"{baseline:,.1f}")
            anomaly_columns[2].metric(
                "Difference from baseline", f"{difference:+,.1f}",
                f"{percent:+.1f}%" if percent is not None else None,
                delta_color="off",
            )
        with st.expander("Anomaly baseline details"):
            st.dataframe(pd.DataFrame([
                {
                    "Year": previous,
                    "Reported detections": anomaly["totals"].get(previous),
                    "Status": "Excluded: incomplete VIIRS archive" if previous in anomaly["excluded_years"]
                    else "Included" if previous in baseline_years else "No reported detections",
                }
                for previous in range(year - 10, year)
            ]), hide_index=True, width="stretch")

    if mode == "Scientist":
        st.subheader("Monthly summed FRP")
        st.caption(
            f"{sensor} · {year}. Sum of observed instantaneous FRP in MW; "
            "not fire energy or burned area. Missing FRP values are excluded."
        )
        if selected:
            monthly_frp = _monthly_frp(selected)
            if monthly_frp.notna().any():
                st.bar_chart(monthly_frp.rename("Summed instantaneous FRP (MW)"))
            else:
                st.info("No FRP values were reported for this sensor and year.")
        else:
            st.info("No FRP values were reported for this sensor and year.")

        st.subheader("Yearly detection history by sensor")
        st.caption(
            "Sensors are shown separately and are not harmonized; their resolutions and "
            "Australia boundaries differ. Chart scales may differ. Missing years do not imply zero activity."
        )
        history_frame = pd.DataFrame(history)
        sensor_columns = st.columns(2)
        for column, history_sensor in zip(sensor_columns, ("MODIS", "VIIRS")):
            with column:
                st.markdown(f"**{history_sensor}**")
                totals = _annual_detections(history_frame, history_sensor)
                if totals.empty:
                    st.info(f"No {history_sensor} detections are available.")
                else:
                    st.bar_chart(totals)

        with st.expander("Data coverage and limitations"):
            for history_sensor in ("MODIS", "VIIRS"):
                dates_available = history_frame.loc[history_frame["sensor"] == history_sensor, "date"]
                if dates_available.empty:
                    st.write(f"{history_sensor}: no detection records available.")
                else:
                    st.write(
                        f"{history_sensor}: detection records occur from "
                        f"{dates_available.min()[:7]} to {dates_available.max()[:7]}."
                    )
            st.write(
                "These are first and last months with records, not proof of continuous coverage. "
                "The imported S-NPP VIIRS archive for 2019 is missing; N20 has 2019 data. "
                "A missing record does not establish that an area was observed or fire-free."
            )

    with st.expander("Data table and download"):
        if selected:
            st.dataframe(pd.DataFrame(selected), hide_index=True, width="stretch")
        try:
            csv_data = api.get("/api/export", filters)
            st.download_button(
                "Download monthly activity (CSV)", csv_data,
                file_name=f"fire_monthly_{region.lower()}_{sensor.lower()}_{year}.csv",
                mime="text/csv",
            )
        except api.APIError as exc:
            st.error(str(exc))
