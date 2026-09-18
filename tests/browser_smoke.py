#!/usr/bin/env python3
"""Opt-in real Chrome test. Dev dependencies: Python Playwright + Chrome for Testing.
READER_CHROME=/path/to/chrome python3 tests/browser_smoke.py
Never uses an existing profile or database. Port 8787 must be free.
"""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import shutil
import zipfile
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('reader_test_server', ROOT / 'daemon/server.py')
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)
ASSETS = ROOT / 'docs/screenshots'
ASSETS.mkdir(parents=True, exist_ok=True)

POSTS = [
    ('900000000000000001', 'demo_archive', 'SQLite makes a small archive feel instant. Keep the original link beside the text so you can always return to the source.'),
    ('900000000000000002', 'demo_notebook', 'A useful reading habit: write down one idea you want to revisit, then search for it a week later.'),
    ('900000000000000003', 'demo_local', 'Local software can be quiet software. A folder, a search box, and a copy of the things you chose to keep.'),
]


def fixture():
    return {'data': {'timeline': {'entries': [
        {'tweet': {'__typename': 'Tweet', 'rest_id': pid,
                   'core': {'user_results': {'result': {'rest_id': 'demo', 'core': {'screen_name': author, 'name': 'Synthetic demo'}}}},
                   'legacy': {'full_text': text, 'created_at': 'Fri Sep 18 12:00:00 +0000 2026'}}}
        for pid, author, text in POSTS]}}}


PAGE = '''<!doctype html><html><body><h1>Synthetic X fixture</h1>
<button id="load" onclick="fetch('/i/api/graphql/synthetic/Bookmarks').then(r=>r.json())">Load demo posts</button>
<article data-testid="tweet"><a href="/demo_archive/status/900000000000000001">Synthetic post</a><p>SQLite makes a small archive feel instant.</p></article>
</body></html>'''


