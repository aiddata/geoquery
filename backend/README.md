# GeoQuery Backend

Django + DRF backend for GeoQuery. See the repository root for the full
docker-compose development stack.

## User accounts (django-allauth)

Authentication uses [django-allauth](https://docs.allauth.org/) in headless
mode with a custom user model (`accounts.User`). Login is GitHub OAuth
(session-cookie based); users claim historical requests by verifying the email
addresses they used when submitting them.

Required environment variables (set in the root `.env` for compose):

- `GITHUB_OAUTH_CLIENT_ID` / `GITHUB_OAUTH_CLIENT_SECRET` — from a GitHub
  OAuth App with callback URL
  `http://localhost:5173/api/accounts/github/login/callback/` in dev
  (`https://<domain>/api/accounts/github/login/callback/` in production).
  The whole OAuth round-trip goes through the frontend origin: the Vite proxy
  forwards `/api` to Django without rewriting the Host header
  (`changeOrigin: false`), so Django generates the redirect URI from the
  browser-facing origin.
- `EMAIL_PASSWORD` — SMTP password for verification email (in dev, emails
  print to the backend container log via the console email backend instead).

### One-time migration for existing dev databases

`AUTH_USER_MODEL` was switched from `auth.User` to `accounts.User`. Databases
migrated before this change must drop Django's auth/admin tables once (data
tables — `requests`, `extract_tasks`, features, datasets — are untouched;
admin users and sessions are lost and must be recreated):

```bash
docker compose exec db psql -U django_user -d geoquery
```

```sql
BEGIN;
DROP TABLE IF EXISTS django_admin_log CASCADE;
DROP TABLE IF EXISTS auth_user_groups, auth_user_user_permissions, auth_user CASCADE;
DROP TABLE IF EXISTS auth_group_permissions, auth_group, auth_permission CASCADE;
DROP TABLE IF EXISTS django_content_type CASCADE;
DELETE FROM django_migrations WHERE app IN ('admin', 'auth', 'contenttypes', 'accounts');
DELETE FROM django_session;
COMMIT;
```

Then:

```bash
docker compose exec backend uv run python manage.py migrate
docker compose exec backend uv run python manage.py createsuperuser
```

### Claiming historical requests

`analytics.Request.user` links requests to accounts. Whenever a user verifies
an email address (including GitHub-verified addresses at signup), all
unclaimed requests whose `contact` matches it case-insensitively are attached
to their account (`accounts/claims.py`, `accounts/signals.py`). To backfill
after a bulk import:

```bash
docker compose exec backend uv run python manage.py backfill_request_claims [--dry-run]
```
