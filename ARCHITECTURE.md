# Frontend architecture: Harmonized Burning Activity Calendar

**Goal:** a web app that shows one consistent time series of fire activity
by joining the long MODIS record (2003 onward) with the more detailed VIIRS
record (2012 onward), presented as a burning calendar.

**Scope of this document:** the frontend (web app) only. The harmonization
math runs in a separate offline pipeline. The two sides meet at the
**data contract** below.

---

## 1. Stack and why

| Layer | Choice | Why |
|---|---|---|
| App framework | **Streamlit** | Python end to end, same language as the pipeline. Fast to build. Free hosting on Streamlit Community Cloud. |
| Query engine | **DuckDB** over **Parquet** | Runs SQL directly on Parquet files with no database server. Aggregates millions of rows in milliseconds. |
| Charts | **Plotly** | Interactive heatmap and line chart with hover, zoom and download built in. |
| Map | **pydeck** (deck.gl) `GlobeView` | A 3D globe drawn with WebGL. Handles thousands of cells and supports click selection in Streamlit. Needs no API key: the ocean, countries and grid lines are drawn as layers, with no map tiles. |

**Main rule:** the app never processes raw hotspots. All heavy work
(gridding, harmonization, uncertainty) happens offline in the pipeline. The
app only reads the results and aggregates them, which keeps every interaction
fast despite Streamlit rerunning the script on each click.

---

## 2. Big picture

```
 ┌───────────────────────── OFFLINE (teammates) ──────────────────────────┐
 │ FIRMS / LAADS hotspots (MODIS MCD14ML, VIIRS VNP14IMG)                 │
 │   → clean (type = 0, day/night)                                        │
 │   → grid to equal-area cells                                           │
 │   → sum FRP per cell per day                                           │
 │   → fit VIIRS→MODIS model on the 2012–2021 overlap                     │
 │   → write Parquet that follows the DATA CONTRACT (section 4)           │
 └───────────────────────────────┬────────────────────────────────────────┘
                                 │  data/cells.parquet
                                 │  data/fire_daily.parquet
 ┌───────────────────────────────▼──────────── FRONTEND (this repo) ──────┐
 │  app.py            layout + wiring                                     │
 │    │  sidebar widgets ──► Filters (frozen dataclass)                   │
 │    │  map click ────────► Filters.cell_ids                             │
 │    ▼                                                                   │
 │  frontend/data.py  DuckDB SQL → small chart-ready DataFrames (cached)  │
 │    ▼                                                                   │
 │  frontend/calendar_view.py  interval picker + month calendar cards     │
 │  frontend/charts.py    Plotly: time series                             │
 │  frontend/map_view.py  pydeck: 3D globe with grid cells                │
 │  frontend/config.py    paths, dates, labels, colors                    │
 └────────────────────────────────────────────────────────────────────────┘
```

Each module has one job, so team members can work in parallel:

| File | Owns | Never does |
|---|---|---|
| `app.py` | Page layout, widgets, the order of sections | SQL, figure styling |
| `frontend/data.py` | Every query; caching; units (total vs. density) | Draw anything |
| `frontend/calendar_view.py` | Interval picker and month calendar cards (HTML + CSS) | Read data files |
| `frontend/charts.py` | Plotly time series from DataFrames | Read files |
| `frontend/map_view.py` | pydeck globe; reading the click selection | Read data files |
| `frontend/splash.py` | Intro screen (HTML + CSS only) and the Start button | Read data files |
| `frontend/config.py` | Constants: data paths, transition date, colors | Logic |
| `scripts/generate_sample_data.py` | Synthetic data with the real schema | Ship in production |

---

## 3. Folder structure

```
fire-calendar/
├── app.py                        # streamlit run app.py
├── frontend/
│   ├── __init__.py
│   ├── config.py
│   ├── data.py
│   ├── calendar_view.py
│   ├── charts.py
│   ├── map_view.py
│   └── splash.py
├── scripts/
│   ├── generate_sample_data.py   # placeholder data until the pipeline is ready
│   ├── build_world_geojson.py    # one-off: builds the globe's country outlines
│   └── build_splash_globe.py     # one-off: builds the intro globe's world map
├── static/
│   ├── countries_50m.geojson     # served at app/static/ for the globe
│   └── splash_land.svg           # flat world map for the intro globe
├── data/                         # Parquet goes here (or set FIRE_DATA_DIR)
│   ├── cells.parquet
│   └── fire_daily.parquet
├── .streamlit/config.toml        # theme
├── requirements.txt
├── README.md
└── ARCHITECTURE.md
```

---

## 4. Data contract (agree on this with the pipeline team)

Two Parquet files. The frontend relies on these exact column names. Adding
columns is safe; renaming or removing them breaks the app.

### `cells.parquet`: one row per grid cell

| Column | Type | Meaning |
|---|---|---|
| `cell_id` | string | Unique cell id |
| `lat`, `lon` | float | Cell center (degrees) |
| `region` | string | Region name shown in the sidebar |
| `landcover` | string | Dominant land cover class |
| `area_km2` | float | True cell area, used for density. For a lat/lon cell: `R² · Δλ · (sin φ₂ − sin φ₁)` |

