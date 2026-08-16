#!/bin/sh
set -e

export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-config.settings}"

# SQLite local volume only when not using PostgreSQL
DB_ENGINE="$(echo "${DB_ENGINE:-}" | tr '[:upper:]' '[:lower:]')"
case "$DB_ENGINE" in
  postgresql|postgres|django.db.backends.postgresql)
    ;;
  *)
    DATA_DIR="$(dirname "${SQLITE_PATH:-/data/db.sqlite3}")"
    mkdir -p "$DATA_DIR"
    touch "$DATA_DIR/.write_test" && rm -f "$DATA_DIR/.write_test"
    ;;
esac

python manage.py migrate --noinput

exec gunicorn config.wsgi:application \
  --bind "0.0.0.0:${PORT:-8889}" \
  --workers "${WEB_CONCURRENCY:-2}" \
  --timeout 120 \
  --access-logfile - \
  --error-logfile - \
  --capture-output
