"""SQLite store shared by the ingest daemon and the offline importers.

Each source gets its own database file. The daemon owns reader.db (X only);
Instagram is imported straight into instagram.db and never passes through the
daemon, so the two can't be mixed by accident.
"""
import json
import os
import sqlite3
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id            TEXT PRIMARY KEY,
    source        TEXT NOT NULL,
    author        TEXT,
    author_name   TEXT,
    author_id     TEXT,
    created_at    TEXT,
    text          TEXT,
    quoted_text   TEXT,
    quoted_author TEXT,
    urls          TEXT,
    hashtags      TEXT,
    symbols       TEXT,
    media         TEXT,
    metrics       TEXT,
    lang          TEXT,
    -- Reply context.
    in_reply_to      TEXT,
    conversation_id  TEXT,
    first_seen    TEXT NOT NULL,
    last_seen     TEXT NOT NULL,
    lane          TEXT,
    entities      TEXT,
    classified_at TEXT,
    -- Optional imported text; Reader does not extract text from media.
    media_text    TEXT
);

CREATE TABLE IF NOT EXISTS signals (
    post_id TEXT NOT NULL,
    tier    TEXT NOT NULL,
    at      TEXT NOT NULL,
    PRIMARY KEY (post_id, tier)
);

-- Retained for existing archives and API clients.
CREATE TABLE IF NOT EXISTS events (
    at      TEXT NOT NULL,
    kind    TEXT NOT NULL,
    detail  TEXT
);

-- Optional labels retained for compatibility with existing databases.
CREATE TABLE IF NOT EXISTS tags (
    post_id TEXT NOT NULL,
    tag     TEXT NOT NULL,
    PRIMARY KEY (post_id, tag)
);

CREATE INDEX IF NOT EXISTS idx_tags_tag     ON tags(tag);
CREATE INDEX IF NOT EXISTS idx_posts_created ON posts(created_at);
CREATE INDEX IF NOT EXISTS idx_posts_lane    ON posts(lane);
CREATE INDEX IF NOT EXISTS idx_signals_tier  ON signals(tier);

CREATE VIRTUAL TABLE IF NOT EXISTS posts_fts USING fts5(
    text, quoted_text, author, media_text, content='posts', content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS posts_ai AFTER INSERT ON posts BEGIN
    INSERT INTO posts_fts(rowid, text, quoted_text, author, media_text)
    VALUES (new.rowid, new.text, new.quoted_text, new.author, new.media_text);
END;
CREATE TRIGGER IF NOT EXISTS posts_ad AFTER DELETE ON posts BEGIN
    INSERT INTO posts_fts(posts_fts, rowid, text, quoted_text, author, media_text)
    VALUES ('delete', old.rowid, old.text, old.quoted_text, old.author, old.media_text);
END;
CREATE TRIGGER IF NOT EXISTS posts_au AFTER UPDATE ON posts BEGIN
    INSERT INTO posts_fts(posts_fts, rowid, text, quoted_text, author, media_text)
    VALUES ('delete', old.rowid, old.text, old.quoted_text, old.author, old.media_text);
    INSERT INTO posts_fts(rowid, text, quoted_text, author, media_text)
    VALUES (new.rowid, new.text, new.quoted_text, new.author, new.media_text);
END;
"""

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
READER_DB = os.environ.get("READER_DB", os.path.join(DATA_DIR, "reader.db"))
INSTAGRAM_DB = os.environ.get("INSTAGRAM_DB", os.path.join(DATA_DIR, "instagram.db"))


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def iso(created_at):
    """X sends 'Wed Jul 30 08:53:45 +0000 2026'."""
    if not created_at:
        return None
    try:
        return parsedate_to_datetime(created_at).astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        return created_at


def migrate(db):
    """Bring an existing database up to the current SCHEMA.

    `CREATE TABLE IF NOT EXISTS` is a no-op on a table that already exists, so
    new columns and a changed FTS shape have to be applied by hand. The FTS
    table is derived from posts, so dropping and rebuilding it is safe.
    """
    have = {r[1] for r in db.execute("PRAGMA table_info(posts)")}
    if not have:
        return  # fresh database; SCHEMA will create everything
    for col in ("media_text", "in_reply_to", "conversation_id"):
        if col not in have:
            db.execute(f"ALTER TABLE posts ADD COLUMN {col} TEXT")

    fts = db.execute("SELECT sql FROM sqlite_master WHERE name='posts_fts'").fetchone()
    if fts and "media_text" not in (fts[0] or ""):
        # Triggers reference the old column list; drop them with the table so
        # SCHEMA can recreate both in their current shape.
        for t in ("posts_ai", "posts_ad", "posts_au"):
            db.execute(f"DROP TRIGGER IF EXISTS {t}")
        db.execute("DROP TABLE posts_fts")
        db.commit()
        return True  # caller rebuilds the index after SCHEMA runs
    return False


def connect(path=READER_DB):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    db = sqlite3.connect(path)
    rebuilt = migrate(db)
    db.executescript(SCHEMA)
    if rebuilt:
        db.execute("INSERT INTO posts_fts(posts_fts) VALUES('rebuild')")
        db.commit()
    return db


def upsert_posts(db, posts, default_source="x"):
    written = 0
    for p in posts:
        pid = p.get("id")
        if not pid:
            continue
        q = p.get("quoted") or {}
        db.execute(
            """
            INSERT INTO posts (id, source, author, author_name, author_id, created_at, text,
                               quoted_text, quoted_author, urls, hashtags, symbols, media,
                               metrics, lang, in_reply_to, conversation_id, first_seen, last_seen)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                last_seen = excluded.last_seen,
                metrics   = excluded.metrics,
                -- long-form bodies arrive later than the truncated version
                text      = CASE WHEN length(excluded.text) > length(posts.text)
                                 THEN excluded.text ELSE posts.text END
            """,
            (
                pid,
                p.get("source", default_source),
                p.get("screen_name"),
                p.get("name"),
                p.get("user_id"),
                iso(p.get("created_at")),
                p.get("text", ""),
                q.get("text"),
                q.get("screen_name"),
                json.dumps(p.get("urls") or []),
                json.dumps(p.get("hashtags") or []),
                json.dumps(p.get("symbols") or []),
                json.dumps(p.get("media") or []),
                json.dumps(
                    {
                        k: p.get(k)
                        for k in ("favorite_count", "retweet_count", "reply_count", "bookmark_count", "view_count")
                        if p.get(k) is not None
                    }
                ),
                p.get("lang"),
                p.get("in_reply_to"),
                p.get("conversation_id"),
                now(),
                now(),
            ),
        )
        written += 1
        tier = p.get("tier")
        if tier and tier != "fetched":
            record_signal(db, {"id": pid, "tier": tier, "at": now()})
    return written


def record_signal(db, sig):
    pid, tier = sig.get("id"), sig.get("tier")
    if not pid or not tier:
        return
    db.execute(
        "INSERT INTO signals (post_id, tier, at) VALUES (?,?,?) "
        "ON CONFLICT(post_id, tier) DO NOTHING",
        (pid, tier, sig.get("at") or now()),
    )
