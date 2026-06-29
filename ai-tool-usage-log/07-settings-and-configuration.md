# Project Configuration — Settings, Redis, Celery, Sessions
**Tool used:** Claude 3.5 Sonnet
**Date:** June 25, 2026

---

## Context

Needed to configure `settings.py` to support: a custom user model, PostgreSQL with an SQLite fallback, Redis for Celery and caching, session persistence, and a way to point the Django app at the email service URL without hardcoding it. Everything environment-sensitive goes into a `.env` file so there are no credentials in source control.

---

## Part 1: Database configuration with env-based fallback

## Prompt I used

> Configure Django's `DATABASES` setting to support both PostgreSQL (for production) and SQLite (for zero-config local dev). All credentials should come from environment variables using `python-dotenv`. If the env vars are missing, fall back to SQLite automatically.

## What I got back

```python
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR.parent / '.env')

DATABASES = {
    'default': {
        'ENGINE':   os.getenv('DB_ENGINE',   'django.db.backends.sqlite3'),
        'NAME':     os.getenv('DB_NAME',      BASE_DIR / 'db.sqlite3'),
        'USER':     os.getenv('DB_USER',      ''),
        'PASSWORD': os.getenv('DB_PASSWORD',  ''),
        'HOST':     os.getenv('DB_HOST',      ''),
        'PORT':     os.getenv('DB_PORT',      ''),
    }
}
```

Used exactly as provided. The fallback to SQLite means new contributors can run the project with zero setup — just `python manage.py runserver`.

Important limitation documented in the README: `select_for_update()` is silently ignored by SQLite. The race condition protection in `book_slot` only works correctly on PostgreSQL. SQLite is fine for dev but must not be used for production under real traffic.

---

## Part 2: Custom user model and auth settings

## Prompt I used

> Set `AUTH_USER_MODEL` to the custom User model. Configure `LOGIN_URL` and `LOGIN_REDIRECT_URL` so Django's auth decorators redirect to the right places.

## What I got back

```python
AUTH_USER_MODEL      = 'core.User'
LOGIN_URL            = 'login'
LOGIN_REDIRECT_URL   = 'dashboard'
```

Standard. `LOGIN_URL = 'login'` means all the `@login_required` and `user_passes_test` decorators redirect to the named URL `login` instead of `/accounts/login/` (Django's default).

---

## Part 3: Redis cache, Celery broker, and session backend

This was the most involved configuration decision. Three things all use Redis, and they need to be separated properly.

## Prompt I used

> Configure Redis as Django's cache backend using `django-redis`. Also configure Celery to use Redis as its broker and result backend. For sessions, I want them to be fast (Redis-cached) but not lost on Redis restart — use `cached_db` session engine so Redis is the read layer and the database is the persistent fallback.

## Why `cached_db` matters

Pure `cache` sessions store everything in Redis only. If Redis restarts (common in dev), all sessions are wiped — every logged-in user gets a CSRF 403 on their next request. `cached_db` reads from Redis but falls back to the database, so a Redis restart is invisible to logged-in users.

## What I got back

```python
CACHES = {
    'default': {
        'BACKEND':  'django_redis.cache.RedisCache',
        'LOCATION': 'redis://127.0.0.1:6379/1',   # db 1 for cache
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
        },
    }
}

SESSION_ENGINE      = 'django.contrib.sessions.backends.cached_db'
SESSION_CACHE_ALIAS = 'default'
SESSION_COOKIE_AGE  = 86400   # 24 hours

CELERY_BROKER_URL      = 'redis://127.0.0.1:6379/0'   # db 0 for Celery
CELERY_RESULT_BACKEND  = 'redis://127.0.0.1:6379/0'
CELERY_ACCEPT_CONTENT  = ['json']
CELERY_TASK_SERIALIZER = 'json'
```

Celery uses Redis db 0, the cache uses db 1 — keeps them from interfering with each other.

---

## Part 4: Email service URL configuration

## Prompt I used

> The Django app needs to call the serverless email service at `http://localhost:3000/dev` in development. In production this will be an AWS API Gateway URL. Store this as a setting that reads from an env variable with a local dev default.

## What I got back

```python
EMAIL_SERVICE_BASE_URL = os.getenv('EMAIL_SERVICE_BASE_URL', 'http://localhost:3000/dev')
```

Used in `services.py` as `settings.EMAIL_SERVICE_BASE_URL`. To point the app at a real AWS deployment, just set the env var — no code changes needed.

---

## Part 5: Timezone configuration

## Prompt I used

> The app is used in India. Configure Django's timezone to `Asia/Kolkata` (IST). Make it readable from an env variable so it can be changed per deployment.

## What I got back

```python
TIME_ZONE = os.getenv('TIME_ZONE', 'Asia/Kolkata')
USE_TZ    = True
```

`USE_TZ = True` means Django stores all datetimes in UTC internally and converts to the configured timezone for display. This is important for the slot overlap detection and past-time validation in `AvailabilitySlot.clean()` — all comparisons use `timezone.localtime(timezone.now())` rather than `datetime.now()`, which would be naive and break under timezone-aware storage.

---

## Part 6: Logging

## Prompt I used

> Set up basic Django logging to print INFO-level logs from all loggers to the console. The app uses `logger.warning()` and `logger.error()` in several places for Celery task failures and calendar sync issues.

## What I got back

```python
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
}
```

Used as-is. All `logger.warning()` and `logger.error()` calls in `views.py` and `services.py` surface in the Django terminal during development, making it easy to spot when Celery tasks fail or calendar sync skips a user.
