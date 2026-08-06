FROM node:20-bookworm-slim AS frontend-builder

WORKDIR /app

COPY . /app

RUN mkdir -p /app/static/css \
    && npm --prefix /app/frontend/tailwind ci \
    && npm --prefix /app/frontend/tailwind test \
    && npm --prefix /app/frontend/tracker_script ci \
    && npm --prefix /app/frontend/tracker_script test


FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

ENV DJANGO_SETTINGS_MODULE=config.settings.prod

WORKDIR /app

RUN adduser --disabled-password --gecos "" appuser

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY --from=frontend-builder --chown=appuser:appuser /app /app

RUN mkdir -p /app/staticfiles /app/media \
    && chown -R appuser:appuser /app/staticfiles /app/media

USER appuser
#RUN python manage.py collectstatic --noinput --settings=config.settings.prod

#CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:$PORT"]
CMD ["sh", "-c", "BOOTSTRAP_SKIP_DB=1 BOOTSTRAP_SKIP_MIGRATE=1 BOOTSTRAP_LOAD_FIXTURES=0 BOOTSTRAP_SKIP_COLLECTSTATIC=0 python manage.py bootstrap && gunicorn config.wsgi:application --bind 0.0.0.0:$PORT"]

EXPOSE 8000
