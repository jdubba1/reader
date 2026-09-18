# Privacy

Reader 0.2.0 stores a local archive of X posts. It has no account, cloud service, analytics, advertising, or telemetry.

## What it handles

After you enable capture, Reader saves posts loaded by X: text, quoted text, author names and handles, IDs, timestamps, links, media URLs, available metrics, and reading/like/bookmark signals. This includes posts you may not read. Posts can contain personal or sensitive information. Media files are not downloaded.

Reader observes the X page's post responses and engagement requests. It does not read cookies, retain authentication headers, capture direct messages, or observe unrelated websites. Search terms go to the local companion and are not logged.

## Where data goes

Captures wait in Chrome local storage, then go over HTTP to `127.0.0.1:8787` on the same computer. The companion stores them in `data/reader.db`, or the path set by `READER_DB`. The queue holds at most 5,000 posts, 5,000 signals, and about 6 MiB; oldest items are dropped when full, with a count shown in Reader.

Reader sends no captured data to its developer or a remote service. It does not sell data or use it for advertising. The archive UI loads no remote images, fonts, or scripts. Original-post, help, and download links contact their respective sites when opened. X handles normal browsing under its own policies.

Reader does not encrypt its database or Chrome storage. Anyone with access to those files, backups, or exports may read them. The companion binds to loopback and blocks ordinary website origins, but other local programs and extensions can access it. Do not expose it through a proxy, tunnel, or public network.

## Controls and deletion

Capture starts paused. Enabling it saves new captures; pausing stops new saves while the existing queue continues syncing. Settings and counters remain in Chrome local storage until cleared or the extension is removed.

Setup & data can export the companion's X archive as JSON or delete it along with this extension's queue and counters. Sync before exporting to include pending captures. Deletion leaves capture paused. If the companion is offline, Reader clears the queue and requires you to reconnect and retry database deletion before resuming capture.

Deletion does not remove downloaded exports, backups, copies on X, or queues in other Chrome profiles. It is not a guarantee of forensic erasure. Uninstalling the extension removes its Chrome storage but leaves the database. To remove the default archive manually, stop the companion and delete `data/reader.db` and any `reader.db-*` sidecars. Remove exports and backups separately.

The optional Instagram importer reads a Meta export only when you run it and writes a separate `data/instagram.db`. The extension does not search, export, or delete that database. Delete it and the original Meta export separately.

## Contact

Report privacy issues at https://github.com/jdubba1/reader/issues. Issues are public; do not include captured posts, exports, credentials, or private logs.
