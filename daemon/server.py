#!/usr/bin/env python3
"""Loopback-only ingest daemon for the local X index."""
import json
import os
import re
import sqlite3
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlsplit, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from store import READER_DB, connect, now, record_signal, upsert_posts

PORT = int(os.environ.get('READER_PORT', '8787'))
MAX_BODY = 8 * 1024 * 1024


class Handler(BaseHTTPRequestHandler):
    def _allowed(self):
        port = self.server.server_port
        if self.headers.get('Host') not in (f'127.0.0.1:{port}', f'localhost:{port}'):
            return False
        origin = self.headers.get('Origin')
        if origin:
            return bool(re.fullmatch(r'chrome-extension://[a-p]{32}', origin))
        return self.headers.get('Sec-Fetch-Site') in (None, 'none', 'same-origin')

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        if self._allowed() and self.headers.get('Origin'):
            self.send_header('Access-Control-Allow-Origin', self.headers['Origin'])
            self.send_header('Vary', 'Origin')
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        if not self._allowed():
            return self._json(403, {'error': 'local extension access only'})
        self.send_response(204)
        if self.headers.get('Origin'):
            self.send_header('Access-Control-Allow-Origin', self.headers['Origin'])
            self.send_header('Vary', 'Origin')
        self.send_header('Access-Control-Allow-Headers', 'content-type')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.end_headers()

    def do_GET(self):
        if not self._allowed():
            return self._json(403, {'error': 'local extension access only'})
        url = urlsplit(self.path)
        if url.path not in ('/stats', '/search', '/export'):
            return self._json(404, {'error': 'not found'})
        db = connect(READER_DB)
        db.row_factory = sqlite3.Row
        try:
            if url.path == '/stats':
                result = {
                    'service': 'reader', 'api_version': 1,
                    'posts': db.execute('SELECT count(*) FROM posts').fetchone()[0],
                    'by_tier': dict(db.execute('SELECT tier, count(*) FROM signals GROUP BY tier').fetchall()),
                }
            elif url.path == '/export':
                # A versioned snapshot includes every user table, never derived FTS data.
                db.execute('BEGIN')
                result = {'format': 'reader-x', 'version': 1, 'exported_at': now()}
                for table in ('posts', 'signals', 'tags', 'events'):
                    result[table] = [dict(r) for r in db.execute(f'SELECT * FROM {table}')]
            else:
                args = parse_qs(url.query)
                query = args.get('q', [''])[0].strip()
                tier = args.get('tier', [''])[0]
                offset = int(args.get('offset', ['0'])[0])
                if len(query) > 500 or not 0 <= offset <= 9223372036854775807 or tier not in ('', 'viewed', 'liked', 'bookmarked'):
                    raise ValueError()
                terms = query.split()
                where, params = [], []
                if terms:
                    # Treat input as words, not executable FTS syntax.
                    match = ' AND '.join('"' + t.replace('"', '""') + '"' for t in terms)
                    where.append('p.rowid IN (SELECT rowid FROM posts_fts WHERE posts_fts MATCH ?)')
                    params.append(match)
                if tier:
                    where.append('EXISTS (SELECT 1 FROM signals s WHERE s.post_id=p.id AND s.tier=?)')
                    params.append(tier)
                clause = ' WHERE ' + ' AND '.join(where) if where else ''
                rows = db.execute('SELECT p.id, p.author, p.author_name, p.text, p.quoted_text, '
                                  'p.last_seen, p.created_at FROM posts p' + clause +
                                  ' ORDER BY p.last_seen DESC, p.id DESC LIMIT 51 OFFSET ?',
                                  params + [offset]).fetchall()
                result = {'posts': [dict(r) for r in rows[:50]], 'has_more': len(rows) > 50}
        except (ValueError, sqlite3.OperationalError):
            return self._json(400, {'error': 'Invalid search. Use up to 500 characters.'})
        finally:
            db.close()
        self._json(200, result)

    def do_POST(self):
        if not self._allowed():
            return self._json(403, {'error': 'local extension access only'})
        if self.path not in ('/ingest', '/event', '/delete'):
            return self._json(404, {'error': 'not found'})
        if self.headers.get('Content-Type', '').split(';')[0].strip() != 'application/json':
            return self._json(415, {'error': 'application/json required'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            return self._json(400, {'error': 'invalid content length'})
        if not 0 < length <= MAX_BODY:
            return self._json(413, {'error': 'body must be between 1 byte and 8 MB'})
        try:
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError()
            posts = payload.get('posts', [])
            signals = payload.get('signals', [])
            if not isinstance(posts, list) or not isinstance(signals, list):
                raise ValueError()
            if any(not isinstance(p, dict) for p in posts + signals):
                raise ValueError()
            if any(p.get('source', 'x') != 'x' for p in posts + signals):
                raise ValueError()
        except (ValueError, UnicodeDecodeError):
            return self._json(400, {'error': 'invalid X capture payload'})
        db = connect(READER_DB)
        try:
            if self.path == '/delete':
                if payload.get('confirm') != 'delete-reader-x':
                    return self._json(400, {'error': 'deletion confirmation required'})
                db.execute('PRAGMA secure_delete=ON')
                for table in ('posts', 'signals', 'tags', 'events'):
                    db.execute(f'DELETE FROM {table}')
                db.commit()
                db.execute('VACUUM')
                written = 0
            elif self.path == '/event':
                kind = payload.get('kind', 'unknown')
                if not isinstance(kind, str):
                    raise ValueError()
                db.execute('INSERT INTO events (at, kind, detail) VALUES (?,?,?)',
                           (now(), kind, json.dumps({k:v for k,v in payload.items() if k != 'kind'})))
                written = 0
            else:
                written = upsert_posts(db, posts, default_source='x')
                for sig in signals:
                    record_signal(db, sig)
            db.commit()
        except (ValueError, TypeError, AttributeError, OverflowError, sqlite3.Error):
            db.rollback()
            return self._json(400, {'error': 'invalid capture fields'})
        finally:
            db.close()
        self._json(200, {'ok': True, 'posts': written, 'signals': len(signals)})

    def log_message(self, fmt, *args):
        # Do not write search terms or post contents into terminal/service logs.
        pass


if __name__ == '__main__':
    connect(READER_DB).close()
    print(f'Reader listening on http://127.0.0.1:{PORT}', flush=True)
    HTTPServer(('127.0.0.1', PORT), Handler).serve_forever()
