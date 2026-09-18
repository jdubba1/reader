#!/usr/bin/env python3
"""Import Instagram saved posts from a Meta data export into instagram.db.

    ./scripts/ingest_instagram.py raw/instagram/your_instagram_activity

Saved posts only by default. Pass --include-likes to import likes too.

Writes directly to instagram.db, never through the daemon, so Instagram data
cannot end up in the X index.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "daemon"))
from store import INSTAGRAM_DB, connect, upsert_posts  # noqa: E402

SOURCE = "instagram"


def labels(item):
    """Flatten Meta's label_values into a plain dict."""
    out = {}
    for lv in item.get("label_values", []):
        key = lv.get("label") or lv.get("title")
        if not key:
            continue
        if "value" in lv:
            out[key] = lv["value"]
        elif "dict" in lv:
            out[key] = lv["dict"]
    return out


def owner_of(flat):
    node = flat.get("Owner")
    if isinstance(node, list):
        for entry in node:
            for sub in entry.get("dict", []) if isinstance(entry, dict) else []:
                if sub.get("label") == "Name":
                    return sub.get("value")
    return None


def hashtags_of(flat):
    node = flat.get("Hashtags")
    if not isinstance(node, list):
        return []
    return [e["value"].lstrip("#") for e in node if isinstance(e, dict) and e.get("value")]


def convert(items, tier):
    posts = []
    for it in items:
        flat = labels(it)
        url = flat.get("URL")
        if not url:
            continue
        # The shortcode is Instagram's stable id.
        shortcode = url.rstrip("/").split("/")[-1]
        ts = it.get("timestamp")
        owner = owner_of(flat)
        posts.append(
            {
                "id": f"ig_{shortcode}",
                "source": SOURCE,
                "screen_name": owner,
                "name": owner,
                "created_at": datetime.fromtimestamp(ts, timezone.utc).strftime("%a %b %d %H:%M:%S +0000 %Y")
                if ts
                else None,
                "text": flat.get("Caption") or flat.get("Title") or "",
                "urls": [url],
                "hashtags": hashtags_of(flat),
                "media": [],
                "tier": tier,
            }
        )
    return posts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", help="path to your_instagram_activity/")
    ap.add_argument("--include-likes", action="store_true", help="also import liked posts (off by default)")
    ap.add_argument("--db", default=INSTAGRAM_DB)
    args = ap.parse_args()

    sources = [("saved/saved_posts.json", "bookmarked")]
    if args.include_likes:
        sources.append(("likes/liked_posts.json", "liked"))

    db = connect(args.db)
    total = 0
    try:
        for rel, tier in sources:
            path = os.path.join(args.root, rel)
            if not os.path.exists(path):
                print(f"skip {rel} (not in export)")
                continue
            with open(path) as f:
                raw = json.load(f)
            items = raw if isinstance(raw, list) else next(iter(raw.values()))
            posts = convert(items, tier)
            upsert_posts(db, posts, default_source=SOURCE)
            print(f"{rel}: {len(posts)} posts → {tier}")
            total += len(posts)
        db.commit()
    finally:
        db.close()
    print(f"{total} posts → {os.path.abspath(args.db)}")


if __name__ == "__main__":
    main()
