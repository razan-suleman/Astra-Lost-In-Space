# Harmonized Burning Activity Calendar

A Streamlit web app that shows fire activity as a calendar (years × time of
year), combining the MODIS record (2003 onward) with VIIRS (2012 onward) into
one consistent series.

## Run with real Australia data

Install both sets of requirements and place `australia_fires.duckdb` and
`australia_viirs.duckdb` in `backend/`. Start the backend and frontend in
separate terminals from the repository root:

```powershell
python backend\main.py
```

```powershell
streamlit run app.py
```

Open http://localhost:8501, select **Start**, then use **Real observations**.
Choose **Scientist** for separate sensor histories, monthly summed FRP and
coverage notes, or **Land manager** for a simpler historical map and calendar.
Both views use historical detections, not live fire alerts.
The year and sensor filters apply to the Australia calendar, map and monthly
CSV download. The map's period selector shows either the entire selected year
or a single month; it does not change the calendar, chart or CSV download.
The map groups all detections in that period into 0.5-degree cells, colored
by detection count on a logarithmic, colorblind-friendly scale. The labeled
legend and cell table provide counts without relying on color; the scale is
relative to the current map. Click an occupied cell or enter latitude and
longitude to see its yearly history and compare two years by month; without a
selection the comparison covers Australia. The existing calendar, monthly
chart and CSV remain Australia-wide. Missing records do not establish coverage
or zero activity. The map uses geographic 0.5-degree cells, not the separate
EPSG:6933 kilometre grids. Raw MODIS and
VIIRS values are not harmonized; the two Australia geographic definitions
may differ. Days without reported detections have unknown coverage.

Use **Draw an area on the map** to draw and apply a polygon. Its history,
year comparison and anomaly count detections by their actual coordinates,
including detections on the polygon boundary. Drawing a polygon replaces a
selected cell; selecting a cell or coordinates replaces the polygon. Clearing
the selection returns these views to Australia-wide data. The calendar,
monthly chart and CSV remain Australia-wide. The drawing map covers 110–155° E
and 45–9° S; offshore territories outside those bounds cannot be selected.
Polygons can have up to 50 vertices and must not cross themselves.

The historical monthly anomaly compares a selected month and year with the
same month in the preceding 10 calendar years, for the same sensor and area.
The baseline is the mean of years with reported detections only. Months without
records are excluded rather than counted as zero, which can bias the average
upward; actual observation coverage is unknown. The imported 2019 S-NPP VIIRS
archive is missing, so 2019 VIIRS is excluded from baselines and flagged when
selected as the target year. Satellite changes and observation conditions can
also affect the comparison.

The backend defaults to `http://127.0.0.1:8000`; set `ASTRA_API_URL` before
starting Streamlit to use a different backend. Requests are made by Streamlit
on the server, not directly by the browser. The backend's existing arbitrary
SQL endpoint is for trusted local development only.

## Run the sample demo

```bash
pip install -r requirements.txt
python scripts/generate_sample_data.py   # synthetic placeholder data
streamlit run app.py
```

Then open http://localhost:8501 and select **Sample demo**. These data are synthetic.

## Use real data

The pipeline must write `cells.parquet` and `fire_daily.parquet` with the
columns listed in **ARCHITECTURE.md, section 4**. Then:

```bash
FIRE_DATA_DIR=/path/to/pipeline/output FIRE_SAMPLE_DATA=0 streamlit run app.py
```

## Where things are

| File | Purpose |
|---|---|
| `app.py` | Page layout and wiring |
| `frontend/data.py` | All queries (DuckDB over Parquet), cached |
| `frontend/charts.py` | Calendar heatmap and time series (Plotly) |
| `frontend/map_view.py` | Clickable 3D globe of grid cells (pydeck) |
| `static/countries_50m.geojson` | Country outlines for the globe |
| `frontend/config.py` | Paths, transition date, colors |

See `ARCHITECTURE.md` for the full design.
