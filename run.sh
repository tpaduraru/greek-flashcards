#!/usr/bin/env bash
# Start the NT Greek Flashcards app with the gunicorn production server.
# Usage:  ./run.sh          (listens on 0.0.0.0:8080)
#         PORT=9000 ./run.sh
set -euo pipefail
cd "$(dirname "$0")"

export KOINE_DB="${KOINE_DB:-$(pwd)/koine.db}"
PORT="${PORT:-8080}"
WORKERS="${WORKERS:-3}"

# initialise the database + schema on first run
.venv/bin/python3 -c "import app; app.init_db(); print('DB ready at', app.DB_PATH)"

exec .venv/bin/gunicorn --workers "$WORKERS" --bind "0.0.0.0:${PORT}" app:app
