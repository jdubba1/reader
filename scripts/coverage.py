#!/usr/bin/env python3
"""Report monthly post counts and date ranges by source and signal tier.

Missing months do not establish whether capture was complete.
"""
import argparse
import os
import sqlite3
import sys
from collections import Counter
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "daemon"))
from store import INSTAGRAM_DB, READER_DB  # noqa: E402


def months_between(a, b):
    out, y, m = [], a.year, a.month
    while (y, m) <= (b.year, b.month):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def parse_month(s):
    return date(int(s[:4]), int(s[5:7]), 1)


def report(db, source, tier):
    rows = db.execute(
        """
        SELECT substr(p.created_at, 1, 7) ym, count(*)
        FROM posts p JOIN signals s ON s.post_id = p.id
        WHERE p.source = ? AND s.tier = ? AND p.created_at IS NOT NULL
        GROUP BY ym ORDER BY ym
        """,
        (source, tier),
    ).fetchall()
    if not rows:
        return None

    counts = Counter(dict(rows))
    span = months_between(parse_month(rows[0][0]), parse_month(rows[-1][0]))
    total = sum(counts.values())
    empty = [m for m in span if counts.get(m, 0) == 0]

    print(f"\n=== {source} / {tier} ===")
    print(f"{total} posts, {rows[0][0]} → {rows[-1][0]} ({len(span)} months, {len(empty)} empty)")

    peak = max(counts.values())
    for m in span:
        c = counts.get(m, 0)
        bar = "#" * max(1, round(c / peak * 34)) if c else ""
        print(f"  {m}  {c:5d}  {bar}" + ("   << empty" if not c else ""))

    # Count consecutive empty months.
    runs, run = [], 0
    for m in span:
        if counts.get(m, 0) == 0:
            run += 1
        elif run:
            runs.append(run)
            run = 0
    if run:
        runs.append(run)
    if runs:
        print(f"  longest gap: {max(runs)} consecutive empty month(s)")
    return {"total": total, "first": rows[0][0], "last": rows[-1][0], "empty": len(empty)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier")
    ap.add_argument("--source")
    ap.add_argument("--ig", action="store_true", help="report on Instagram instead of X")
    args = ap.parse_args()

    db = sqlite3.connect(INSTAGRAM_DB if args.ig else READER_DB)
    pairs = db.execute(
        """
        SELECT p.source, s.tier, count(*) FROM posts p JOIN signals s ON s.post_id = p.id
        GROUP BY p.source, s.tier ORDER BY 3 DESC
        """
    ).fetchall()

    print("=== tiers present ===")
    for src, tier, n in pairs:
        print(f"  {src:10s} {tier:11s} {n}")

    for src, tier, _ in pairs:
        if args.tier and tier != args.tier:
            continue
        if args.source and src != args.source:
            continue
        report(db, src, tier)

    # Posts seen passively but never engaged with; the "read it, didn't save
    # it" pile, which only grows while browsing.
    n = db.execute(
        "SELECT count(*) FROM posts WHERE id NOT IN (SELECT post_id FROM signals)"
    ).fetchone()[0]
    print(f"\nposts with no signal at all (passive timeline sightings): {n}")


if __name__ == "__main__":
    main()
