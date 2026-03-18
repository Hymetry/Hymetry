# Hymetry OSS - Deployment

## Deploy on Heroku

Deploy Hymetry OSS to Heroku in one click:

[![Deploy](https://www.herokucdn.com/deploy/button.svg)](https://heroku.com/deploy?template=https://github.com/Hymetry/Hymetry)

### Quick Start

1. Click the **Deploy to Heroku** button.
2. Create your Heroku app.
3. Wait for build and release to finish.

### Included Add-ons

- Heroku Postgres
- Heroku Redis

## Deploy on Render

Deploy Hymetry OSS to Render in one click using the included `render.yaml` blueprint:

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/hymetry/hymetry)

### Quick Start

1. Click the **Deploy to Render** button.
2. Review the generated services (web, worker, Postgres, Redis).
3. Optionally set `HYMETRY_DOMAIN` and `EDGE_URL` to your Render app URL (or custom domain).
4. Create the blueprint and wait for all services to become healthy.

## Self-hosted or cloud (Docker Compose)

Use `docker-compose.yml` to run the full stack (web, Celery worker+beat in one container, Postgres, Redis, and Caddy) on your own server or cloud VM.

### Quick Start

1. Create your env file:
  - Copy `.env.example` to `.env` and fill in required values.
  - Set `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`.
  - Set `DATABASE_URL` in `.env` to the same credentials (required), e.g. `postgresql://postgres:pwd@db:5432/hymetry_oss_db`.
2. Build and start services:
  - `docker compose up -d --build`
3. Check service status:
  - `docker compose ps`
4. Open the app:
  - `http://localhost` (via Caddy) or `http://localhost:8000` (web directly).

### Notes

- Data is persisted with Docker volumes (`postgres_data`, `redis_data`, `staticfiles`, `media`).
- The `init` service runs bootstrap tasks before app services start.
- Default Postgres host mapping is `127.0.0.1:5433`.
- Django app uses `DATABASE_URL`; Postgres container initialization uses `POSTGRES_*` from `.env`.

