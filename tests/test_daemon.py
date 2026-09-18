import http.client
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('reader_server', ROOT / 'daemon/server.py')
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class DaemonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        server.READER_DB = os.path.join(cls.tmp.name, 'test.db')
        cls.httpd = server.HTTPServer(('127.0.0.1', 0), server.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.thread.join()
        cls.httpd.server_close()
        cls.tmp.cleanup()

    def request(self, method='GET', path='/stats', payload=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.httpd.server_port)
        values = {'Content-Type':'application/json', **(headers or {})}
        body = json.dumps(payload) if payload is not None else None
        conn.request(method, path, body, values)
        response = conn.getresponse()
        result = response.status, dict(response.getheaders()), json.loads(response.read() or '{}')
        conn.close()
        return result

    def test_rejects_websites_and_rebinding(self):
        for headers in ({'Origin':'https://evil.example'}, {'Origin':'null'}, {'Host':'evil.example'}, {'Sec-Fetch-Site':'cross-site'}):
            status, headers, _ = self.request(headers=headers)
            self.assertEqual(status,403)
            self.assertNotIn('Access-Control-Allow-Origin',headers)

    def test_accepts_extension_and_validates_payload(self):
        origin = 'chrome-extension://' + 'a'*32
        status, headers, _ = self.request('POST','/ingest', {'posts':[{'id':'demo','text':'synthetic searchable example','source':'x'}]}, {'Origin':origin})
        self.assertEqual(status,200)
        self.assertEqual(headers['Access-Control-Allow-Origin'],origin)
        for payload in ([], {'posts':[None]}, {'posts':[{'source':'instagram'}]}, {'signals':[{'source':'instagram'}]}):
            self.assertEqual(self.request('POST','/ingest',payload)[0],400)
        self.assertEqual(self.request('POST','/ingest',{}, {'Content-Length':'-1'})[0],413)
        self.assertEqual(self.request('POST','/ingest',{}, {'Content-Length':'999999999'})[0],413)

    def test_idempotent_ingest_and_private_stats(self):
        payload = {'posts':[{'id':'repeat','text':'unique_fixture_word','source':'x'}]}
        self.request('POST','/ingest',payload)
        self.request('POST','/ingest',payload)
        db=server.connect(server.READER_DB)
        self.assertEqual(db.execute("SELECT count(*) FROM posts WHERE id='repeat'").fetchone()[0],1)
        self.assertEqual(db.execute("SELECT count(*) FROM posts_fts WHERE posts_fts MATCH 'unique_fixture_word'").fetchone()[0],1)
        db.close()
        stats=self.request()[2]
        self.assertNotIn('db',stats)
        self.assertNotIn('recent_events',stats)

if __name__ == '__main__':
    unittest.main()
