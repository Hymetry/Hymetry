# Hymetry

[Hymetry](https://www.hymetry.com/) is session recording software for SaaS apps.

It helps you capture sessions, replay user interactions, and understand how people use your product.

## Deployment options

Choose the setup that fits your needs:

- **Render** — recommended managed deployment
- **Heroku** — simple if you already use Heroku
- **Docker Compose** — self-hosted deployment on your own server or cloud VM

---

## Render (recommended)

Deploy Hymetry to Render in one click:

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/hymetry/hymetry)

### Quick start

1. Click the **Deploy to Render** button.
2. Create the blueprint and wait for all services to become healthy.
3. Open the **hymetry-web** service:

<img width="454" height="172" alt="Render services list with hymetry-web highlighted" src="https://github.com/user-attachments/assets/9cc2b769-a056-495c-b044-56e3fc7d8f3e" />

4. Open the URL of your newly created Hymetry instance:

<img width="510" height="236" alt="Render web service page showing the generated Hymetry URL" src="https://github.com/user-attachments/assets/7c08ff35-1147-4628-8dfd-9269987ae9e7" />

5. Set the admin password.

<details>
<summary>Optional Render settings</summary>

Optionally set `HYMETRY_DOMAIN` and `EDGE_URL` to your Render app URL or custom domain.

Example:

```env
HYMETRY_DOMAIN=https://example.com
EDGE_URL=https://edge.example.com
```

</details>

---

## Heroku

Deploy Hymetry to Heroku in one click:

[![Deploy](https://www.herokucdn.com/deploy/button.svg)](https://heroku.com/deploy?template=https://github.com/Hymetry/Hymetry)

### Quick start

1. Click the **Deploy to Heroku** button.
2. Create your Heroku app.
3. Wait for build and release to finish.

<details>
<summary>Included add-ons</summary>

- Heroku Postgres
- Heroku Redis

</details>

<details>
<summary>Optional Heroku settings</summary>

Optionally set `HYMETRY_DOMAIN` and `EDGE_URL` to your app URL or custom domain.

Example:

```env
HYMETRY_DOMAIN=https://example.com
EDGE_URL=https://edge.example.com
```

</details>

---

## Self-hosted with Docker Compose

Use `docker-compose.yml` to run the full stack on your own server or cloud VM:

- web
- Celery worker + beat in one container
- Postgres
- Redis
- Caddy

### Quick start

1. Create your env file.
   - Copy `.env.example` to `.env` and edit it if needed.
2. Build and start services.
   - `docker compose up -d --build`
3. Check service status.
   - `docker compose ps`
4. Open the app.
   - `http://localhost`

<details>
<summary>Docker Compose notes</summary>

- Data is persisted with Docker volumes: `postgres_data`, `redis_data`, `staticfiles`, `media`
- The `init` service runs bootstrap tasks before app services start.
- Default Postgres host mapping is `127.0.0.1:5433`.
- Django uses `DATABASE_URL`; Postgres container initialization uses `POSTGRES_*` from `.env`.

</details>
