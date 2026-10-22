"""Run: python -m unittest test_atlas -v"""
import csv
import io
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch

import server


class AtlasApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.patch = patch.object(server, 'DB_PATH', Path(cls.tmp.name) / 'test.sqlite3')
        cls.patch.start()
        server.init_db()
        cls.httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.httpd.server_port

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=3)
        cls.patch.stop()
        cls.tmp.cleanup()

    def req(self, method, path, data=None, content_type='application/json'):
        connection = HTTPConnection('127.0.0.1', self.port, timeout=3)
        body = data if isinstance(data, str) else json.dumps(data) if data is not None else None
        headers = {'Content-Type': content_type} if body is not None else {}
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        content = response.read()
        status = response.status
        mime = response.getheader('Content-Type')
        connection.close()
        return status, content, mime

    def test_seed_exactly_four(self):
        with server.db() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM plots').fetchone()[0], 4)
            self.assertEqual(conn.execute("SELECT value_kes FROM plots WHERE parcel_number='Karai/Gikambura/9590'").fetchone()[0], 3800000)
            self.assertEqual(conn.execute("SELECT valuation_period FROM plots WHERE parcel_number='Dagoretti/Settlement Scheme/450'").fetchone()[0], '2025-03')
        status, body, _ = self.req('GET', '/api/plots')
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(body)), 4)
        server.init_db()  # should not reseed duplicates

    def test_add_modify_export_delete_and_layer(self):
        example = dict(server.SEED[0], parcel_number='DEMO/Test/99', value_kes=2000000)
        status, body, _ = self.req('POST', '/api/plots', example)
        self.assertEqual(status, 201)
        item = json.loads(body)
        self.assertEqual(item['parcel_number'], 'DEMO/Test/99')
        pk = item['id']
        example['value_kes'] = 2500000
        status, body, _ = self.req('PUT', f'/api/plots/{pk}', example)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['value_kes'], 2500000)

        status, body, mime = self.req('GET', '/api/export.geojson')
        self.assertEqual(status, 200)
        geo = json.loads(body)
        self.assertEqual(geo['type'], 'FeatureCollection')
        self.assertEqual(len(geo['features']), 5)
        self.assertEqual(geo['features'][0]['geometry']['coordinates'], [36.651306, -1.282306])
        status, body, mime = self.req('GET', '/api/export.csv')
        self.assertEqual(status, 200)
        self.assertEqual(len(list(csv.DictReader(io.StringIO(body.decode('utf-8-sig'))))), 5)

        polygon = {'type': 'FeatureCollection', 'features': []}
        status, body, _ = self.req('POST', '/api/layers', {'name': 'Test GIS', 'geojson': polygon})
        self.assertEqual(status, 201)
        layer_id = json.loads(body)['id']
        status, body, _ = self.req('GET', '/api/layers')
        self.assertEqual(json.loads(body)[0]['name'], 'Test GIS')
        status, body, _ = self.req('DELETE', f'/api/layers/{layer_id}')
        self.assertEqual(status, 200)

        status, body, _ = self.req('DELETE', f'/api/plots/{pk}')
        self.assertEqual(status, 200)
        status, body, _ = self.req('GET', '/api/plots')
        self.assertEqual(len(json.loads(body)), 4)

    def test_csv_import_and_validation(self):
        csv_content = 'parcel_number,latitude,longitude,area_ha,value_kes,valuation_period\nX/Y/001,-1.2,36.6,0.05,2900000,2026-02\n'
        status, body, _ = self.req('POST', '/api/import.csv', csv_content, 'text/csv')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['imported'], 1)
        status, body, _ = self.req('POST', '/api/import.csv', csv_content, 'text/csv')
        self.assertEqual(json.loads(body)['duplicates_skipped'], 1)
        status, body, _ = self.req('POST', '/api/plots', dict(server.SEED[0], parcel_number='X/Y/002', valuation_period='2026-99'))
        self.assertEqual(status, 400)
        with server.db() as conn:
            conn.execute("DELETE FROM plots WHERE parcel_number='X/Y/001'")

    def test_html_assets(self):
        for endpoint in ('/', '/styles.css', '/app.js'):
            status, body, mime = self.req('GET', endpoint)
            self.assertEqual(status, 200)
            self.assertGreater(len(body), 500)


if __name__ == '__main__':
    unittest.main()
