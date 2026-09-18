#!/usr/bin/env python3
"""Friendly foreground launcher, with no dependencies outside Python."""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'daemon'))


def main():
    if sys.version_info < (3, 10):
        print('Reader needs Python 3.10 or newer. Install it from https://python.org/downloads/')
        return 1
    from server import HTTPServer, Handler, PORT, READER_DB, connect
    if PORT != 8787:
        print('The Chrome extension connects to port 8787. Remove READER_PORT and try again.')
        return 1
    try:
        connect(READER_DB).close()
        httpd = HTTPServer(('127.0.0.1', PORT), Handler)
    except OSError as error:
        print(f'Could not start Reader: {error}\nIf Reader is already running, use its existing window. Otherwise free port 8787 and retry.')
        return 1
    except Exception as error:
        print(f'Could not open the archive: {error}\nCheck folder permissions and that Python includes SQLite FTS5. Keep a backup before repairing any database.')
        return 1
    print(f'Reader is ready. Open the Chrome extension and click Check connection & sync.\nArchive: {os.path.abspath(READER_DB)}\nKeep this window open. Press Ctrl+C to stop. Restart this launcher after reboot.', flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\nReader stopped. Queued captures will sync when you start it again.')
    finally:
        httpd.server_close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
