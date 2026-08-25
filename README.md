<h1 align="center">Hymetry — account-level product analytics for B2B SaaS</h1>

<p align="center">
  Hymetry connects product usage to the companies and people behind it—so you can see what customers adopt,
  where engagement changes, who may need attention, and, when available, what happened during a recorded visit.
</p>

<p align="center">
  <strong>Open source</strong> · <strong>Self-hosted</strong> · <strong>AGPL-3.0-or-later</strong>
</p>

<p align="center">
  <a href="https://app.hymetry.com/projects/demo/"><strong>Explore the live demo →</strong></a>
  · <a href="https://www.hymetry.com/">Learn more at hymetry.com</a>
  · <a href="https://www.hymetry.com/resources/">Guides</a>
  · <a href="#self-host-hymetry">Install</a>
</p>

## What problem does Hymetry solve?

B2B product usage is account-shaped. One customer can contain many users, roles, workflows, and levels of adoption. A healthy-looking event total can still hide an account that:

- depends on one power user;
- adopted only a small part of the product;
- lost engagement after a release;
- or repeatedly gets stuck in the same workflow.

Event dashboards show activity. Replay tools show individual sessions. Customer-facing teams still have to connect those pieces to the right company and user before they can act.

Hymetry keeps that context together. It organizes browser behavior around **product areas and pages**, **companies**, **identified users**, and **visits**—so a team can move from a usage signal to the people, pages, visits, and available replay evidence behind it.

<a href="https://www.hymetry.com/resources/b2b-product-analytics/">
  <img
    src="https://www.hymetry.com/resources/b2b-product-analytics/assets/signal-to-evidence-workflow.svg"
    alt="Workflow from a product signal to the affected account, contributing users, relevant visits, and team action"
  >
</a>

<p align="center">
  <em>Start with a product signal, then open the account, users, and visits that explain it.</em>
</p>

## What can you answer?

| View | What it helps answer |
| --- | --- |
| **Companies** | Which accounts are active? Is adoption broad or concentrated? Which accounts show risk or opportunity signals worth investigating? |
| **Pages** | Which product areas and workflows are being adopted? How are usage, engagement, and flows changing? |
| **Users** | Who is participating inside each account? Who is gaining or losing momentum? |
| **Visits** | What happened in the recorded sessions behind a company, user, page, or product-area signal, when a replay is available? |

Hymetry's attention, risk, and opportunity signals are transparent usage heuristics—not churn or expansion predictions.

> [!IMPORTANT]
> Screen recording is optional. Password fields receive the recorder's default masking, but other inputs and DOM text are not blanket-masked. Configure and test masking before enabling recording in production; see the [session replay privacy checklist](https://www.hymetry.com/resources/session-replay-privacy-checklist/).

## See the product in practice

### See account-level adoption and attention signals

<a href="https://www.hymetry.com/product/companies/">
  <img
    src="https://www.hymetry.com/product/companies/companies-overview.png"
    alt="Companies overview with account activity, adoption breadth, health distribution, and company-level usage"
  >
</a>

<p align="center">
  <em>Synthetic demo data: understand the portfolio before drilling into a customer.</em>
</p>

### Understand adoption across product areas

<a href="https://www.hymetry.com/product/pages/">
  <img
    src="https://www.hymetry.com/product/pages/pages-overview.png"
    alt="Pages overview with usage metrics and product-area adoption"
  >
</a>

<p align="center">
  <em>Synthetic demo data: compare how customers use stable pages and product areas.</em>
</p>

### Open the session evidence behind a signal

<a href="https://www.hymetry.com/product/visits/">
  <img
    src="https://www.hymetry.com/product/visits/visits-overview.png"
    alt="Visits overview with session rows and product-area activity timelines"
  >
</a>

<p align="center">
  <em>Synthetic demo data: filter visits by account context, then open available replays.</em>
</p>

## How it works

1. **Collect** — add the generated browser tracker and choose analytics only or analytics with screen recording.
2. **Identify** — send stable user and company IDs from your application's authenticated context.
3. **Structure** — group normalized URLs into named pages and product areas using page-naming rules; optional AI-assisted naming can generate and refresh those rules.
4. **Investigate** — compare periods, apply reusable filters and segments, and move from Pages, Companies, or Users to relevant Visits and, when available, replays.

Hymetry does not guess customer identity. Your integration supplies the user and company IDs that make account-level analytics reliable.

## Evaluate before you deploy

