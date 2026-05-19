#!/bin/sh
set -e

echo "Waiting for database..."
python - <<'PY'
import os
import time
from sqlalchemy import create_engine, text

url = os.getenv("DATABASE_URL")
if not url:
    raise SystemExit("DATABASE_URL is not set")
engine = create_engine(url, future=True)
for _ in range(60):
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            print("Database ready")
            break
    except Exception:
        time.sleep(2)
else:
    raise SystemExit("Database unavailable")
PY

# Apply migrations by default so ORM columns (e.g. chat_sessions context) stay in sync with code.
# Set SKIP_DB_MIGRATIONS=1 to skip (e.g. external migration control).
if [ "${SKIP_DB_MIGRATIONS:-0}" != "1" ]; then
  alembic upgrade head
fi
alembic current || true

exec gunicorn -w 2 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:${API_PORT:-8043} --timeout 3600 --graceful-timeout 300 app:app
