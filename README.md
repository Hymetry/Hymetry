# Docker (local / cloud-like) guide

This repo provides two Docker Compose setups:

- **`docker-compose.yml`**: Postgres **in Docker** (`db` container).
- **`docker-compose.host-db.yml`**: Postgres **on your host** (containers connect to `host.docker.internal`).

## Prerequisites

- Docker Desktop (Windows/macOS) or Docker Engine (Linux)

## Environment variables: one `.env` for both Compose + containers

There are *two* “env file” concepts:

- **Compose-time** (`docker compose --env-file ...`): used for `${VAR}` interpolation while parsing `docker-compose*.yml`.
- **Container runtime** (`env_file:` in the YAML): injects variables into the container environment (what Django/Celery read).

### Recommended setup (single source of truth)

Create a local `.env` (do not commit secrets):

   - Copy `.env.docker.example` → `.env`
   - Edit values as needed

After that, **`.env`** is used for:

- YAML `${...}` interpolation (via `--env-file .env` or Compose default loading of `.env`)
- Container runtime env (via `env_file: ./.env`)



## Run (Postgres in Docker)

Uses `docker-compose.yml` and starts: `db`, `redis`, `web` (gunicorn), `celery`, `celery-beat`, `caddy`.

```bash
docker compose --env-file .env -f docker-compose.yml up --build
```

- **App**: `http://localhost` (Caddy on port 80)
- **Direct gunicorn** (bypassing Caddy): `http://localhost:8000`

## Deploy on another domain (using `docker-compose.yml`)

To run this same Docker setup on a real domain, you typically only change **`.env`** values (no code changes).

### Domain / URLs

- **`CADDY_HOST`**: set to your domain so Caddy can serve that host (and obtain HTTPS certs when applicable).
  - Example: `CADDY_HOST=example.com`
- **`ALLOWED_HOSTS`**: include your domain(s), comma-separated.
  - Example: `ALLOWED_HOSTS=example.com,www.example.com`
- **URLs**: set to your `https://...` domain as appropriate for your deployment:
  - `SITE_URL=https://example.com`
  - `APP_URL=https://example.com`
  - `EDGE_URL=https://example.com` (or whatever you intend)
  - `API_URL=https://example.com`

Also ensure:

- **`DEBUG=False`**
- **`SECRET_KEY`** is a strong secret (not `change-me`)

### Ports / firewall

`docker-compose.yml` publishes Caddy on:

- **80/tcp** (HTTP)
- **443/tcp** (HTTPS)

For a domain deployment, your DNS must point the domain to the server, and inbound **80/443** must be allowed to reach that Docker host.

## Run (Postgres on the host)

1. Ensure Postgres is running on your machine and accessible on `DB_PORT` (default `5432`).
2. Set DB variables in `.env` (example):
   - `POSTGRES_HOST=host.docker.internal`
   - `POSTGRES_PORT=5432`
   - `POSTGRES_DB=...`
   - `POSTGRES_USER=...`
   - `POSTGRES_PASSWORD=...`

Then:

```bash
docker compose --env-file .env -f docker-compose.dev-host-db.yml up --build
```

Notes:

- `host.docker.internal` is built-in on Docker Desktop (Windows/macOS). On Linux you may need a different host gateway config.

## Migrations / collectstatic behavior

The image entrypoint (`docker/entrypoint.sh`) does the following by default:

- waits for Postgres (unless `SKIP_DB_WAIT=1`)
- runs migrations (`RUN_MIGRATIONS=1`)
- runs `collectstatic` (`RUN_COLLECTSTATIC=1`)

In Compose, `celery` and `celery-beat` set `RUN_MIGRATIONS=0` and `RUN_COLLECTSTATIC=0` so only the `web` service performs those steps by default.

## Fixtures (optional)

The entrypoint can optionally load a **Celery Beat** fixture:

- **Enable**: set `LOAD_CELERY_BEAT_FIXTURE=1`
- **Path**: `CELERY_BEAT_FIXTURE_PATH` (default `/app/fixtures/celery_beat.json`)

Behavior:

- only runs if `django_celery_beat` is available
- only loads the fixture if there are **no existing** `PeriodicTask` rows (to avoid duplicating schedules)

## Initialize the database (create Django superuser)

After the stack is up and migrations have run, create an admin user:

```bash
# Postgres-in-Docker setup
docker compose -f docker-compose.yml exec web python manage.py createsuperuser
```

```bash
# Host-Postgres setup
docker compose -f docker-compose.dev-host-db.yml exec web python manage.py createsuperuser
```

## Common commands

```bash
# Stop containers (keeps volumes)
docker compose -f docker-compose.yml down

# Stop + delete volumes (destroys Postgres/Redis data for the in-Docker setup)
docker compose -f docker-compose.yml down -v

# Run a one-off Django command
docker compose -f docker-compose.yml exec web python manage.py createsuperuser
```

