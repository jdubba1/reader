#!/usr/bin/env python3
"""Search the reader index.

Searches the X index by default. Instagram lives in its own database and is
only searched with --ig; no query returns both.

    ./scripts/query.py "sqlite"          full-text search (X)
    ./scripts/query.py --ig "recipe"          Instagram saved posts
    ./scripts/query.py --lane tooling         everything in one lane
    ./scripts/query.py --tier bookmarked -n 50
"""
import argparse
import json
import os
import sqlite3
import sys
import textwrap

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "daemon"))
from store import INSTAGRAM_DB, READER_DB  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="?", help="FTS5 query")
    ap.add_argument("--lane")
    ap.add_argument("--tier")
    ap.add_argument("--author")
    ap.add_argument("--ig", action="store_true", help="search Instagram saved posts instead of X")
    ap.add_argument("-n", type=int, default=20)
    args = ap.parse_args()

    db = sqlite3.connect(INSTAGRAM_DB if args.ig else READER_DB)
    db.row_factory = sqlite3.Row

    sql = "SELECT p.* FROM posts p"
    where, params = [], []
    if args.query:
        sql += " JOIN posts_fts f ON p.rowid = f.rowid"
        where.append("posts_fts MATCH ?")
        params.append(args.query)
    if args.tier:
        sql += " JOIN signals s ON s.post_id = p.id"
        where.append("s.tier = ?")
        params.append(args.tier)
    if args.lane:
        where.append("p.lane = ?")
        params.append(args.lane)
    if args.author:
        where.append("p.author = ? COLLATE NOCASE")
        params.append(args.author)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY p.created_at DESC LIMIT ?"
    params.append(args.n)

    rows = db.execute(sql, params).fetchall()
    for r in rows:
        date = (r["created_at"] or "")[:10]
        lane = f"  [{r['lane']}]" if r["lane"] else ""
        print(f"\n{date}  @{r['author']}{lane}")
        print(textwrap.fill(r["text"] or "", 88, initial_indent="  ", subsequent_indent="  "))
        if r["quoted_text"]:
            print(textwrap.fill("↳ " + r["quoted_text"], 88, initial_indent="  ", subsequent_indent="    "))
        for u in json.loads(r["urls"] or "[]"):
            print(f"  → {u}")
        if r["source"] == "x":
            print(f"  https://x.com/{r['author']}/status/{r['id']}")
    print(f"\n{len(rows)} result(s) from {'instagram' if args.ig else 'x'}")


if __name__ == "__main__":
    main()