def run():
    with tempfile.TemporaryDirectory(prefix='reader-smoke-') as tmp, sync_playwright() as p:
        server.READER_DB = str(Path(tmp) / 'reader.db')
        # Fail before launching Chrome if the real companion already owns this port.
        class IsolatedHandler(server.Handler):
            extension_origin = None
            def _allowed(self):
                # Another installed Reader can retry into port 8787 while QA runs.
                # Only this temporary extension may write to the fixture database.
                if self.command in ('POST', 'OPTIONS') and self.headers.get('Origin') != self.extension_origin:
                    return False
                return super()._allowed()
        httpd = server.HTTPServer(('127.0.0.1', 8787), IsolatedHandler)
        def start():
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            return thread
        thread = start()
        executable = os.environ.get('READER_CHROME')
        extension = Path(tmp) / 'extension'
        if os.environ.get('READER_EXTENSION_ZIP'):
            with zipfile.ZipFile(os.environ['READER_EXTENSION_ZIP']) as archive:
                archive.extractall(extension)
        else:
            shutil.copytree(ROOT / 'extension', extension)
        args = ['--disable-extensions-except=' + str(extension), '--load-extension=' + str(extension)]
        options = dict(headless=True, args=args, viewport={'width': 1280, 'height': 800}, accept_downloads=True)
        if executable:
            options['executable_path'] = executable
        else:
            options['channel'] = 'chromium'
        ctx = None
        errors = []
        try:
            def launch():
                context = p.chromium.launch_persistent_context(str(Path(tmp) / 'profile'), **options)
                context.on('weberror', lambda e: errors.append(str(e.error)))
                # All X traffic is fulfilled locally. No login, cookie, or real post is used.
                def route(request):
                    if '/i/api/graphql/' in request.request.url:
                        request.fulfill(json=fixture())
                    else:
                        request.fulfill(content_type='text/html', body=PAGE)
                context.route('https://x.com/**', route)
                return context
            ctx = launch()
            worker = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event('serviceworker')
            base = worker.url.rsplit('/', 1)[0]
            IsolatedHandler.extension_origin = base
            page = ctx.new_page()
            page.goto(base + '/library.html')
            expect(page.locator('#connection')).to_contain_text('Companion connected')
            expect(page.locator('#toggle')).to_have_text('Enable local capture')
            expect(page.locator('#result-status')).to_contain_text('Your archive is empty')
            x = ctx.new_page()
            x.goto('https://x.com/home')
            x.locator('#load').click()
            x.wait_for_timeout(250)
            assert page.evaluate("chrome.runtime.sendMessage({type:'get-stats'})")['queuedPosts'] == 0
            page.locator('#toggle').click()
            expect(page.locator('#toggle')).to_have_text('Pause capture')
            x.reload()
            x.locator('#load').click()
            x.wait_for_timeout(2000)
            expect(page.locator('#queue')).to_contain_text('3 posts', timeout=10000)
            page.locator('#retry').click()
            expect(page.locator('#results article')).to_have_count(3)
            with server.connect(server.READER_DB) as db:
                assert {row[0] for row in db.execute('SELECT id FROM posts')} == {row[0] for row in POSTS}
            expect(page.locator('#results a').first).to_have_attribute('href', 'https://x.com/i/status/' + POSTS[2][0])
            page.locator('#query').fill('SQLite')
            page.locator('#search button').click()
            expect(page.locator('#results article')).to_have_count(1)
            page.locator('#query').fill('nonexistentword')
            page.locator('#search button').click()
            expect(page.locator('#result-status')).to_contain_text('No matching posts')
            page.locator('#query').fill('')
            page.locator('#tier').select_option('bookmarked')
            page.locator('#search button').click()
            expect(page.locator('#results article')).to_have_count(3)
            page.locator('#tier').select_option('viewed')
            page.locator('#search button').click()
            expect(page.locator('#results article')).to_have_count(1)
            page.locator('#tier').select_option('bookmarked')
            page.locator('#search button').click()
            expect(page.locator('#results article')).to_have_count(3)
            page.screenshot(path=str(ASSETS / 'search.png'))
            page.locator('#setup').scroll_into_view_if_needed()
            page.screenshot(path=str(ASSETS / 'setup.png'))
            with page.expect_download() as downloaded:
                page.locator('#export').click()
            export = json.loads(Path(downloaded.value.path()).read_text())
            assert len(export['posts']) == 3 and export['format'] == 'reader-x'
            # Offline captures survive a complete browser/worker restart.
            httpd.shutdown(); thread.join(); httpd.server_close()
            x.locator('#load').click()
            page.locator('#retry').click()
            expect(page.locator('#connection')).to_contain_text('disconnected', timeout=15000)
            expect(page.locator('#queue')).to_contain_text('3 posts')
            ctx.close(); ctx = launch()
            page = ctx.new_page(); page.goto(base + '/library.html')
            expect(page.locator('#queue')).to_contain_text('3 posts')
            expect(page.locator('#toggle')).to_have_text('Pause capture')
            httpd = server.HTTPServer(('127.0.0.1', 8787), IsolatedHandler)
            thread = start()
            page.locator('#retry').click()
            expect(page.locator('#connection')).to_contain_text('3 posts archived')
            expect(page.locator('#queue')).to_contain_text('0 posts and 0 signals')
            # Pause, delete, verify the real database and derived FTS index are empty.
            page.locator('#toggle').click()
            expect(page.locator('#toggle')).to_have_text('Resume capture')
            page.locator('#delete-open').click()
            page.locator('#confirmation').fill('DELETE')
            page.locator('#delete').click()
            expect(page.locator('#notice')).to_contain_text('X archive and queue deleted')
            expect(page.locator('#results article')).to_have_count(0)
            assert page.evaluate("chrome.runtime.sendMessage({type:'get-stats'})")['enabled'] is False
            with server.connect(server.READER_DB) as db:
                assert db.execute('SELECT count(*) FROM posts').fetchone()[0] == 0
                assert db.execute("SELECT count(*) FROM posts_fts WHERE posts_fts MATCH 'SQLite'").fetchone()[0] == 0
            popup = ctx.new_page(); popup.goto(base + '/popup.html')
            expect(popup.locator('#connection')).to_contain_text('Connected. 0 posts archived.')
            expect(popup.locator('#capture')).to_contain_text('Capture paused')
            assert not errors, errors
            print('PASS: Chrome ' + ctx.browser.version + '; opt-in, real content-script capture, search, filters, links, empty state, export, offline queue, browser restart, reconnect, deletion, popup. Synthetic X fixture only.')
        finally:
            if ctx: ctx.close()
            httpd.shutdown(); thread.join(); httpd.server_close()


if __name__ == '__main__':
    run()
