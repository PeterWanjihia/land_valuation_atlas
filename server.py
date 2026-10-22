#!/usr/bin/env python3
"""Land Valuation Atlas — dependency-free SQLite + HTTP server.

Run locally: python server.py
Open: http://127.0.0.1:8765

Vercel loads this file as a Python function (class Handler) and routes every
request to it. The bundled SQLite file is opened read-only on Vercel because
the deployment filesystem cannot persist writes. Local runs stay writable.

Local-use starter. Do not expose to the internet without authentication and HTTPS.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
STATIC_DIR = (ROOT / 'static').resolve()
DB_PATH = Path(os.environ.get('ATLAS_DB', ROOT / 'data' / 'valuations.sqlite3'))
HOST = os.environ.get('ATLAS_HOST', '127.0.0.1')
PORT = int(os.environ.get('ATLAS_PORT', '8765'))
MAX_BODY = 8 * 1024 * 1024
READ_ONLY_MESSAGE = 'This deployment serves the SQLite database read-only.'

SEED = [
    {
        'parcel_number': 'Dagoretti/Thogoto/3917',
        'latitude': -1.282306, 'longitude': 36.651306,
        'coordinate_dms': '1°16\'56.3"S 36°39\'04.7"E',
        'relative_position': '0.21 km West-Northwest',
        'locality': 'Thogoto, Dagoretti', 'area_ha': 0.046,
        'value_kes': 5_000_000, 'valuation_period': '2022-02',
        'original_value': '5m', 'original_date': '02/22',
        'notes': '',
    },
    {
        'parcel_number': 'Dagoretti/Settlement Scheme/450',
        'latitude': -1.291444, 'longitude': 36.651833,
        'coordinate_dms': '1°17\'29.2"S 36°39\'06.6"E',
        'relative_position': '0.98 km South',
        'locality': 'Kangiria Area', 'area_ha': 0.046,
        'value_kes': 3_000_000, 'valuation_period': '2025-03',
        'original_value': '3m', 'original_date': '03/25',
        'notes': '',
    },
    {
        'parcel_number': 'Dagoretti/Thogoto/4347',
        'latitude': -1.281500, 'longitude': 36.663167,
        'coordinate_dms': '1°16\'53.4"S 36°39\'47.4"E',
        'relative_position': '1.13 km East',
        'locality': 'Thogoto, Dagoretti', 'area_ha': 0.043,
        'value_kes': 5_000_000, 'valuation_period': '2023-08',
        'original_value': '5m', 'original_date': '08/23',
        'notes': '',
    },
    {
        'parcel_number': 'Karai/Gikambura/9590',
        'latitude': -1.272222, 'longitude': 36.653861,
        'coordinate_dms': '1°16\'20.0"S 36°39\'13.9"E',
        'relative_position': '1.17 km North',
        'locality': 'Gikambura, Karai', 'area_ha': 0.05,
        'value_kes': 3_800_000, 'valuation_period': '2024-07',
        'original_value': '3.8m', 'original_date': '07/24',
        'notes': '',
    },
]

PLOT_FIELDS = [
    'parcel_number', 'latitude', 'longitude', 'coordinate_dms',
    'relative_position', 'locality', 'area_ha', 'value_kes',
    'valuation_period', 'original_value', 'original_date', 'notes',
]
CSV_FIELDS = PLOT_FIELDS + ['id', 'created_at', 'updated_at']


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def deployment_is_read_only() -> bool:
    """Vercel functions can read the deployed filesystem, not persist changes to it."""
    return os.environ.get('VERCEL') == '1'


def database_path() -> Path:
    return Path(DB_PATH).resolve()


def connect():
    path = database_path()
    if deployment_is_read_only():
        # immutable=1 avoids journal/WAL files beside the bundled database.
        return sqlite3.connect(f'{path.as_uri()}?mode=ro&immutable=1', uri=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(path, timeout=10)


@contextmanager
def db():
    read_only = deployment_is_read_only()
    connection = connect()
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA foreign_keys=ON')
    try:
        yield connection
        if not read_only:
            connection.commit()
    except Exception:
        if not read_only:
            connection.rollback()
        raise
    finally:
        connection.close()


def init_db():
    with db() as conn:
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS plots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                parcel_number TEXT NOT NULL UNIQUE,
                latitude REAL NOT NULL CHECK (latitude BETWEEN -90 AND 90),
                longitude REAL NOT NULL CHECK (longitude BETWEEN -180 AND 180),
                coordinate_dms TEXT NOT NULL DEFAULT '',
                relative_position TEXT NOT NULL DEFAULT '',
                locality TEXT NOT NULL DEFAULT '',
                area_ha REAL NOT NULL CHECK (area_ha > 0),
                value_kes INTEGER NOT NULL CHECK (value_kes >= 0),
                valuation_period TEXT NOT NULL,
                original_value TEXT NOT NULL DEFAULT '',
                original_date TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_plot_value ON plots (value_kes);
            CREATE INDEX IF NOT EXISTS idx_plot_period ON plots (valuation_period);
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS layers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                geojson TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        ''')
        seeded = conn.execute("SELECT value FROM metadata WHERE key='seeded_v1'").fetchone()
        if not seeded:
            if conn.execute('SELECT COUNT(*) FROM plots').fetchone()[0] == 0:
                for entry in SEED:
                    insert_plot(conn, entry)
            conn.execute("INSERT INTO metadata(key, value) VALUES('seeded_v1', 'yes')")


def validate_plot(payload):
    if not isinstance(payload, dict):
        raise ValueError('Expected a JSON object for plot details.')
    d = {}
    for key in ('parcel_number', 'coordinate_dms', 'relative_position', 'locality',
                'valuation_period', 'original_value', 'original_date', 'notes'):
        d[key] = str(payload.get(key, '') or '').strip()[:1500]
    if not d['parcel_number']:
        raise ValueError('Plot number is required.')
    if len(d['parcel_number']) > 200:
        raise ValueError('Plot number is too long.')
    for key in ('latitude', 'longitude', 'area_ha'):
        try:
            d[key] = float(payload[key])
        except (KeyError, ValueError, TypeError):
            raise ValueError(f'{key} must be a number.') from None
    if not (-90 <= d['latitude'] <= 90 and -180 <= d['longitude'] <= 180):
        raise ValueError('Latitude or longitude is out of range.')
    if not (0 < d['area_ha'] <= 1_000_000):
        raise ValueError('Land area must be positive.')
    try:
        d['value_kes'] = int(float(payload['value_kes']))
    except (KeyError, ValueError, TypeError):
        raise ValueError('Valuation must be a KES number.') from None
    if not (0 <= d['value_kes'] <= 10**15):
        raise ValueError('Valuation is out of range.')
    if not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', d['valuation_period']):
        raise ValueError('Valuation date must be YYYY-MM.')
    return d


def insert_plot(conn, payload):
    data = validate_plot(payload)
    cols = list(data)
    ts = now_iso()
    cursor = conn.execute(
        f"INSERT INTO plots ({', '.join(cols)}, created_at, updated_at) VALUES ({', '.join(['?'] * len(cols))}, ?, ?)",
        [data[k] for k in cols] + [ts, ts],
    )
    return cursor.lastrowid


def rows_to_dict(rows):
    return [dict(x) for x in rows]


def to_geojson(plots):
    return {
        'type': 'FeatureCollection',
        'features': [
            {
                'type': 'Feature',
                'id': row['id'],
                'geometry': {
                    'type': 'Point',
                    'coordinates': [row['longitude'], row['latitude']],
                },
                'properties': {k: v for k, v in row.items() if k not in ('latitude', 'longitude')}
                | {'area_sqm': round(row['area_ha'] * 10_000, 2)},
            } for row in plots
        ],
    }


def validate_geojson(data):
    if not isinstance(data, dict):
        raise ValueError('Layer must be a GeoJSON object.')
    if data.get('type') not in ('FeatureCollection', 'Feature', 'GeometryCollection',
                                'Point', 'MultiPoint', 'LineString', 'MultiLineString',
                                'Polygon', 'MultiPolygon'):
        raise ValueError('Upload a valid GeoJSON feature, geometry, or FeatureCollection.')
    # Parseability by Leaflet depends on geometry validity; keep original JSON as layer data.
    return data


class Handler(BaseHTTPRequestHandler):
    server_version = 'LandAtlas/1.0'

    def send_bytes(self, content, mimetype, status=200, filename=None):
        self.send_response(status)
        self.send_header('Content-Type', mimetype)
        self.send_header('Content-Length', str(len(content)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Cache-Control', 'no-store' if self.path.startswith('/api/') else 'max-age=300')
        if filename:
            self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(content)

    def send_json(self, value, status=200):
        self.send_bytes(json.dumps(value, ensure_ascii=False).encode('utf-8'),
                        'application/json; charset=utf-8', status=status)

    def fail(self, status, message):
        self.send_json({'error': message}, status)

    def body(self, as_json=True):
        length = int(self.headers.get('Content-Length', 0))
        if length < 1 or length > MAX_BODY:
            raise ValueError('Empty upload or file too large (8 MB maximum).')
        data = self.rfile.read(length)
        return json.loads(data) if as_json else data.decode('utf-8-sig')

    def do_GET(self):
        path = urlsplit(self.path).path
        if path in ('/', '/index.html', '/app.js', '/styles.css'):
            name = 'index.html' if path == '/' else path.lstrip('/')
            item = (STATIC_DIR / name).resolve()
            typ = ( 'text/html; charset=utf-8' if name.endswith('.html') else
                   'text/javascript; charset=utf-8' if name.endswith('.js') else
                   'text/css; charset=utf-8')
            self.send_bytes(item.read_bytes(), typ)
            return
        with db() as conn:
            if path == '/api/health':
                self.send_json({'ok': True, 'database': 'SQLite', 'records': conn.execute('SELECT COUNT(*) FROM plots').fetchone()[0]})
            elif path == '/api/plots':
                self.send_json(rows_to_dict(conn.execute('SELECT * FROM plots ORDER BY valuation_period DESC, id DESC')))
            elif path == '/api/layers':
                self.send_json([{'id': r['id'], 'name': r['name'], 'geojson': json.loads(r['geojson'])}
                                for r in conn.execute('SELECT * FROM layers ORDER BY name')])
            elif path == '/api/export.csv':
                data = io.StringIO()
                writer = csv.DictWriter(data, fieldnames=CSV_FIELDS)
                writer.writeheader()
                writer.writerows(rows_to_dict(conn.execute('SELECT * FROM plots ORDER BY id')))
                self.send_bytes(data.getvalue().encode('utf-8-sig'), 'text/csv; charset=utf-8',
                                filename='land_valuations.csv')
            elif path == '/api/export.geojson':
                geo = to_geojson(rows_to_dict(conn.execute('SELECT * FROM plots ORDER BY id')))
                self.send_bytes(json.dumps(geo, ensure_ascii=False, indent=2).encode(),
                                'application/geo+json', filename='land_valuations.geojson')
            else:
                self.fail(404, 'Not found.')

    def reject_readonly_write(self) -> bool:
        if not deployment_is_read_only():
            return False
        self.fail(403, READ_ONLY_MESSAGE)
        return True

    def do_POST(self):
        if self.reject_readonly_write():
            return
        path = urlsplit(self.path).path
        try:
            if path == '/api/plots':
                data = self.body()
                with db() as conn:
                    plot_id = insert_plot(conn, data)
                    record = dict(conn.execute('SELECT * FROM plots WHERE id=?', (plot_id,)).fetchone())
                self.send_json(record, status=201)
            elif path == '/api/import.csv':
                raw = self.body(as_json=False)
                reader = csv.DictReader(io.StringIO(raw))
                if not reader.fieldnames or not set(['parcel_number', 'latitude', 'longitude', 'area_ha', 'value_kes', 'valuation_period']).issubset(reader.fieldnames):
                    raise ValueError('CSV must include parcel_number, latitude, longitude, area_ha, value_kes, valuation_period.')
                imported, duplicates = 0, 0
                with db() as conn:
                    for line, entry in enumerate(reader, start=2):
                        if not any((v or '').strip() for v in entry.values() if isinstance(v, str)):
                            continue
                        try:
                            insert_plot(conn, entry)
                            imported += 1
                        except sqlite3.IntegrityError:
                            duplicates += 1
                        except ValueError as ex:
                            raise ValueError(f'CSV line {line}: {ex}') from ex
                self.send_json({'imported': imported, 'duplicates_skipped': duplicates})
            elif path == '/api/layers':
                data = self.body()
                name = str(data.get('name') or '').strip()
                if not 1 <= len(name) <= 150:
                    raise ValueError('Layer name must have 1–150 characters.')
                geojson = validate_geojson(data.get('geojson'))
                with db() as conn:
                    cur = conn.execute('INSERT INTO layers (name, geojson, created_at) VALUES (?, ?, ?)',
                                       (name, json.dumps(geojson), now_iso()))
                    new_id = cur.lastrowid
                self.send_json({'id': new_id, 'name': name, 'geojson': geojson}, status=201)
            else:
                self.fail(404, 'Not found.')
        except json.JSONDecodeError:
            self.fail(400, 'Invalid JSON data.')
        except sqlite3.IntegrityError:
            self.fail(409, 'That plot number or layer name already exists.')
        except (ValueError, KeyError) as ex:
            self.fail(400, str(ex))

    def do_PUT(self):
        if self.reject_readonly_write():
            return
        match = re.fullmatch(r'/api/plots/(\d+)', urlsplit(self.path).path)
        if not match:
            self.fail(404, 'Not found.')
            return
        try:
            data = validate_plot(self.body())
            with db() as conn:
                cols = list(data)
                cur = conn.execute(
                    f"UPDATE plots SET {', '.join(f'{key}=?' for key in cols)}, updated_at=? WHERE id=?",
                    [data[key] for key in cols] + [now_iso(), int(match.group(1))],
                )
                if cur.rowcount == 0:
                    self.fail(404, 'Plot not found.')
                    return
                record = dict(conn.execute('SELECT * FROM plots WHERE id=?', (int(match.group(1)),)).fetchone())
            self.send_json(record)
        except sqlite3.IntegrityError:
            self.fail(409, 'That plot number already exists.')
        except (ValueError, KeyError, json.JSONDecodeError) as ex:
            self.fail(400, str(ex))

    def do_DELETE(self):
        if self.reject_readonly_write():
            return
        path = urlsplit(self.path).path
        match = re.fullmatch(r'/api/(plots|layers)/(\d+)', path)
        if not match:
            self.fail(404, 'Not found.')
            return
        table = match.group(1)
        with db() as conn:
            cur = conn.execute(f'DELETE FROM {table} WHERE id=?', (int(match.group(2)),))
            if cur.rowcount == 0:
                self.fail(404, 'Record not found.')
                return
        self.send_json({'deleted': True})

    def log_message(self, fmt, *args):
        print(f'[{self.log_date_time_string()}] {self.address_string()} {fmt % args}')


if __name__ == '__main__':
    init_db()
    print(f'Land Valuation Atlas — http://{HOST}:{PORT}')
    print(f'SQLite database: {DB_PATH}')
    print('Press Ctrl+C to stop. Do not expose this local starter to the public internet.')
    try:
        ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print('\nStopped.')