### `fire_daily.parquet`: one row per cell per day **with any fire**

Days with no row are treated as "no fire". Keeping the table sparse makes it
roughly 10× smaller.

| Column | Type | Meaning |
|---|---|---|
| `cell_id` | string | Links to `cells` |
| `date` | date | UTC acquisition date |
| `modis_frp` | float, nullable | Raw MODIS FRP sum (MW). **NULL = no MODIS data that day** (before launch or after retirement). 0 = observed, no fire |
| `viirs_frp` | float, nullable | Raw VIIRS FRP sum (MW). NULL before 2012-01-20 |
| `harmonized_frp` | float | The consistent series on the MODIS scale (MW) |
| `harmonized_lo`, `harmonized_hi` | float | Uncertainty bounds. Equal to `harmonized_frp` where it is observed MODIS |
| `source` | string | `"MODIS"` or `"VIIRS→MODIS"` (where the harmonized value comes from) |
| `n_valid` | int | Number of valid (cloud-free) observations of the cell that day |

The distinction between NULL and 0 matters: the calendar shows a whole year
in gray ("no data from this sensor") when a sensor has only NULLs that year,
so a missing sensor is never mistaken for a year without fire.

**Where the transition happens** is set in `config.TRANSITION` (default
2022-01-01, because the Aqua orbit drifted after 2021). If the pipeline
chooses another date, change it there and the markers on both charts move.

---

## 5. Views

| # | View | Question it answers | Built with |
|---|---|---|---|
| 1 | **Headline numbers** | How much burns, when is the peak, how much is modeled? | `st.metric` |
| 2 | **Burning calendar** (main view) | Which days burned in the interval I picked? | Month calendar cards, one square per day |
| 3 | **Globe** | Where does it burn? Click cells to focus every other view on them. | pydeck `GlobeView` |
| 4 | **Consistency chart** | Does the joined series stay smooth where VIIRS takes over? | Plotly lines + uncertainty band |
| 5 | **Data table + CSV** | Exact numbers, export, and an accessible alternative to the charts | `st.dataframe`, `st.download_button` |

### Calendar details
- **Month cards:** one wall-calendar card per month in the chosen interval
  (weeks start on Monday), one square per day. Built as HTML + CSS in
  `frontend/calendar_view.py`, so hover effects and tooltips are instant.
- **Interval picker:** preset pills (*Fire season*, *Last 3 / 6 / 12 months*,
  *Last 2 years*), ◀ ▶ buttons that move the interval by its own length, and a
  month-range slider. At most `config.CALENDAR_MAX_MONTHS` (24) months are
  drawn at once.
  - *Fire season* = six months around the peak month (2 before, 3 after) of the
    latest year, so it handles seasons that cross New Year (e.g. Sahel: Nov–Apr).
  - State: the interval lives in `st.session_state["cal_sel"]`. Presets and
    arrows change it from code and bump `cal_ver`, which gives the slider a new
    key so it redraws at the new range. Moving the slider by hand clears the preset.
- **Colors:** log scale, seven steps from dim ember to bright flame (more fire =
  brighter, like fires seen from space at night). No-fire days are a faint
  tile; days with no sensor data are hatched.
- **Each card shows:** month total, a thin bar comparing it with the biggest
  month in the interval, and (for the harmonized series) a tag: `MODIS`
  (observed) or a dashed `VIIRS` tag (converted, so modeled).
- **Summary line:** interval total, days with fire, busiest day.

### Intro (splash) screen
- Shown until the user clicks **Start**, which sets `st.session_state.started`.
  The sidebar has **← Back to intro** to return to it.
- Pure HTML + CSS drawn with `st.markdown`; no JavaScript, so nothing extra to install.
- Spinning globe: a circle whose background is a flat world map
  (`static/splash_land.svg`) scrolling sideways, with gradient shading on top.
- Satellites: real 3D CSS transforms (tilted orbit planes in a shared 3D scene), so
  they pass behind the globe and in front of it. Each satellite turns against its orbit
  so it always faces the viewer.
- Start button: a real `st.button`, moved to the center by CSS on its key class
  `.st-key-start_btn`. Opacity 0.55, rising to 1 on hover with a 0.45 s transition.
- Speeds, sizes and colors are CSS variables at the top of `_CSS` in `splash.py`.
- Users with "reduce motion" turned on in their OS get a still image.

### Globe details
- deck.gl `GlobeView` puts the cells on the curved surface of the Earth.
  Each cell edge gets extra points so it follows the curve.
- A globe can't use flat map tiles, so the map is four layers, drawn in order:
  ocean (`SolidPolygonLayer` over the whole sphere), countries
  (`GeoJsonLayer`), a 15° latitude/longitude grid (`PathLayer`), and the fire
  cells (`PolygonLayer`). `cull: true` hides the far side of the globe.
- Country outlines come from `static/countries_50m.geojson` (Natural Earth
  1:50m). Streamlit serves it at `app/static/...` because
  `enableStaticServing = true` in `.streamlit/config.toml`. The browser
  downloads it once (1.7 MB) and caches it, instead of resending it on every
  rerun. To rebuild it, use `scripts/build_world_geojson.py`.
