"""
Koine — a Biblical (New Testament) Greek flashcard app.

A single-file Flask backend backed by SQLite. It handles:
  - user accounts (register / login / logout) with hashed passwords
  - a tree of decks (alphabet, grammar terms, word types, frequency banks)
  - flashcards for each deck
  - per-user progress with Leitner-style spaced repetition

The frontend is plain HTML/CSS/JS in ./templates and ./static (no build step),
which keeps deployment on a Proxmox LXC or VM trivial.
"""

import os
import sqlite3
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import (
    Flask, g, jsonify, request, session, render_template, send_from_directory
)
from werkzeug.security import generate_password_hash, check_password_hash

import seed  # local module holding all the card content

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("KOINE_DB", os.path.join(BASE_DIR, "koine.db"))
SECRET_FILE = os.path.join(BASE_DIR, "secret_key")

# Leitner boxes -> how many days until a card is due again.
# Box 0 is "new / just failed"; it comes back inside the same session.
BOX_INTERVALS_DAYS = {0: 0, 1: 1, 2: 3, 3: 7, 4: 16, 5: 35, 6: 90}
MAX_BOX = 6

app = Flask(__name__, static_folder="static", template_folder="templates")


def _load_secret_key() -> bytes:
    """Persist a secret key on disk so sessions survive restarts."""
    if os.path.exists(SECRET_FILE):
        with open(SECRET_FILE, "rb") as fh:
            return fh.read()
    key = secrets.token_bytes(32)
    with open(SECRET_FILE, "wb") as fh:
        fh.write(key)
    os.chmod(SECRET_FILE, 0o600)
    return key


app.secret_key = _load_secret_key()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(days=90),
)


# --------------------------------------------------------------------------- #
# Database helpers
# --------------------------------------------------------------------------- #

def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

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

CREATE TABLE IF NOT EXISTS progress (
    user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    card_id   INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    box       INTEGER NOT NULL DEFAULT 0,
    correct   INTEGER NOT NULL DEFAULT 0,
    wrong     INTEGER NOT NULL DEFAULT 0,
    last_seen TEXT,
    due_at    TEXT,
    PRIMARY KEY (user_id, card_id)
);

