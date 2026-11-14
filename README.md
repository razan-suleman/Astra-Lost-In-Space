# Harmonized Burning Activity Calendar

A Streamlit web app that shows fire activity as a calendar (years × time of
year), combining the MODIS record (2003 onward) with VIIRS (2012 onward) into
one consistent series.

## Run it

```bash
pip install -r requirements.txt
python scripts/generate_sample_data.py   # synthetic placeholder data
streamlit run app.py
```

Then open http://localhost:8501.

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
