# NT Greek Flashcards

A small, self-hosted web app for learning Biblical (Koine) New Testament Greek
with spaced-repetition flashcards. Built to run on your own Proxmox box (an LXC
container or a small VM) with no external services.

- **Backend:** Python + Flask, storing everything in a single **SQLite** file.
- **Frontend:** a reactive single-page app in plain HTML/CSS/JavaScript — no
  build step, no npm, nothing to compile.
- **Accounts:** simple username/password login, only so each learner's progress
  is remembered. Passwords are stored hashed (never in plaintext).
- **Scheduling:** a Leitner-box spaced-repetition system (boxes 0–6) that shows
  you cards when they're due and pushes mastered cards further into the future.

---

## What you can study

Pick a deck from the hamburger (☰) menu. Decks are grouped:

- **Alphabet** — the letters in two scripts:
  - *Minuscule* (lowercase) with letter names and sounds
  - *Uncial* (majuscule / capital) letters
- **Grammar terms** — the vocabulary of grammar itself: parts of speech, the
  noun cases, verb tenses, voices, moods, verbal forms, and number/gender/person.
- **Word types** — the closed-class words worth memorising as sets: all the
  prepositions, conjunctions, adverbs, particles, and the proper nouns.
- **Frequency banks** — the most common words in the NT, in banks of 100:
  - Bank 1 · top 100
  - Bank 2 · 101–200
  - Bank 3 · 201–300
  - *(Banks 4 and 5 — words 301–500 — are added by you via CSV; see
    ["Extending to the full 500"](#extending-to-the-full-500) below.)*

Study controls: click a card (or press **Space**) to flip it, then grade
yourself **Again / Good / Easy** (or press **1 / 2 / 3**). "Again" brings the
card back later in the same session; "Good" and "Easy" schedule it further out.

---

## A note on the vocabulary content

The card content lives in `seed.py` as plain data, so you can read and correct
anything. Two honesty notes, because this is a language tool and accuracy
matters more than looking complete:

- The glosses are **study glosses** — short, memorisable meanings, not full
  lexicon entries. A word like a preposition genuinely shifts meaning by case;
  the card gives you the hook, not the whole BDAG article.
- I seeded the **top 300** frequency words (three banks), not all 500. Producing
  200 more correctly-**accented** lemmas with correct ranks from memory is
  exactly the kind of task where small errors accumulate silently, and a wrong
  breathing mark or accent in a Greek study tool is worse than an honest gap.
  The path to the full 500 is the CSV importer below, pointed at an
  authoritative list — so the words you add are verified, not guessed.

Whatever you study, it's worth spot-checking accents and glosses against a
reference you trust (Mounce's *Basics of Biblical Greek* frequency list, the
STEP Bible TAGNT data, or the open **MorphGNT** / SBLGNT datasets).

---

## Requirements

- Python 3.10+ (3.12 recommended — what this was tested on)
- `pip` to install two packages (Flask, and gunicorn for production)

Everything else (SQLite, the web UI) is included. The UI pulls three fonts from
Google Fonts when online; if your server has no internet access the app still
works and falls back to system serif/sans fonts.

---

## Quick start (try it in 30 seconds)

```bash
cd greek-flashcards
.venv/bin/pip install -r requirements.txt          # add --break-system-packages on Debian/Ubuntu if pip complains
python3 app.py                           # dev server on http://0.0.0.0:8080
```

Open `http://<server-ip>:8080`, register a username, and start studying. The
database (`koine.db`) and a `secret_key` file are created automatically in the
project folder on first run.

> `python3 app.py` uses Flask's built-in **development** server — fine for
> trying it out or single-user use on your LAN. For anything you leave running,
> use gunicorn as below.

---

## Deploying on Proxmox

Below is a clean setup inside a **Debian 12 LXC container** (a VM is identical
from the command line). Adjust the user/paths to taste.

### 1. Create the container

In the Proxmox UI, create an LXC from the Debian 12 template (512 MB RAM and 4 GB
disk is plenty). Start it and open a shell / SSH in.

### 2. Install dependencies

```bash
apt update && apt install -y python3 python3-pip python3-venv
```

### 3. Copy the app in and create a service user

```bash
useradd --system --create-home --home-dir /opt/greek-flashcards greek
# copy the project files into /opt/greek-flashcards (scp, git, or the Proxmox file push)
chown -R greek:greek /opt/greek-flashcards
cd /opt/greek-flashcards
.venv/bin/pip install -r requirements.txt 
```

### 4. Run it with gunicorn

The included `run.sh` initialises the database and launches gunicorn:

```bash
./run.sh                 # 0.0.0.0:8080
PORT=9000 ./run.sh       # or pick a port
```

### 5. Keep it running with systemd

An example unit ships as `greekflashcards.service`. Edit the paths/user if you
didn't use `/opt/greek-flashcards` + the `greek` user, then:

```bash
cp greekflashcards.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now greekflashcards
systemctl status greekflashcards          # check it's running
```

The app is now on `http://<container-ip>:8080` and restarts on boot / on crash.

### 6. (Optional) Put it behind nginx with a hostname

If you want a nice URL and/or TLS, run nginx (on the host or another container)
as a reverse proxy:

```nginx
server {
    listen 80;
    server_name greek.yourdomain.lan;

    location / {
        proxy_pass         http://127.0.0.1:8080;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
    }
}
```

Add TLS with your own certificate or Let's Encrypt (e.g. `certbot`) as usual.

---

## Configuration

Set these as environment variables (or in the systemd unit's `Environment=`
lines):

| Variable   | Default            | Purpose                                        |
|------------|--------------------|------------------------------------------------|
| `KOINE_DB` | `./koine.db`       | Path to the SQLite database file.              |
| `PORT`     | `8080`             | Port to listen on.                             |
| `WORKERS`  | `3`                | gunicorn worker processes (used by `run.sh`).  |

**Backups** are trivial: stop the service (or just copy while idle) and save the
single `koine.db` file. That one file holds all users, decks, and progress.

---

## Extending to the full 500

Use `import_csv.py` to add banks 4 and 5 (words 301–500) — or any custom deck.
The importer writes into the **same** `koine.db` the app uses.

1. Build a CSV with a header row. Columns: `front,back,hint,extra`
   (`front` and `back` required; `hint` and `extra` optional). A starter file,
   `banks-4-5-template.csv`, is included.

   ```csv
   front,back,hint,extra
   πλοῖον,"boat, ship",ploion,noun · rank 312
   σπείρω,"I sow",speirō,verb · rank 313
   ```

   Get the word list from an authoritative source and copy the lemmas
   **with their accents** — e.g. Mounce's frequency list, STEP Bible's TAGNT,
   or the open MorphGNT/SBLGNT data. This is the step where verification
   matters; the tool is only as trustworthy as the list you feed it.

2. Import (from the project folder, with the same `KOINE_DB` if you set one):

   ```bash
   python3 import_csv.py banks-4-5-template.csv \
       --slug freq-4 --name "Bank 4 · 301–400" \
       --group "Frequency banks" \
       --subtitle "the most common words in the NT"
   ```

   Handy flags: `--dry-run` (parse and report, write nothing), `--replace`
   (clear the deck's existing cards before importing, for a clean re-import).
   Re-running without `--replace` **appends**.

3. Reload the menu in the browser. New decks appear live from the database — a
   restart isn't strictly required, though it doesn't hurt.

You can use the exact same process to make your own decks (irregular verbs,
a chapter's vocab, principal parts, etc.) — just choose a new `--slug`.

---

## Project layout

```
greek-flashcards/
├── app.py                     Flask app: schema, auth, API, spaced repetition
├── seed.py                    all built-in card content (edit/verify freely)
├── import_csv.py              add banks 4–5 or custom decks from a CSV
├── banks-4-5-template.csv     starter CSV showing the expected format
├── requirements.txt           Flask + gunicorn
├── run.sh                     init DB + launch gunicorn
├── greekflashcards.service    example systemd unit
├── templates/
│   └── index.html             single-page UI (auth + study shell)
└── static/
    ├── style.css              styling
    └── app.js                 client logic (menu, sessions, grading)
```

## HTTP API (for the curious / for scripting)

All under `/api`, JSON in and out, session-cookie auth:

- `POST /api/register` `{username, password}` — create an account & sign in
- `POST /api/login` `{username, password}` — sign in
- `POST /api/logout` — sign out
- `GET  /api/me` — current user (or `null`)
- `GET  /api/decks` — all decks, grouped, with per-user due/learned counts
- `GET  /api/deck/<slug>/session?limit=24` — a study session of due cards
  (add `?mode=all` to draw from the whole deck regardless of due date)
- `POST /api/review` `{card_id, grade}` — grade a card (`again` | `good` | `easy`)
- `POST /api/deck/<slug>/reset` — reset your progress for one deck
- `GET  /health` — liveness check

---

Built to be simple, correct, and yours to modify. Χάρις ὑμῖν.
