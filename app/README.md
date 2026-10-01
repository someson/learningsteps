# LearningSteps

LearningSteps is a Python FastAPI + PostgreSQL application that helps people track their daily learning journey: what they worked on, what they struggled with, and what they intend to do next. It serves a web UI at `/` and a JSON API under `/api`, with sign-in (Microsoft Entra ID in production, passwords locally), per-user journals and an administrator role.

This document covers the application in `app/`. Infrastructure, deployment and the build log are in the repository's other directories (`infra-terraform/`, `k8s-manifests/`, `.github/workflows/`).

## Table of Contents

- [🚀 Getting Started](#-getting-started)
- [🧪 Running Tests](#-running-tests)
- [🎨 Web UI Development](#-web-ui-development)
- [⚙️ API Endpoints](#️-api-endpoints)
- [🔑 Authentication and Users](#-authentication-and-users)
- [🔐 Configuration](#-configuration)
- [📈 Metrics](#-metrics)
- [📦 Container Image](#-container-image)
- [☁️ Deployment](#️-deployment)
- [📊 Data Schema](#-data-schema)
- [🗄️ Explore Your Database (Optional)](#️-explore-your-database-optional)
- [🔧 Troubleshooting](#-troubleshooting)

## 🚀 Getting Started

### Prerequisites

- Git
- Docker Desktop, running
- Python 3 (only to run the tests)

### 1. Configure Your Environment

Two files, both git-ignored, created from their templates:

```bash
cp app/.env-sample app/.env         # API settings; connects as the unprivileged app role
cp app/.env.db-sample app/.env.db   # PostgreSQL admin credentials
```

The API container only receives `app/.env`. The admin credentials in `app/.env.db` go to PostgreSQL and the one-shot `migrate` service, never to the API.

### 2. Start the Stack

From the **repository root**:

```bash
docker compose up -d --build
docker compose ps -a      # migrate: Exited (0); api and postgres: healthy
```

This starts three services:

| Service | What it does |
|---|---|
| `postgres` | PostgreSQL 16, not published on the host |
| `migrate` | Runs `api/migrate.py` once. It creates the `learningsteps` role, applies `database_setup.sql` as the admin role and grants the app role row access only. It is idempotent and runs on every `up` |
| `api` | The API and web UI on `127.0.0.1:8000`; Prometheus metrics on `127.0.0.1:9000` |

The API image is built from `app/Dockerfile`, the same image CI scans and deploys to AKS. After changing code, run `docker compose up -d --build` again. To stop, run `docker compose down` (add `-v` to also wipe the database).

### 3. Create Users

Password sign-in is enabled locally. Create accounts with `create_user.py`. The password is read from stdin and must be at least 12 characters:

```bash
echo 'admin-password-1' | docker compose exec -T api python create_user.py admin --admin
echo 'alice-password-1' | docker compose exec -T api python create_user.py alice
echo 'bob-password-123' | docker compose exec -T api python create_user.py bob
```

### 4. Try It 🎉

1. **Web UI**: http://localhost:8000/. Sign in, then create, search, sort, edit and delete entries (with Undo).
2. **API docs**: http://localhost:8000/docs (Swagger UI, available after signing in).
3. **Administration**: http://localhost:8000/admin, as `admin`.

## 🧪 Running Tests

`test_api.py` runs about 100 end-to-end checks against the running stack: CRUD, validation, authentication, isolation between users, rate limiting, CSRF, security headers, the admin API and metrics. It needs `requests`, a dev-only dependency that is not in the image:

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r app/requirements-dev.txt
METRICS_URL=http://localhost:9000/metrics python app/test_api.py
```

It uses the three accounts from [Create Users](#3-create-users) by default. Override them with `TEST_USER` / `TEST_PASSWORD`, `TEST_USER2` / `TEST_PASSWORD2` and `TEST_ADMIN` / `TEST_ADMIN_PASSWORD`, and set `BASE_URL` to test another deployment. Without `METRICS_URL` the metrics port is not checked.

After many runs, failed-login throttling can lock the test accounts for 15 minutes. To reset it:

```bash
docker compose exec postgres psql -U postgres -d learning_journal -c "delete from login_failures"
```

Lint: `ruff check app` (configuration in `app/ruff.toml`). CI runs both.

## 🎨 Web UI Development

The web UI lives in `frontend/`. It uses Vite, React, TypeScript, Tailwind and shadcn/ui. The Docker image builds it in a separate Node stage and FastAPI serves the result from `api/static/`. For hot reload during development:

```bash
cd app/frontend
npm ci
npm run dev        # http://localhost:5173, /api is proxied to localhost:8000
```

`npm run build` writes the production bundle to `api/static/` (git-ignored).

## ⚙️ API Endpoints

All data endpoints live under `/api` and require a session unless noted. Requests with a body must be `application/json`. Cross-site requests are rejected (CSRF protection via `Sec-Fetch-Site` / `Origin`).

**Entries**: every query is scoped to the signed-in user. Another user's entry answers 404.

| Method | Path | Description | Errors |
|---|---|---|---|
| POST | `/api/entries` | Create an entry | 422 invalid input |
| GET | `/api/entries` | List own entries. Query: `limit` (1–100, default 20), `offset`, `q` (search in all text fields or an ID prefix), `sort` (`created_at`, `updated_at`, `work`, `struggle`, `intention`), `dir` (`asc` / `desc`) | 422 |
| GET | `/api/entries/{entry_id}` | Get one entry | 404, 422 not a UUID |
| PATCH | `/api/entries/{entry_id}` | Partial update: send only the fields to change | 400 empty body, 404, 422 unknown field / null / invalid value |
| DELETE | `/api/entries/{entry_id}` | Soft delete (restorable) | 404 |
| POST | `/api/entries/{entry_id}/restore` | Undo a delete | 404 |
| DELETE | `/api/entries` | Soft delete **all own** entries | |

**Authentication**

| Method | Path | Description |
|---|---|---|
| GET | `/api/auth/config` | Which sign-in methods are enabled (no session needed) |
| POST | `/api/auth/login` | Password sign-in; sets the session cookie (401 wrong credentials, 403 blocked, 404 password sign-in disabled, 429 throttled) |
| GET | `/api/auth/entra/login` | Starts sign-in with Microsoft |
| GET | `/api/auth/entra/callback` | Microsoft redirects here |
| POST | `/api/auth/logout` | Ends the session |
| GET | `/api/auth/me` | The signed-in user (name, admin flag) |

**Administration** (admin role only: 401 anonymous, 403 other users)

| Method | Path | Description |
|---|---|---|
| GET | `/api/admin/users` | All users with entry count, registration and last sign-in |
| POST | `/api/admin/users/{user_id}/block` | Block a user; ends all their sessions at once (not yourself) |
| POST | `/api/admin/users/{user_id}/unblock` | Unblock |
| POST | `/api/admin/orphans/adopt` | Assign entries created before accounts existed to yourself |

Admins cannot read other users' journals.

**Pages and probes**

| Path | Description |
|---|---|
| `/` | Web UI |
| `/admin` | Administration page (401 / 403 pages without the role) |
| `/docs`, `/openapi.json` | Swagger UI and schema, signed-in users only (or everyone with `ENABLE_DOCS=true`) |
| `/healthz` | Liveness: the process is up; does not touch the database |
| `/readyz` | Readiness: the database answers (503 otherwise) |

Errors are JSON under `/api` and `/openapi.json`, and HTML pages everywhere else (404, 401, 403, 405, 500). A 500 shows only a Request ID that matches the log line; details never reach the client.

## 🔑 Authentication and Users

- **Sessions**: a random token in an `HttpOnly`, `SameSite=Strict` cookie (`Secure` with the `__Host-` prefix behind HTTPS). Only its SHA-256 is stored. Lifetime is `SESSION_TTL_HOURS`.
- **Password sign-in** (`LOCAL_LOGIN=true`, the default; used locally and in CI): accounts come from `create_user.py`. Pass `--reset` to set a new password for an existing account. Failed attempts are throttled to 5 per account and 50 per IP within 15 minutes.
- **Microsoft Entra ID** (production): OIDC authorization code + PKCE. Users are created on first sign-in, and only the allowed tenants may sign in. In AKS the API authenticates to Entra with its Workload Identity token, so there is no client secret. Outside AKS, set `ENTRA_CLIENT_SECRET` or `ENTRA_CLIENT_SECRET_FILE`.
- **Administrators**: `create_user.py <name> --admin` locally. For Entra users, the `Admin` app role is read from the token at every sign-in.
- **Ownerless entries** (created before accounts existed) can be handed over with **Assign to me** in `/admin`, or `python adopt_orphans.py <username or UPN>` in the API container.

Every sign-in, change, deletion and admin action is written to the `audit` logger with user, IP and `X-Request-ID`. Entry contents are never logged.

## 🔐 Configuration

API settings (`app/.env` locally, ConfigMap in AKS):

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | — | Connection string for the app role, e.g. `postgresql://learningsteps:…@postgres:5432/learning_journal` |
| `DATABASE_URL_FILE` | — | Path to a file with the connection string; takes precedence. Used in AKS, where the secret is mounted from Key Vault, so the password never appears in the process environment |
| `DB_POOL_MAX_SIZE` | `5` | Max connections per process. Keep replicas × this well below the server's `max_connections` |
| `COOKIE_SECURE` | `true` | `false` only for plain-HTTP local runs |
| `SESSION_TTL_HOURS` | `12` | Session lifetime |
| `LOCAL_LOGIN` | `true` | Password sign-in; `false` in AKS |
| `ENABLE_DOCS` | `false` | Show `/docs` to anonymous visitors too |
| `ENTRA_CLIENT_ID`, `ENTRA_TENANT_ID`, `ENTRA_ALLOWED_TENANTS`, `ENTRA_REDIRECT_URI` | — | Sign-in with Microsoft; disabled when unset |
| `ENTRA_CLIENT_SECRET` / `ENTRA_CLIENT_SECRET_FILE` | — | Only when running outside AKS (no Workload Identity) |
| `METRICS_PORT` | `9000` | Prometheus metrics port |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | uvicorn setting. `*` in AKS, where only Caddy can reach the API, so client IPs are taken from `X-Forwarded-For` |

Migration settings (`app/.env.db` locally, Key Vault in AKS): `ADMIN_DATABASE_URL` or `ADMIN_DATABASE_URL_FILE` (server admin), plus the app role's `DATABASE_URL` or `DATABASE_URL_FILE`.

One connection pool is opened at startup and shared by all requests.

## 📈 Metrics

Prometheus metrics are served on a separate port (`METRICS_PORT`, 9000), not on the app port. The ingress (Caddy) only ever proxies to 8000, so metrics cannot reach the internet. See `api/metrics.py` for the full list:

- `learningsteps_http_requests_total{method,route,status}` and `learningsteps_http_request_duration_seconds`: labelled by route template (`/api/entries/{entry_id}`), never raw paths
- `learningsteps_db_up`, `learningsteps_db_ping_duration_seconds`, `learningsteps_db_pool_connections`: a database probe every 10 s
- `learningsteps_logins_total{method,result}`
- process CPU, memory and GC

For a local Prometheus + Grafana with the LearningSteps dashboard, run `docker compose --profile monitoring up -d --build` from the repository root. Grafana is on http://localhost:3000 and Prometheus on http://localhost:9090.

## 📦 Container Image

`app/Dockerfile` builds the image used locally and in Azure:

- **Stages**: Node builds the web UI, a Chainguard `-dev` image installs the Python dependencies into a venv, and only the venv, code and static files go into the runtime image.
- **Base**: Chainguard Python, pinned by digest. It has no shell and no package manager, and Trivy reports 0 known vulnerabilities at the pinned digest. Dependabot bumps the digests.
- **User**: runs as non-root UID `65532`. The application code is owned by root and read-only for that user.
- **Filesystem**: compatible with a read-only root filesystem (only `/tmp` needs to be writable).
- **pip**: removed from the shipped virtualenv.
- **Entrypoint**: only `python`, so the migration Job runs the same image with `migrate.py`. It serves on port `8000`, with no `--reload`.

## ☁️ Deployment

Every push to `main` is built, tested and scanned by `.github/workflows/ci-cd.yml`, then deployed to AKS: images are pushed to ACR, the migration Job runs, and the API and Caddy are rolled out. Azure resources are defined in `infra-terraform/` (see its README), and Kubernetes manifests are in `k8s-manifests/`. The monitoring stack for AKS is installed separately with `k8s-manifests/monitoring/install.sh`.

For manual work you need the Azure CLI (`brew install azure-cli`, then `az login`), plus kubectl and kubelogin for cluster access.

## 📊 Data Schema

Each journal entry:

| Field | Type | Description | Validation |
|---|---|---|---|
| id | UUID | Unique identifier | Auto-generated |
| work | string | What did you work on today? | Required, 3–256 characters |
| struggle | string | What's one thing you struggled with today? | Required, 3–256 characters |
| intention | string | What will you study/work on tomorrow? | Required, 3–256 characters |
| created_at | datetime | When the entry was created | Auto-generated UTC |
| updated_at | datetime | When the entry was last updated | Auto-updated UTC |

Text fields are trimmed, and whitespace-only values are rejected. Unknown fields in a PATCH body are rejected with 422.

In the database (`database_setup.sql`):

| Table | Contents |
|---|---|
| `entries` | Entry text as JSONB, the owner (`user_id`), timestamps, and `deleted_at` for soft deletes |
| `users` | Local and Entra accounts, admin flag, block status (`disabled_at`) |
| `sessions` | SHA-256 of session tokens with expiry |
| `login_failures` | Failed sign-ins, used for throttling |

The admin role owns all tables. The app role `learningsteps` has only the row privileges it needs: no DDL, and no `DELETE` on `entries` or `users`.

## 🗄️ Explore Your Database (Optional)

PostgreSQL is not published on the host by default. To connect a SQL client, uncomment the `ports` line of the `postgres` service in `docker-compose.yml` and run `docker compose up -d`.

With VS Code's PostgreSQL extension (by Chris Kolkman):

1. **Open the PostgreSQL panel** in the sidebar and click **Add Connection** (`+`).
2. **Enter**:
   - **Host name**: `localhost`
   - **User name**: `postgres`
   - **Password**: `postgres`
   - **Port**: `5432`
   - **Connection type**: `Standard/No SSL`
   - **Database**: `learning_journal`
   - **Display name**: `Learning Journal DB`
3. **Expand the connection**, right-click `learning_journal` → **New Query**, and run:

```sql
SELECT id, user_id, data, created_at, deleted_at FROM entries ORDER BY created_at DESC;
```

Without a client: `docker compose exec postgres psql -U postgres -d learning_journal`.

## 🔧 Troubleshooting

**The API won't start**

- Check the services: `docker compose ps -a`. `migrate` must be `Exited (0)`; `api` and `postgres` must be `healthy`.
- Read the logs: `docker compose logs migrate`, `docker compose logs api`, `docker compose logs postgres`.
- `app/.env` and `app/.env.db` must both exist, and their URLs must use host `postgres` (the compose service name).

**Tables are missing or permission denied**

- `migrate` applies the schema and grants on every `up`. Check `docker compose logs migrate`. For a clean start: `docker compose down -v && docker compose up -d --build`.

**Sign-in fails with 429 or "Too many failed attempts"**

- Throttling: wait 15 minutes, or clear `login_failures` (see [Running Tests](#-running-tests)).

**Sign-in works but the session is lost immediately**

- Over plain HTTP the cookie must not be `Secure`: set `COOKIE_SECURE=false` in `app/.env` (the sample already does).

**The web UI says it is not built**

- Only happens when running the API outside Docker: run `npm ci && npm run build` in `app/frontend`.

**Port 8000 or 9000 is busy**

- Change the left side of `127.0.0.1:8000:8000` or `127.0.0.1:9000:9000` in `docker-compose.yml`.

**You need a shell inside the API container**

- There is none, by design :P. Use `docker compose logs api`, or `docker compose exec api python -c '…'`. For interactive debugging, temporarily build with `cgr.dev/chainguard/python:latest-dev` as the runtime base.
