#!/usr/bin/env python3
"""Build auditable release ZIPs from explicit file lists, never git history/data."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
EXTENSION = [
    'manifest.json', 'background.js', 'content.js', 'inject.js',
    'popup.html', 'popup.js', 'library.html', 'library.js', 'ui.css', 'privacy.html',
    *[f'icons/{n}.png' for n in (16, 32, 48, 128)],
]
COMPANION = [
    'daemon/server.py', 'daemon/store.py', 'scripts/companion.py',
    'scripts/query.py', 'scripts/coverage.py', 'scripts/ingest_instagram.py',
    'Start Reader.command', 'Start Reader.bat', 'README.md', 'PRIVACY.md', 'LICENSE',
    'docs/screenshots/search.png',
]


def build(source, files, destination):
    with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(files):
            path = source / name
            if not path.is_file() or path.is_symlink():
                raise ValueError(f'Missing file or symlink: {name}')
            entry = zipfile.ZipInfo(name, date_time=(2026, 9, 18, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = (0o100755 if name.endswith('.command') else 0o100644) << 16
            archive.writestr(entry, path.read_bytes())
    return hashlib.sha256(destination.read_bytes()).hexdigest()


def main():
    manifest = json.loads((ROOT / 'extension/manifest.json').read_text())
    assert manifest['permissions'] == ['storage', 'alarms']
    assert len(manifest['description']) <= 132
    out = ROOT / 'dist'
    out.mkdir(exist_ok=True)
    checksums = []
    packages = [
        ('reader', ROOT, COMPANION + ['extension/' + name for name in EXTENSION]),
        ('reader-extension', ROOT / 'extension', EXTENSION),
        ('reader-companion', ROOT, COMPANION),
    ]
    for name_prefix, base, files in packages:
        name = f'{name_prefix}-{manifest["version"]}.zip'
        checksum = build(base, files, out / name)
        checksums.append(f'{checksum}  {name}')
    (out / 'SHA256SUMS').write_text('\n'.join(checksums) + '\n')
    print('\n'.join(checksums))


if __name__ == '__main__':
    main()
