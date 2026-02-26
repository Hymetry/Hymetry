FROM python:3.12-slim

# Встановлюємо змінні середовища
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Створюємо користувача ДО того, як копіюватимемо файли
RUN adduser --disabled-password --gecos "" appuser

# Встановлюємо системні залежності
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Копіюємо та встановлюємо залежності Python (кешується, поки не зміниться requirements.txt)
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Копіюємо код проекту ОДРАЗУ з потрібними правами
COPY --chown=appuser:appuser . /app

RUN mkdir -p /app/staticfiles /app/media \
    && chown -R appuser:appuser /app/staticfiles /app/media

# Перемикаємось на непривілейованого користувача
USER appuser

EXPOSE 8000