Hymetry is designed for product, UX, customer success, account, founder, and engineering teams working on B2B web products. The [hosted demo project](https://app.hymetry.com/projects/demo/) lets you explore Pages, Companies, Users, Visits, and replay using synthetic data. It opens on the hosted Hymetry domain; demo data is not installed into your OSS database.

For a deeper explanation of the model, read the [B2B product analytics guide](https://www.hymetry.com/resources/b2b-product-analytics/) or browse the [Hymetry resource library](https://www.hymetry.com/resources/).

## Self-host Hymetry

Hymetry can run with Docker Compose or deploy from the included Render blueprint. The application uses Django, PostgreSQL, Redis, Celery, and Gunicorn; the Compose deployment adds Caddy.

<details>
<summary><strong>Docker Compose quick start</strong> — local evaluation</summary>

### Prerequisites

- Git
- Docker Engine or Docker Desktop with Docker Compose

### Install

1. Clone the repository:

   ~~~console
   git clone https://github.com/Hymetry/Hymetry.git
   cd Hymetry
   ~~~

2. Copy the example configuration:

   ~~~console
   cp .env.example .env
   ~~~

   On PowerShell, use `Copy-Item .env.example .env`.

3. Generate a secret:

   ~~~console
   docker run --rm python:3.12-alpine python -c "import secrets; print(secrets.token_urlsafe(64))"
   ~~~

   In `.env`, replace `SECRET_KEY` with the generated value. Keep it stable: it protects sessions and the encryption material for workspace OpenAI credentials.

4. Start the stack:

   ~~~console
   docker compose up -d --build
   ~~~

5. Open [http://localhost/account/setup/admin/](http://localhost/account/setup/admin/) and create the first administrator.

The setup endpoint is sealed after the first administrator is created. Docker volumes persist PostgreSQL, Redis, static files, and media. The `init` service applies migrations, seeds initial configuration once, and creates idempotent Celery schedules.

> The example environment is intended for local evaluation. Before exposing Hymetry to the internet, rotate `POSTGRES_PASSWORD` and update `DATABASE_URL`, configure the public host and HTTPS settings, and establish backups plus appropriate request-size and rate controls.

### Connect your product

1. Create the first workspace and a project.
2. In **Project settings**, choose **Analytics** or **Analytics and screen recording**.
3. Copy the generated identity block and tracker tag into your product.
4. Replace the example IDs and traits with values from the current authenticated user and customer account.
5. Use the product, then confirm that analytics, identity, and optional recording data arrive in Project settings.

</details>

<details>
<summary><strong>Deploy on Render</strong></summary>

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/Hymetry/Hymetry)

Render deploys the included `render.yaml` blueprint and generates `SECRET_KEY`. After the first deployment, open `/account/setup/admin/` on the generated service URL and create the administrator.

`HYMETRY_DOMAIN` and `EDGE_URL` are optional. When absent, Hymetry learns the public URL from the request.

</details>

<details>
<summary><strong>Local access model and administrator recovery</strong></summary>

- The first administrator is created only after installation.
- There is no public signup, email delivery, invitation email, or email password-reset flow.
- A superuser can create the first workspace.
- Any active workspace owner can create additional workspaces; admins, members, and viewers cannot.
- Workspace owners and admins add local users directly; only owners may assign the Owner role.
- Commercial plans, trials, billing states, and workspace status badges are not part of OSS.

To change a local administrator password from the Docker deployment:

~~~console
docker compose exec web python manage.py changepassword admin@example.com
~~~

</details>

<details>
<summary><strong>Workspace OpenAI key (optional BYOK)</strong></summary>

OpenAI BYOK is configured once per workspace in **Workspace settings** and is shared by projects in that workspace. Only owners and superusers can save, validate, replace, or remove it.

The key is encrypted at rest. By default, its encryption material is derived from the persistent `SECRET_KEY`. For explicit rotation, set `OPENAI_KEY_ENCRYPTION_KEYS` to a comma-separated list of Fernet keys, with the current key first and older decryption keys after it. There is no global `OPENAI_API_KEY` fallback.

Without a valid workspace key, AI page naming is skipped. Ingestion, analytics, recording, and manual page rules continue to work.

</details>

<details>
<summary><strong>Configuration and capture notes</strong></summary>

Important environment variables are documented in [`.env.example`](./.env.example):

- `DATABASE_URL`, `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`
- `DJANGO_CACHE_URL` and `DJANGO_CACHE_KEY_PREFIX` for the shared analytics cache
- `HYMETRY_DOMAIN` and `EDGE_URL` for explicit public URLs
- `HOSTED_DEMO_URL` for the external demo link
- `SECRET_KEY` and optional `OPENAI_KEY_ENCRYPTION_KEYS` for persistent encryption
- `REPLAY_STREAM_*` settings for bounded replay bootstrap, chunking, prefetch, and append batches

Tracking URLs keep the host and path but discard query parameters and fragments before storage. Localhost, IP addresses, and internal single-label hosts are supported for self-hosted projects.

Screen recording can capture sensitive DOM content. Password fields receive rrweb's default masking, but other inputs and DOM text are not blanket-masked. Server-side masking rules are not seeded by default; configure them in Django admin and test representative recordings before production use.

</details>

<details>
<summary><strong>Database upgrades</strong></summary>

New installations run the complete migration chain automatically.

Incremental upgrade migrations support an existing OSS database whose application version is exactly commit [`da90b398`](https://github.com/Hymetry/Hymetry/commit/da90b398e6ed0069b1835d08314f7ac46c6ca8d8).

Before upgrading:

1. Back up PostgreSQL.
2. Keep the existing `SECRET_KEY` and any `OPENAI_KEY_ENCRYPTION_KEYS` unchanged.
3. Update the application.

For Docker Compose, rebuilding and restarting the stack runs migrations and bootstrap through the `init` service. For non-Docker deployments, run these commands in the configured application environment:

~~~console
python manage.py migrate
python manage.py bootstrap
~~~

Databases from other historical OSS revisions do not have a verified direct upgrade path; migrate them to the supported baseline first or start with a new database.

</details>

## Support and license

The self-hosted edition is community-supported.

Hymetry is licensed under the [GNU Affero General Public License v3 or later](./LICENSE). See the [Hymetry OSS Terms](<AGPL terms.md>) for additional operator, privacy, third-party notice, and trademark terms.
