# Hymetry OSS - Deploy to Heroku

Deploy Hymetry OSS to Heroku in one click:

[![Deploy](https://www.herokucdn.com/deploy/button.svg)](https://heroku.com/deploy?template=https://github.com/Hymetry/Hymetry)

## Quick Start

1. Click the **Deploy to Heroku** button.
2. Create/select your Heroku app.
3. Wait for build and release to finish.

## After Deploy

- Open your Heroku app dashboard.
- In Heroku Dashboard, open **Settings** -> **Config Vars**.
- Ensure `SITE_URL` is set exactly like:
  `https://<app-name>.herokuapp.com`
- optionally set APP_URL for asset proxy and EDGE_URL for third-party scripts hosting 

## Included Add-ons

- Heroku Postgres
- Heroku Redis

## Notes

- `DEBUG` should remain `False` in production.
- `TERMS_ACCEPTED` must be `true`.
