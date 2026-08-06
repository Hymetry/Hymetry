# Hymetry OSS

Hymetry is a self-hosted product analytics and session replay application. The OSS edition includes Pages, Companies, Users, Visits, streamed session replay, company attributes and segments, persistent analytics filters, page-structure naming with AI, and screen recording.

The hosted demo remains available from **All projects** and opens on the hosted Hymetry domain in a new tab. Demo data is not installed into the OSS database.

## Deployment options

- **Docker Compose** — self-host on a server or local machine.
- **Render** — managed deployment from `render.yaml`.

## Docker Compose quick start

1. Copy `.env.example` to `.env`.
2. Replace `SECRET_KEY` with a long random value and keep it stable: it protects sessions and encrypts workspace OpenAI credentials.
3. Start the stack:

   ```console
   docker compose up -d --build
   ```

4. Open `http://localhost/account/setup/admin/`.
5. Enter an administrator email and a strong password.

The setup endpoint is sealed after the first administrator is created. Hymetry has no public signup, email delivery, or email password-reset flow. If an administrator loses access, use Django's local command from the application container:

```console
python manage.py changepassword admin@example.com
```

Data is persisted in Docker volumes for PostgreSQL, Redis, static files, and media. The `init` service applies database migrations, seeds initial configuration once, and creates idempotent Celery schedules.

## Render

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/hymetry/hymetry)

Render generates `SECRET_KEY`. After the first deploy, open `/account/setup/admin/` on the generated service URL and create the administrator. `HYMETRY_DOMAIN` and `EDGE_URL` are optional; when absent, Hymetry learns the public URL from the request.

## OSS access model

- The first administrator is created only after installation.
- There is no self-service signup.
- A superuser can create the first workspace.
- Any active workspace owner can create additional workspaces; admins, members, and viewers cannot.
- Workspace owners add local users directly and may assign multiple owners. No invitation email is sent.
- Project statuses are retained. Commercial workspace plans, trials, billing states, and workspace status badges are not part of OSS.

## Workspace OpenAI key (BYOK)

OpenAI BYOK is configured once per workspace in **Workspace settings** and is shared by projects in that workspace. Only owners and superusers can save, validate, replace, or remove it.

The key is encrypted at rest. By default the encryption material is derived from the persistent `SECRET_KEY`. For explicit rotation, set `OPENAI_KEY_ENCRYPTION_KEYS` to a comma-separated list of Fernet keys with the current key first and older decryption keys after it. There is no global `OPENAI_API_KEY` fallback.

Without a valid workspace key, AI page naming is skipped; ingestion, analytics, recording, and manual page rules continue to work.

## Configuration

Important environment variables are documented in `.env.example`:

- `DATABASE_URL`, `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`
- `DJANGO_CACHE_URL` and `DJANGO_CACHE_KEY_PREFIX` for the shared analytics cache
- `HYMETRY_DOMAIN` and `EDGE_URL` for explicit public URLs
- `HOSTED_DEMO_URL` for the external demo link
- `SECRET_KEY` and optional `OPENAI_KEY_ENCRYPTION_KEYS` for persistent encryption
- `REPLAY_STREAM_*` settings for bounded replay bootstrap, chunking, prefetch, and append batches

Tracking URLs keep host and path but discard query parameters and fragments before storage. Localhost, IP addresses, and internal single-label hosts are supported for self-hosted projects.

## Database upgrades

New installations run the complete migration chain automatically. Incremental upgrade migrations support an existing OSS database whose application version is exactly commit `da90b398e6ed0069b1835d08314f7ac46c6ca8d8`.

Before upgrading, back up the PostgreSQL database and keep the existing `SECRET_KEY` and any `OPENAI_KEY_ENCRYPTION_KEYS` unchanged. After updating the application, run:

```console
python manage.py migrate
python manage.py bootstrap
```

The Docker Compose `init` service performs these commands during startup. Databases from other historical OSS revisions do not have a verified direct upgrade path; migrate them to the supported baseline first or start with a new database.

## Support and license

The self-hosted edition is community-supported. The software is licensed under GNU AGPLv3 or later; see `AGPL terms.md` and `LICENSE`.