- **3D bars toggle:** cells are extruded with height ∝ √(value), and the
  tallest is 400 km. GlobeView has no camera tilt, so in 3D mode the starting
  view is rotated 35° away from the region. That puts the region near the
  globe's edge, where bar heights can be seen from the side.

### Consistency chart details
- Harmonized (thick, blue, drawn on top), MODIS raw (orange), VIIRS raw (aqua).
- A gray band marks the 2012–2021 overlap used for calibration, and a dotted
  line marks the switch.
- The uncertainty band sums per-cell bounds, which assumes errors are fully
  correlated. That makes it a conservative (wide) band. The pipeline team can
  replace it with a properly propagated interval.

---

## 6. State and interaction

```
sidebar widgets ─┐
                 ├─► Filters(region, years, metric, density, landcovers, cell_ids)
map selection ───┘          │
                            ▼
              data.daily_values(f, start, end)   # interval from the calendar picker
              data.monthly_series(f)
              data.cell_totals(f)      # ignores cell_ids: the map always shows the whole region
              data.headline(f)
```

- `Filters` is a **frozen dataclass**, so it is hashable and acts as the cache key.
- The map selection is read from `st.session_state` **before** anything is
  drawn, so every chart in the same run uses it.
- The map widget key includes the region and a reset counter.
  **Clear selection** increments the counter, which creates a fresh map with
  no selection. Changing the region clears the selection the same way.

---

## 7. Performance

| Technique | Where | Effect |
|---|---|---|
| Sparse daily table | Data contract | Only fire days are stored |
| `@st.cache_resource` DuckDB connection | `data._con` | One connection per server process |
| `@st.cache_data` on every query | `data.py` | Revisiting a filter combination is instant |
| SQL aggregation before pandas | `data.py` | Only a few thousand rows ever reach Python |
| Grid cells, not raw points, on the map | `map_view.py` | The browser draws hundreds of cells, not millions of points |

With the real global dataset: if `fire_daily.parquet` gets large (more than
a few GB), partition it by region or year (`data/fire_daily/region=…/year=…/`)
and point DuckDB at the folder with `hive_partitioning=true`. Only `data.py`
needs to change.

---

## 8. Design system

All values live in `config.py`.

- **Theme: "night sky"**, matching the intro screen but a little lighter:
  page `#14253f`, panels `#1b3152`, light text. Set in
  `.streamlit/config.toml` (Streamlit widgets) and `config.py` (charts,
  calendar, globe). Changing the toml needs an app restart.
- **Categorical (fixed order, never reassigned):** Harmonized `#3987e5`,
  MODIS `#d95926`, VIIRS `#199e70`, the dark-mode steps of the reference
  palette. All pass the colorblind-safety and 3:1 contrast checks on `#14253f`.
- **Sequential (fire intensity):** one warm hue from dim ember `#5a2318` to
  bright flame `#ffab3d`. The same ramp on the calendar and the globe, so a
  color means the same thing everywhere.
- **Globe:** the intro screen's ocean `#1d4f8a` and land `#cfe0d3`.
- **One y-axis per chart.** Never two scales on one chart.
- Text uses ink colors, never series colors.

---

## 9. Moving from sample to real data

1. The pipeline writes `cells.parquet` and `fire_daily.parquet` following section 4.
2. Point the app at them: `FIRE_DATA_DIR=/path/to/output`.
3. Turn off the sample-data banner: `FIRE_SAMPLE_DATA=0`.
4. If the switch year differs, update `config.TRANSITION`.
5. Delete `scripts/generate_sample_data.py` once it is no longer needed.

---

## 10. Deployment

- **Demo:** Streamlit Community Cloud. Connect the GitHub repo, set the env
  vars, and deploy. Parquet up to ~100 MB can live in the repo. Larger files
  go to object storage (S3/GCS), which DuckDB reads directly via its `httpfs`
  extension.
- **Self-hosted:** `streamlit run app.py --server.port 8501` behind any
  reverse proxy, or in a Docker container.

---

## 11. Testing

- `streamlit.testing.v1.AppTest` runs the script headless and can change
  widgets. Use it to check that every filter combination renders without
  exceptions.
- `charts.py` and `map_view.py` take plain DataFrames, so they can be
  unit-tested with small hand-made frames.

---

## 12. Possible next steps

| Feature | Effort | Notes |
|---|---|---|
| Day/night split | Small | Add `daynight` column to the contract, one more sidebar filter |
| Region drawn by the user | Medium | Bounding box inputs, or a GeoJSON upload |
| Click a calendar cell to filter the map to that week | Medium | Plotly `on_select` on the heatmap |
| Fire season metrics (start, end, length per year) | Medium | Compute from the cumulative FRP curve; show as a line over the calendar |
| Multi-region comparison | Medium | Small multiples of the calendar, one per region |
| Migrate to Dash or React + FastAPI | Large | Only if the app needs richer linked interactions or custom design. `data.py` can become the API almost unchanged |
