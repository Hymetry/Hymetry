FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN adduser --disabled-password --gecos "" appuser

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY --chown=appuser:appuser . /app

RUN mkdir -p /app/staticfiles /app/media \
    && chown -R appuser:appuser /app/staticfiles /app/media

RUN python manage.py collectstatic --noinput

USER appuser

EXPOSE 8000