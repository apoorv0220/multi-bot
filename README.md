# Multi-tenant Chatbot Platform

A multi-tenant retrieval-augmented chatbot. Tenants own their content, branding,
moderation policy, and embedded widget; visitors talk to a tenant-scoped
assistant backed by per-tenant Qdrant collections, OpenAI for embeddings and
chat completion, and an admin dashboard for everything in between.

> **Documentation entry point:** [`docs/README.md`](./docs/README.md). Anything
> beyond this quick-start belongs there.

## What is in this repo

- **Backend** ([`backend/`](./backend/)) - FastAPI app (`app:app` from
  [`backend/app.py`](./backend/app.py)), SQLAlchemy + Alembic against
  Postgres, Qdrant for vectors, OpenAI for embeddings and chat completion,
  Playwright + requests for content scraping, APScheduler for weekly
  reindex.
- **Frontend** ([`frontend/`](./frontend/)) - React 18 (CRA) admin
  dashboard, embedded chat widget, and a vanilla `widget.js` loader.
- **Docs** ([`docs/`](./docs/)) - architecture, schema, API,
  multi-tenancy, deployment, and operations references.
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

## Where to look next

| You want to... | Read |
| --- | --- |
| Understand how the system fits together | [`docs/architecture.md`](./docs/architecture.md) |
| Understand tenant isolation | [`docs/multi-tenancy.md`](./docs/multi-tenancy.md) |
| Wire a new integration / endpoint | [`docs/api-reference.md`](./docs/api-reference.md) |
| Work on the backend code | [`docs/backend-module-map.md`](./docs/backend-module-map.md) |
| Work on the frontend / embed widget | [`docs/frontend-module-map.md`](./docs/frontend-module-map.md) |
| Operate the platform | [`docs/deployment.md`](./docs/deployment.md), [`docs/background-jobs.md`](./docs/background-jobs.md) |
| Configure environment | [`docs/environment-variables.md`](./docs/environment-variables.md) |
| Run locally without Docker | [`docs/local-development.md`](./docs/local-development.md) |
| Understand the database | [`docs/database-schema.md`](./docs/database-schema.md) |
| Understand reindex / embeddings | [`docs/embedding-pipeline.md`](./docs/embedding-pipeline.md) |
| Test IP / country blocks | [`docs/testing-ip-country-blocks.md`](./docs/testing-ip-country-blocks.md) |
| Embed the chat on a tenant site | [`docs/widget-auth-architecture.md`](./docs/widget-auth-architecture.md), [`docs/frontend-module-map.md`](./docs/frontend-module-map.md) |

The full index, with an audience matrix, is in
[`docs/README.md`](./docs/README.md).

## License / attribution

Tenant deployments using DB-IP IP-to-Country Lite for GeoIP must observe
the DB-IP CC BY 4.0 attribution where geolocation is shown to end users
(see [`backend/scripts/download_dbip_country_lite.py`](./backend/scripts/download_dbip_country_lite.py)).
Other dependencies follow their respective licenses; see
[`requirements.txt`](./requirements.txt) and
[`frontend/package.json`](./frontend/package.json).
