# Multi-tenant Chatbot Platform

A multi-tenant retrieval-augmented chatbot. Tenants own their content, branding,
moderation policy, and embedded widget; visitors talk to a tenant-scoped
assistant backed by per-tenant Qdrant collections, OpenAI for embeddings and
chat completion, and an admin dashboard for everything in between.

## What is in this repo

- **Backend** ([`backend/`](./backend/)) - FastAPI app (`app:app` from
  [`backend/app.py`](./backend/app.py)), SQLAlchemy + Alembic against
  Postgres, Qdrant for vectors, OpenAI for embeddings and chat completion,
  Playwright + requests for content scraping, APScheduler for weekly
  reindex.
- **Frontend** ([`frontend/`](./frontend/)) - React 18 (CRA) admin
  dashboard, embedded chat widget, and a vanilla `widget.js` loader.
- **Compose stack** ([`docker-compose.yml`](./docker-compose.yml)) -
  Postgres + Qdrant + backend + frontend.

## Quick start (Docker Compose)

```bash
git clone <repo-url>
cd migraine-chatbot

cp .env.example .env
$EDITOR .env  # set OPENAI_API_KEY, JWT_SECRET, WIDGET_EMBED_KEYS_JSON, etc.

docker compose build
docker compose up -d

docker compose ps
docker compose logs -f backend
```

Default endpoints (override in `.env`):

- Frontend: `http://localhost:${FRONTEND_PORT:-3043}`
- Backend API: `http://localhost:${BACKEND_PORT:-8043}` (Swagger at `/docs`)
- Qdrant HTTP: `http://localhost:${QDRANT_HTTP_PORT:-6043}`

For everything else - bootstrapping a superadmin, applying migrations,
adding tenants, configuring widget keys, enabling country blocking,
running reindex - see the docs.

**Note:** The [`docs/`](./docs/) folder is listed in [`.gitignore`](./.gitignore) and is
**not committed to git**. Keep runbooks and architecture notes there locally; feature
branches should only commit application code, tests, and migrations.

## License / attribution

Tenant deployments using DB-IP IP-to-Country Lite for GeoIP must observe
the DB-IP CC BY 4.0 attribution where geolocation is shown to end users
(see [`backend/scripts/download_dbip_country_lite.py`](./backend/scripts/download_dbip_country_lite.py)).
Other dependencies follow their respective licenses; see
[`requirements.txt`](./requirements.txt) and
[`frontend/package.json`](./frontend/package.json).