CREATE INDEX IF NOT EXISTS idx_cards_deck ON cards(deck_id);
CREATE INDEX IF NOT EXISTS idx_progress_user ON progress(user_id);
"""


def init_db() -> None:
    """Create tables and load seed content if the DB is empty."""
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)

    have = db.execute("SELECT COUNT(*) AS n FROM decks").fetchone()["n"]
    if have == 0:
        _seed_content(db)
    db.commit()
    db.close()


def _seed_content(db: sqlite3.Connection) -> None:
    """Insert decks + cards from seed.DECKS."""
    for order, deck in enumerate(seed.DECKS):
        cur = db.execute(
            "INSERT INTO decks (slug, group_name, name, subtitle, sort_order) "
            "VALUES (?,?,?,?,?)",
            (deck["slug"], deck["group"], deck["name"],
             deck.get("subtitle"), order),
        )
        deck_id = cur.lastrowid
        for c_order, card in enumerate(deck["cards"]):
            db.execute(
                "INSERT INTO cards (deck_id, front, back, hint, extra, sort_order) "
                "VALUES (?,?,?,?,?,?)",
                (deck_id, card[0], card[1],
                 card[2] if len(card) > 2 else None,
                 card[3] if len(card) > 3 else None,
                 c_order),
            )


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return jsonify(error="Not signed in"), 401
        return fn(*args, **kwargs)
    return wrapper


def current_user_id() -> int:
    return session["user_id"]


@app.post("/api/register")
def register():
    data = request.get_json(force=True, silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if len(username) < 2:
        return jsonify(error="Pick a username with at least 2 characters."), 400
    if len(password) < 6:
        return jsonify(error="Use a password with at least 6 characters."), 400

    db = get_db()
    exists = db.execute(
        "SELECT 1 FROM users WHERE username = ?", (username,)
    ).fetchone()
    if exists:
        return jsonify(error="That username is taken."), 409

    cur = db.execute(
        "INSERT INTO users (username, password_hash, created_at) VALUES (?,?,?)",
        (username, generate_password_hash(password),
         datetime.now(timezone.utc).isoformat()),
    )
    db.commit()
    session.permanent = True
    session["user_id"] = cur.lastrowid
    session["username"] = username
    return jsonify(username=username)


@app.post("/api/login")
def login():
    data = request.get_json(force=True, silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    db = get_db()
    row = db.execute(
        "SELECT * FROM users WHERE username = ?", (username,)
    ).fetchone()
    if row is None or not check_password_hash(row["password_hash"], password):
        return jsonify(error="Wrong username or password."), 401

    session.permanent = True
    session["user_id"] = row["id"]
    session["username"] = row["username"]
    return jsonify(username=row["username"])


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


@app.get("/api/me")
def me():
    if "user_id" not in session:
        return jsonify(user=None)
    return jsonify(user={"username": session.get("username")})


# --------------------------------------------------------------------------- #
# Decks & cards
# --------------------------------------------------------------------------- #

def _now():
    return datetime.now(timezone.utc)


@app.get("/api/decks")
@login_required
def list_decks():
    """Return decks grouped for the menu, with per-user counts."""
    db = get_db()
    uid = current_user_id()
    now_iso = _now().isoformat()

    rows = db.execute(
        """
        SELECT d.id, d.slug, d.group_name, d.name, d.subtitle, d.sort_order,
               COUNT(c.id) AS total,
               COALESCE(SUM(CASE WHEN p.box >= 4 THEN 1 ELSE 0 END), 0) AS learned,
               COALESCE(SUM(
                   CASE WHEN p.card_id IS NULL
                             OR p.due_at IS NULL
                             OR p.due_at <= ? THEN 1 ELSE 0 END), 0) AS due
        FROM decks d
        LEFT JOIN cards c ON c.deck_id = d.id
        LEFT JOIN progress p ON p.card_id = c.id AND p.user_id = ?
        GROUP BY d.id
        ORDER BY d.sort_order
        """,
        (now_iso, uid),
    ).fetchall()

    groups = {}
    order = []
    for r in rows:
        grp = r["group_name"]
        if grp not in groups:
            groups[grp] = []
            order.append(grp)
        groups[grp].append({
            "slug": r["slug"],
            "name": r["name"],
            "subtitle": r["subtitle"],
            "total": r["total"],
            "learned": r["learned"],
            "due": r["due"],
        })
    return jsonify(groups=[{"name": g, "decks": groups[g]} for g in order])


@app.get("/api/deck/<slug>/session")
@login_required
def deck_session(slug):
    """
    Build a study session: due/new cards first (spaced repetition),
    capped by ?limit (default 24). ?mode=all returns every card in order.
    """
    db = get_db()
    uid = current_user_id()
    deck = db.execute("SELECT * FROM decks WHERE slug = ?", (slug,)).fetchone()
    if deck is None:
        return jsonify(error="No such deck."), 404

    mode = request.args.get("mode", "srs")
    try:
        limit = max(1, min(200, int(request.args.get("limit", 24))))
    except ValueError:
        limit = 24
    now_iso = _now().isoformat()

    if mode == "all":
        rows = db.execute(
            """
            SELECT c.*, p.box, p.correct, p.wrong, p.due_at
            FROM cards c
            LEFT JOIN progress p ON p.card_id = c.id AND p.user_id = ?
            WHERE c.deck_id = ?
            ORDER BY c.sort_order
            """,
            (uid, deck["id"]),
        ).fetchall()
    else:
        rows = db.execute(
            """
            SELECT c.*, p.box, p.correct, p.wrong, p.due_at
            FROM cards c
            LEFT JOIN progress p ON p.card_id = c.id AND p.user_id = ?
            WHERE c.deck_id = ?
              AND (p.card_id IS NULL OR p.due_at IS NULL OR p.due_at <= ?)
            ORDER BY (p.due_at IS NULL) DESC, p.due_at ASC, c.sort_order
            LIMIT ?
            """,
            (uid, deck["id"], now_iso, limit),
        ).fetchall()

    cards = [{
        "id": r["id"],
        "front": r["front"],
        "back": r["back"],
        "hint": r["hint"],
        "extra": r["extra"],
        "box": r["box"] if r["box"] is not None else 0,
    } for r in rows]

    return jsonify(deck={"slug": deck["slug"], "name": deck["name"],
                         "subtitle": deck["subtitle"]},
                   cards=cards)


@app.post("/api/review")
@login_required
def review():
    """
    Record a review result and reschedule the card.
    Body: { "card_id": int, "grade": "again" | "good" | "easy" }
    """
    data = request.get_json(force=True, silent=True) or {}
    card_id = data.get("card_id")
    grade = data.get("grade")
    if grade not in ("again", "good", "easy") or not isinstance(card_id, int):
        return jsonify(error="Bad review payload."), 400

    db = get_db()
    uid = current_user_id()
    row = db.execute(
        "SELECT box, correct, wrong FROM progress WHERE user_id = ? AND card_id = ?",
        (uid, card_id),
    ).fetchone()
    box = row["box"] if row else 0
    correct = row["correct"] if row else 0
    wrong = row["wrong"] if row else 0

    if grade == "again":
        box = 0
        wrong += 1
    elif grade == "good":
        box = min(MAX_BOX, box + 1)
        correct += 1
    else:  # easy
        box = min(MAX_BOX, box + 2)
        correct += 1

    now = _now()
    due = now + timedelta(days=BOX_INTERVALS_DAYS.get(box, 1))
    db.execute(
        """
        INSERT INTO progress (user_id, card_id, box, correct, wrong, last_seen, due_at)
        VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(user_id, card_id) DO UPDATE SET
            box=excluded.box, correct=excluded.correct, wrong=excluded.wrong,
            last_seen=excluded.last_seen, due_at=excluded.due_at
        """,
        (uid, card_id, box, correct, wrong, now.isoformat(), due.isoformat()),
    )
    db.commit()
    return jsonify(box=box, due_at=due.isoformat())


@app.post("/api/deck/<slug>/reset")
@login_required
def reset_deck(slug):
    """Wipe the user's progress for one deck (start it over)."""
    db = get_db()
    uid = current_user_id()
    deck = db.execute("SELECT id FROM decks WHERE slug = ?", (slug,)).fetchone()
    if deck is None:
        return jsonify(error="No such deck."), 404
    db.execute(
        "DELETE FROM progress WHERE user_id = ? AND card_id IN "
        "(SELECT id FROM cards WHERE deck_id = ?)",
        (uid, deck["id"]),
    )
    db.commit()
    return jsonify(ok=True)


# --------------------------------------------------------------------------- #
# Frontend
# --------------------------------------------------------------------------- #

@app.get("/")
def index():
    return render_template("index.html")


@app.get("/health")
def health():
    return jsonify(ok=True)


init_db()

if __name__ == "__main__":
    # Dev server only. Use gunicorn in production (see README).
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=False)
