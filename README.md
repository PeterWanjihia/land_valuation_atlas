# Landmark — Land Valuation Atlas

A working, local-first GIS application for keeping an editable register of land valuation comparables and viewing them as map pins.

**What is included:** 4 records from the initial Dagoretti / Karai dataset; interactive map pins; detailed valuation popups; street, satellite and light basemaps; search, year filtering and sorting; add/edit/delete; CSV import and export; GeoJSON export; GeoJSON overlay import; persistent **SQLite database**.

## 1. Start the application

Only **Python 3.10+** is needed. No Python packages, npm packages, API keys or external databases are required.

From the extracted folder:

```bash
python server.py
```

On Windows, if `python` is unavailable, use `py -3 server.py`.

Open **http://127.0.0.1:8765** in your browser. The map needs an internet connection for the map imagery and the Leaflet JavaScript library, although the valuation data is stored locally.

If you want to change the port:

```bash
ATLAS_PORT=9000 python server.py
```

The application listens only on **127.0.0.1** by default; it is a local workstation app, not an internet-hosted service.

## 2. Where is the database?

`data/valuations.sqlite3` — a real SQLite relational database. New plots, edits, deletions and uploaded GIS layers are written here, surviving server restarts. **Back this file up regularly**, particularly before major changes.

The database is initially populated with four observations once, when it is first created. A metadata flag prevents the four original entries from reappearing if you deliberately delete them all.

SQLite schema (created automatically):

- `plots`: primary key, unique parcel number, lat/long, original DMS text, location, relative distance/direction, size in hectares, valuation in Kenyan shillings, valuation month, notes, timestamps.
- `layers`: name and GeoJSON of uploaded geographic overlays.

## 3. Manage properties

- **Open any property:** choose its sidebar entry or the corresponding map pin. Popup includes parcel number, valuation, date, area in ha and m², locality, coordinates, Google Maps link, and an edit action.
- **Add:** click **Add property**, or click an empty spot on the map to prefill the coordinates. Use a decimal lat/long pair or paste a Google Maps URL into the form.
- **Edit:** open a pin and choose **Edit record**.
- **Delete:** inside the edit form, choose **Delete property** (requires confirmation).
- **Filter/search:** use the left sidebar search, year, and sorting controls.

Amounts are stored as integer **KES**. Date is stored as `YYYY-MM`, not an invented precise day. Area is stored as **hectares**, with square meters computed at display time (1 hectare = 10,000 m²).

## 4. Import and export bulk records

- Click **Import CSV**. At least these columns are required:
  `parcel_number,latitude,longitude,area_ha,value_kes,valuation_period`
- Optional columns: `coordinate_dms,relative_position,locality,original_value,original_date,notes`.
- `valuation_period`: `YYYY-MM` (example `2025-03`).
- `value_kes`: numeric full value (example `5000000`, *not* `5m`).
- The CSV importer skips duplicate parcel numbers and reports how many were imported.
- **Export CSV** creates a portable copy of the entire register.
- **GeoJSON** exports valuation points for **QGIS**, other GIS software and future systems.

A ready-made CSV of the first four properties is included at `data/initial_valuations.csv`; an initial GeoJSON file is at `data/initial_valuations.geojson`.

## 5. GIS layers and property boundaries

The top-right layers control switches between **OpenStreetMap streets**, **Esri satellite imagery**, and **CARTO light map**. The button **Add map layer** accepts `.geojson` or `.json` GeoJSON such as:

- Actual surveyed parcel boundaries (polygon geometry)
- Roads and proposed routes (line geometry)
- Administrative boundaries (polygons)
- Amenities, schools, utilities and other points

Uploaded GeoJSON layers are **saved in SQLite** and can be toggled on/off in the map layers control. To delete an uploaded layer, use a database editor or API `DELETE /api/layers/{id}`; an in-app layer management panel can be added in a subsequent version.

**Important:** The four GPS coordinates are *point observations*. They do **not** give you cadastral parcel polygons or official title boundaries. To show plot shapes, import accurate GeoJSON boundary data from an authorized survey / cadastral source. Do not infer official boundaries by drawing an area around the pins.

## 6. Interpretation of the original records

The original abbreviations were interpreted as follows:

| Original | Structured value |
|---|---|
| `5m` | KES 5,000,000 |
| `3m` | KES 3,000,000 |
| `3.8m` | KES 3,800,000 |
| `02/22` | 2022-02 (February 2022) |
| `03/25` | 2025-03 (March 2025) |
| `08/23` | 2023-08 (August 2023) |
| `07/24` | 2024-07 (July 2024) |

These are **assumptions**, not externally verified valuation facts. Confirm whether `m` means millions of Kenyan shillings, and whether `MM/YY` is the appraisal date or something else. The source abbreviations are separately retained in the database.

These valuations span 2022–2025; they are not automatically current market prices.

## 7. Upgrading to shared, production GIS

This starter is intentionally **single-workstation** and has no user login. **Never directly expose its HTTP server to the public internet.** For multi-user shared data, use the existing schema as a starting point for PostgreSQL + PostGIS; put an authenticated API in front, add role-based permissions and audit history, HTTPS, automated backups and a spatial index. That allows multi-user access, geospatial queries, comparables within a radius and eventual price-per-square-meter analysis.

The immediate app does not require accounts, subscriptions, cloud hosting or payment credentials.

## 8. Project layout

```text
land_valuation_atlas/
  server.py                SQLite database and HTTP endpoints
  static/
    index.html             Map application layout
    styles.css             Responsive styles
    app.js                 Leaflet map and record management
  data/
    valuations.sqlite3     Editable, persistent live database
    initial_valuations.csv Original dataset in portable tabular form
    initial_valuations.geojson  GIS point dataset for other tools
  README.md
```

## 9. REST API

`GET /api/plots`, `POST /api/plots`, `PUT /api/plots/:id`, `DELETE /api/plots/:id`, `GET /api/layers`, `POST /api/layers`, `DELETE /api/layers/:id`, `POST /api/import.csv`, `GET /api/export.csv`, `GET /api/export.geojson`, `GET /api/health`.
