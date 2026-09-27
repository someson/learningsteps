# LearningSteps API

Welcome to LearningSteps! LearningSteps is a Python FastAPI + PostgreSQL application that helps people track their daily learning journey. This is a reference implementation, deploy this to the cloud!


## Table of Contents

- [🚀 Getting Started](#-getting-started)
- [🧪 Running Tests](#-running-tests)
- [⚙️ API Endpoints](#️-api-endpoints)
- [🔐 Configuration](#-configuration)
- [📦 Container Image](#-container-image)
- [☁️ Deployment](#️-deployment)
- [📊 Data Schema](#-data-schema)
- [🗄️ Explore Your Database (Optional)](#️-explore-your-database-optional)
- [🔧 Troubleshooting](#-troubleshooting)

## 🚀 Getting Started

### Prerequisites

- Git
- Docker Desktop, running

### 1. Configure Your Environment (.env)

Environment variables live in `app/.env` (git-ignored, so secrets are not committed). Copy the template:

   ```bash
   cp app/.env-sample app/.env
   ```

### 2. Start the Stack

From the **repository root**:

   ```bash
   docker compose up -d --build
   ```

This builds the API image from `app/Dockerfile` (the same image CI pushes to ACR) and starts PostgreSQL 16. The schema in `database_setup.sql` is applied automatically on the first start with an empty volume.

Check both containers report `healthy`:

   ```bash
   docker compose ps
   ```

After changing code, rebuild with the same `docker compose up -d --build`. Stop with `docker compose down` (add `-v` to also wipe the database).

### 3. Test Everything Works! 🎉

1. **Visit the API docs**: http://localhost:8000/docs
1. **Create your first entry** In the Docs UI Use the POST `/entries` endpoint to create a new journal entry.
1. **View your entries** using the GET `/entries` endpoint to see what you've created!

**🎯 Congratulations! You have a fully functional learning journal API with complete CRUD operations, validation, and logging!**

## 🧪 Running Tests

`test_api.py` exercises every endpoint against the running stack on `localhost:8000`. It needs `requests`, which is a dev-only dependency and is not in the image:

   ```bash
   python3 -m venv .venv && . .venv/bin/activate
   pip install -r app/requirements-dev.txt
   python app/test_api.py
   ```

## ⚙️ API Endpoints

| Method | Path | Description | Errors |
|---|---|---|---|
| POST | `/entries` | Create an entry | 422 invalid input |
| GET | `/entries` | List all entries with count | |
| GET | `/entries/{entry_id}` | Get one entry | 404 |
| PATCH | `/entries/{entry_id}` | Partial update: send only the fields to change; the others are kept | 400 empty body, 404, 422 unknown field / null / invalid value |
| DELETE | `/entries/{entry_id}` | Delete one entry | 404 |
| DELETE | `/entries` | Delete **all** entries | |
| GET | `/healthz` | Liveness: the process is up. Does not touch the database | |
| GET | `/readyz` | Readiness: the database answers | 503 |

Server-side failures return a generic message; details go to the logs only, never to the client.

> ⚠️ The API has no authentication. `DELETE /entries` wipes the table for anyone who can reach it. Do not expose it publicly without an auth layer in front.

## 🔐 Configuration

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | — | Connection string, e.g. `postgresql://user:pass@host:5432/learning_journal` |
| `DATABASE_URL_FILE` | — | Path to a file containing the connection string. Takes precedence over `DATABASE_URL`. Used in Kubernetes, where the secret is mounted from Key Vault as a file, so the password never appears in the process environment |
| `DB_POOL_MAX_SIZE` | `5` | Max connections per process. Keep replicas × this well below the server's `max_connections` |

One connection pool is opened at startup and shared by all requests.

## 📦 Container Image

`app/Dockerfile` builds the image used locally and in Azure:

- Base: Chainguard Python, pinned by digest. No shell and no package manager; Trivy reports 0 known vulnerabilities at the pinned digest
- Runs as non-root UID `65532`; application code is owned by root and read-only for that user
- Compatible with a read-only root filesystem (only `/tmp` needs to be writable)
- `pip` is removed from the shipped virtualenv
- Serves on port `8000`, no `--reload`

## ☁️ Deployment

Azure resources are defined in `infra-terraform/` and deployed with Terraform; see `infra-terraform/README.md`. You need the Azure CLI installed locally (`brew install azure-cli`) and logged in (`az login`).

## 📊 Data Schema

Each journal entry follows this structure:

| Field       | Type      | Description                                | Validation                   |
|-------------|-----------|--------------------------------------------|------------------------------|
| id          | string    | Unique identifier (UUID)                   | Auto-generated               |
| work        | string    | What did you work on today?                | Required, 3–256 characters   |
| struggle    | string    | What's one thing you struggled with today? | Required, 3–256 characters   |
| intention   | string    | What will you study/work on tomorrow?      | Required, 3–256 characters   |
| created_at  | datetime  | When entry was created                     | Auto-generated UTC           |
| updated_at  | datetime  | When entry was last updated                | Auto-updated UTC             |

Text fields are trimmed; whitespace-only values are rejected. Unknown fields in a PATCH body are rejected with 422.

## 🗄️ Explore Your Database (Optional)

Want to see your data directly in the database? You can connect to PostgreSQL using VS Code's PostgreSQL extension:

### 1. Install PostgreSQL Extension

1. **Install the PostgreSQL extension** in VS Code (search for "PostgreSQL" by Chris Kolkman)
2. **Restart VS Code** after installation

### 2. Connect to Your Database

1. **Open the PostgreSQL extension** (click the PostgreSQL icon in the sidebar)
2. **Click "Add Connection"** or the "+" button
3. **Enter these connection details**:
   - **Host name**: `localhost` (first uncomment the `ports` line of the `postgres` service in `docker-compose.yml`)
   - **User name**: `postgres`
   - **Password**: `postgres`
   - **Port**: `5432`
   - **Conection Type**: `Standard/No SSL`
   - **Database**: `learning_journal`
   - **Display name**: `Learning Journal DB` (or any name you prefer)

### 3. Explore Your Data

1. **Expand your connection** in the PostgreSQL panel
2. **Left-click on "Learning Journal DB" to expand**
3. **Right-click on "learning_journal"**
4. **Select "New Query"**
5. **Type this query** to see all your entries:

   ```sql
   SELECT * FROM entries;
   ```

6. **Run the query** to see all your journal data! (Ctrl/Cmd + Enter OR use the PostgreSQL command pallete: Run Query)

You can now explore the database structure, see exactly how your data is stored, and run custom queries to understand PostgreSQL better.

## 🔧 Troubleshooting

**If the API won't start:**

- Check status: `docker compose ps` — both services should be `healthy`
- Read the logs: `docker compose logs api` / `docker compose logs postgres`
- `DATABASE_URL` in `app/.env` must use host `postgres` (the compose service name)

**If `entries` table is missing:**

- The schema is applied only when the database volume is empty. Reset it: `docker compose down -v && docker compose up -d --build`

**If port 8000 is busy:**

- Change the left side of `127.0.0.1:8000:8000` in `docker-compose.yml`

**If you need a shell inside the API container:**

- There is none, by design. Use `docker compose logs api`. For interactive debugging, temporarily build with `cgr.dev/chainguard/python:latest-dev` as the runtime base
