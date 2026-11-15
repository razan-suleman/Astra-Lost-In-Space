# ASTRA Australia daily grid data quality report

## Scope and source

- Period: all available years; the two source databases are read-only Australia extracts.
- MODIS uses the Natural Earth Australia boundary; VIIRS uses NASA FIRMS Australia-labeled country files. These extents are not identical.
- The imported S-NPP VIIRS archive for 2019 is missing; the available 2019 VIIRS records are N20 only.
- Satellite codes are preserved as stored: MODIS Terra/Aqua and VIIRS N/N20.

## Grid and aggregation

- CRS: EPSG:6933 (WGS 84 / NSIDC EASE-Grid 2.0 Global), coordinates in metres.
- Fixed grid origin: projected x = 0 m, y = 0 m for every sensor and grid size.
- grid_x = floor(x / cell_size_m), grid_y = floor(y / cell_size_m). A cell spans [index × size, (index + 1) × size) along each axis.
- Cell sizes: 1, 2, 5, 10, 20 km.
- One row per UTC acquisition date, sensor, satellite and occupied cell. No unobserved or empty cells are filled with zero.
- detection_count counts raw detections, not distinct fires. FRP sum and mean use non-null instantaneous FRP values in MW; the sum is not fire energy.
- scan_mean and track_mean average non-null source pixel dimensions in km. footprint_area_mean averages scan × track in km² only where both are present; it is a footprint proxy, not burned area or a viewing-angle correction.
- Each *_valid_count is the number of source detections used for that statistic; a statistic with no valid inputs is null. Negative source FRP values are retained.
- Sensors are not harmonized. MODIS and VIIRS have different resolutions and detection characteristics.

## Source quality

### MODIS
- Source: australia_fires.duckdb; 6,443,441 observations, 2000-11-01 to 2025-12-31.
- Observed bounds (WGS 84): latitude -43.596 to -9.2463; longitude 113.0703 to 153.5926.
- Null values: FRP 0; scan 0; track 0. Negative FRP values retained: 4.

| Year | Satellite | Source detections |
|---:|---|---:|
| 2000 | Terra | 30,724 |
| 2001 | Terra | 235,315 |
| 2002 | Aqua | 144,599 |
| 2002 | Terra | 190,743 |
| 2003 | Aqua | 120,570 |
| 2003 | Terra | 91,789 |
| 2004 | Aqua | 176,070 |
| 2004 | Terra | 136,316 |
| 2005 | Aqua | 112,959 |
| 2005 | Terra | 77,180 |
| 2006 | Aqua | 171,185 |
| 2006 | Terra | 133,466 |
| 2007 | Aqua | 136,043 |
| 2007 | Terra | 118,888 |
| 2008 | Aqua | 107,062 |
| 2008 | Terra | 76,456 |
| 2009 | Aqua | 143,878 |
| 2009 | Terra | 108,036 |
| 2010 | Aqua | 74,000 |
| 2010 | Terra | 46,558 |
| 2011 | Aqua | 248,033 |
| 2011 | Terra | 189,108 |
| 2012 | Aqua | 256,918 |
| 2012 | Terra | 218,046 |
| 2013 | Aqua | 110,750 |
| 2013 | Terra | 79,767 |
| 2014 | Aqua | 145,747 |
| 2014 | Terra | 111,174 |
| 2015 | Aqua | 135,960 |
| 2015 | Terra | 103,502 |
| 2016 | Aqua | 93,906 |
| 2016 | Terra | 65,317 |
| 2017 | Aqua | 157,217 |
| 2017 | Terra | 116,095 |
| 2018 | Aqua | 175,192 |
| 2018 | Terra | 132,167 |
| 2019 | Aqua | 174,565 |
| 2019 | Terra | 135,919 |
| 2020 | Aqua | 93,262 |
| 2020 | Terra | 62,262 |
| 2021 | Aqua | 107,064 |
| 2021 | Terra | 64,884 |
| 2022 | Aqua | 96,216 |
| 2022 | Terra | 64,062 |
| 2023 | Aqua | 221,158 |
| 2023 | Terra | 174,575 |
| 2024 | Aqua | 136,273 |
| 2024 | Terra | 87,273 |
| 2025 | Aqua | 149,277 |
| 2025 | Terra | 105,915 |

### VIIRS
- Source: australia_viirs.duckdb; 24,946,615 observations, 2012-01-20 to 2025-12-31.
- Observed bounds (WGS 84): latitude -43.58683 to -9.26313; longitude 113.41708 to 153.62357.
- Null values: FRP 0; scan 0; track 0. Negative FRP values retained: 163.

| Year | Satellite | Source detections |
|---:|---|---:|
| 2012 | N | 2,143,784 |
| 2013 | N | 947,248 |
| 2014 | N | 1,216,712 |
| 2015 | N | 1,143,155 |
| 2016 | N | 777,831 |
| 2017 | N | 1,241,741 |
| 2018 | N | 1,470,574 |
| 2018 | N20 | 1,334,377 |
| 2019 | N20 | 1,554,640 |
| 2020 | N | 847,691 |
| 2020 | N20 | 829,833 |
| 2021 | N | 819,461 |
| 2021 | N20 | 812,138 |
| 2022 | N | 804,720 |
| 2022 | N20 | 826,535 |
| 2023 | N | 1,855,272 |
| 2023 | N20 | 1,782,338 |
| 2024 | N | 979,867 |
| 2024 | N20 | 1,059,409 |
| 2025 | N | 1,251,438 |
| 2025 | N20 | 1,247,851 |

## Verification and files

For every file, detection counts, FRP valid counts, and FRP sums were independently re-read from Parquet and checked against the source for every sensor/year/satellite group.

| File | Occupied daily satellite cells |
|---|---:|
| grid_1km.parquet | 18,103,453 |
| grid_2km.parquet | 12,090,670 |
| grid_5km.parquet | 7,412,513 |
| grid_10km.parquet | 5,442,216 |
| grid_20km.parquet | 4,121,743 |
