#!/usr/bin/env python3
"""
import_csv.py — add vocabulary to the NT Greek Flashcards database from a CSV.

Use this to extend the built-in top-300 words to the full 500 (banks 4 and 5),
or to create any custom deck of your own.

The database is the SAME one the web app uses. It is found via the KOINE_DB
environment variable, falling back to ./koine.db next to this script — exactly
like app.py. Run the app once first (so the schema exists), or this script will
create the schema itself.

--------------------------------------------------------------------------------
CSV FORMAT
--------------------------------------------------------------------------------
A header row is required. Recognised columns (case-insensitive):

    front   (required)  the prompt shown on the card — e.g. the Greek lemma
    back    (required)  the answer — e.g. the English gloss
    hint    (optional)  a small hint under the prompt — e.g. transliteration
    extra   (optional)  a tag shown after the answer — e.g. "verb", "rank 312"

Example rows (banks-4-5-template.csv ships with this project):

    front,back,hint,extra
    πλοῖον,"boat, ship",ploion,noun · rank 312
    σπείρω,"I sow",speirō,verb · rank 313

--------------------------------------------------------------------------------
USAGE
--------------------------------------------------------------------------------
    python3 import_csv.py FILE.csv --slug freq-4 --name "Bank 4 · 301–400" \
            --group "Frequency banks" --subtitle "the most common words in the NT"

If a deck with --slug already exists, new cards are APPENDED to it (deck
metadata is left unchanged). If it does not exist, the deck is created.

    --replace   delete the deck's existing cards before importing (a clean
                re-import; progress rows for removed cards are cascaded away)

    --dry-run   parse and report, but write nothing

After importing, restart the app (or it will pick the new deck up on the next
request, since decks are read live from the DB).
"""

from __future__ import annotations

import argparse
import csv
import os
import sqlite3
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("KOINE_DB", os.path.join(BASE_DIR, "koine.db"))

# Minimal schema mirror so the script is usable even before the app has run.
SCHEMA = """
CREATE TABLE IF NOT EXISTS decks (
    id          INTEGER PRIMARY KEY,
    slug        TEXT UNIQUE NOT NULL,
    group_name  TEXT NOT NULL,
    name        TEXT NOT NULL,
    subtitle    TEXT,
    sort_order  INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS cards (
    id         INTEGER PRIMARY KEY,
    deck_id    INTEGER NOT NULL REFERENCES decks(id) ON DELETE CASCADE,
    front      TEXT NOT NULL,
    back       TEXT NOT NULL,
    hint       TEXT,
    extra      TEXT,
    sort_order INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_cards_deck ON cards(deck_id);
"""


def read_rows(path: str) -> list[dict]:
    """Read the CSV and return a list of normalised card dicts."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            sys.exit("error: the CSV appears to be empty")

        # map lower-cased header -> actual header key
        headers = {h.lower().strip(): h for h in reader.fieldnames}
        for required in ("front", "back"):
            if required not in headers:
                sys.exit(
                    f"error: CSV must have a '{required}' column "
                    f"(found: {', '.join(reader.fieldnames)})"
                )

        rows: list[dict] = []
        for i, raw in enumerate(reader, start=2):  # row 1 is the header
            front = (raw.get(headers["front"]) or "").strip()
            back = (raw.get(headers["back"]) or "").strip()
            if not front and not back:
                continue  # skip blank lines
            if not front or not back:
                sys.exit(f"error: row {i} is missing front or back")
            rows.append({
                "front": front,
                "back": back,
                "hint": (raw.get(headers["hint"]).strip()
                         if "hint" in headers and raw.get(headers["hint"]) else None),
                "extra": (raw.get(headers["extra"]).strip()
                          if "extra" in headers and raw.get(headers["extra"]) else None),
            })
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Import flashcards from a CSV into the NT Greek Flashcards DB.",
    )
    ap.add_argument("csv", help="path to the CSV file")
    ap.add_argument("--slug", required=True,
                    help="deck slug, e.g. freq-4 (unique id, no spaces)")
    ap.add_argument("--name", help="deck display name, e.g. 'Bank 4 · 301–400'")
    ap.add_argument("--group", default="Frequency banks",
                    help="menu group heading (default: 'Frequency banks')")
    ap.add_argument("--subtitle", default=None, help="small text under the name")
    ap.add_argument("--replace", action="store_true",
                    help="delete the deck's existing cards before importing")
    ap.add_argument("--dry-run", action="store_true",
                    help="parse and report only; write nothing")
    args = ap.parse_args()

    if not os.path.exists(args.csv):
        sys.exit(f"error: file not found: {args.csv}")

    rows = read_rows(args.csv)
    print(f"parsed {len(rows)} card(s) from {args.csv}")
    if args.dry_run:
        for r in rows[:5]:
            print("  ", r)
        if len(rows) > 5:
            print(f"   … and {len(rows) - 5} more")
        print("dry run — nothing written")
        return
    if not rows:
        sys.exit("nothing to import")

    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(SCHEMA)

    existing = db.execute(
        "SELECT id FROM decks WHERE slug = ?", (args.slug,)
    ).fetchone()

    if existing:
        deck_id = existing[0]
        if args.replace:
            db.execute("DELETE FROM cards WHERE deck_id = ?", (deck_id,))
            print(f"replaced existing cards in deck '{args.slug}'")
        else:
            print(f"appending to existing deck '{args.slug}'")
    else:
        name = args.name or args.slug
        # place new deck after all current decks
        max_order = db.execute(
            "SELECT COALESCE(MAX(sort_order), 0) FROM decks"
        ).fetchone()[0]
        cur = db.execute(
            "INSERT INTO decks (slug, group_name, name, subtitle, sort_order) "
            "VALUES (?,?,?,?,?)",
            (args.slug, args.group, name, args.subtitle, max_order + 1),
        )
        deck_id = cur.lastrowid
        print(f"created deck '{args.slug}' ({name})")

    start = db.execute(
        "SELECT COALESCE(MAX(sort_order), -1) FROM cards WHERE deck_id = ?",
        (deck_id,),
    ).fetchone()[0] + 1

    db.executemany(
        "INSERT INTO cards (deck_id, front, back, hint, extra, sort_order) "
        "VALUES (?,?,?,?,?,?)",
        [(deck_id, r["front"], r["back"], r["hint"], r["extra"], start + i)
         for i, r in enumerate(rows)],
    )
    db.commit()
    total = db.execute(
        "SELECT COUNT(*) FROM cards WHERE deck_id = ?", (deck_id,)
    ).fetchone()[0]
    db.close()

    print(f"imported {len(rows)} card(s); deck now has {total} card(s)")
    print("restart the app (or just reload the menu) to see the changes.")


if __name__ == "__main__":
    main()
