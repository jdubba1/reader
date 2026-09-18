#!/usr/bin/env python3
"""Smoke-test the packaged companion, including startup and port conflict handling."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
from urllib.request import urlopen
import zipfile

ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='reader-companion-') as tmp:
    with zipfile.ZipFile(ROOT / 'dist/reader-companion-0.2.0.zip') as archive:
        archive.extractall(tmp)
    env = {**os.environ, 'READER_DB': str(Path(tmp) / 'data/reader.db'), 'READER_PORT':'8787'}
    command = [sys.executable, '-u', str(Path(tmp) / 'scripts/companion.py')]
    process = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        first = process.stdout.readline()
        assert first.startswith('Reader is ready.'), first
        with urlopen('http://127.0.0.1:8787/stats', timeout=5) as response:
            stats = json.load(response)
        assert stats['service'] == 'reader' and stats['posts'] == 0
        conflict = subprocess.run(command, env=env, capture_output=True, text=True, timeout=5)
        assert conflict.returncode == 1 and 'port 8787' in conflict.stdout
        process.send_signal(signal.SIGINT)
        output = process.communicate(timeout=5)[0]
        assert process.returncode == 0 and 'Reader stopped.' in output
        print('PASS: packaged companion startup, temporary SQLite archive, health endpoint, port conflict, clean shutdown.')
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
