#!/bin/sh
set -e

export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-config.settings}"

# Ensure SQLite directory exists and is writable
DATA_DIR="$(dirname "${SQLITE_PATH:-/data/db.sqlite3}")"
mkdir -p "$DATA_DIR"
touch "$DATA_DIR/.write_test" && rm -f "$DATA_DIR/.write_test"

python manage.py migrate --noinput

exec gunicorn config.wsgi:application \
  --bind "0.0.0.0:${PORT:-8889}" \
  --workers "${WEB_CONCURRENCY:-2}" \
  --timeout 120 \
  --access-logfile - \
  --error-logfile - \
  --capture-output
