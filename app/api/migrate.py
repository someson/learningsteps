"""One-shot database migration: the db-migrate Job in AKS, the `migrate`
service in docker-compose.yml. Runs before the API starts, on every deploy.

  1. create (or re-password) the application role from the app DSN
  2. restrict the database to that role, with no DDL rights
  3. move ownership of existing objects to the admin role (earlier versions
     applied the schema as the application role, which let the API drop or
     alter its own tables)
  4. apply database_setup.sql as the admin role
  5. grant the application role only the row privileges it needs

Idempotent: safe to run on every deploy. Re-running after a password
rotation (postgres_password_version bump) resets the role's password.

Connection strings come from mounted files when set (AKS), else from the
environment (docker compose):
  ADMIN_DATABASE_URL_FILE / ADMIN_DATABASE_URL  server admin
  DATABASE_URL_FILE / DATABASE_URL              application role
"""
import asyncio
import logging
import os
from urllib.parse import unquote, urlparse

import asyncpg

logging.basicConfig(level=logging.INFO, format="%(asctime)s - migrate - %(levelname)s - %(message)s")
logger = logging.getLogger("migrate")

SCHEMA_PATH = os.getenv("SCHEMA_PATH", "/app/database_setup.sql")

# Least privilege per table. No DELETE on entries (deletes are soft, an
# UPDATE) or users: a compromised API process cannot erase journal data.
APP_TABLE_PRIVILEGES = {
    "users": "SELECT, INSERT, UPDATE",
    "sessions": "SELECT, INSERT, DELETE",
    "login_failures": "SELECT, INSERT, DELETE",
    "entries": "SELECT, INSERT, UPDATE",
}


def read_dsn(name: str) -> str:
    path = os.getenv(f"{name}_FILE")
    if path:
        with open(path) as f:
            return f.read().strip()
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"Set {name} or {name}_FILE")
    return value


async def quoted(conn: asyncpg.Connection, template: str, *args: str) -> str:
    """Build a DDL statement with server-side quoting.

    DDL cannot take bind parameters, so identifiers and literals are quoted
    by Postgres itself via format(%I / %L) rather than by string formatting.
    """
    placeholders = ", ".join(f"${i}::text" for i in range(1, len(args) + 1))
    return await conn.fetchval(f"SELECT format('{template}', {placeholders})", *args)


async def main() -> None:
    admin_dsn = read_dsn("ADMIN_DATABASE_URL")
    app_dsn = read_dsn("DATABASE_URL")

    app = urlparse(app_dsn)
    role, password, database = unquote(app.username), unquote(app.password), app.path.lstrip("/")

    # One-shot script: nothing else runs on the event loop, so a blocking read is fine.
    with open(SCHEMA_PATH) as f:  # noqa: ASYNC230
        schema = f.read()

    conn = await asyncpg.connect(admin_dsn)
    try:
        admin = await conn.fetchval("SELECT current_user")
        if admin == role:
            raise SystemExit("DATABASE_URL must use a dedicated application role, not the admin role")

        async with conn.transaction():
            exists = await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", role)
            verb = "ALTER" if exists else "CREATE"
            await conn.execute(
                await quoted(conn, f"{verb} ROLE %I WITH LOGIN NOCREATEDB NOCREATEROLE PASSWORD %L", role, password)
            )
            logger.info("%s role %s", "Updated" if exists else "Created", role)

            await conn.execute(await quoted(conn, "REVOKE ALL ON DATABASE %I FROM PUBLIC", database))
            await conn.execute(await quoted(conn, "REVOKE ALL ON DATABASE %I FROM %I", database, role))
            await conn.execute(await quoted(conn, "GRANT CONNECT ON DATABASE %I TO %I", database, role))
            await conn.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            await conn.execute(await quoted(conn, "REVOKE CREATE ON SCHEMA public FROM %I", role))
            await conn.execute(await quoted(conn, "GRANT USAGE ON SCHEMA public TO %I", role))

            if exists:
                # Taking objects over needs the privileges of their owner. The
                # admin created the role, so it holds ADMIN OPTION on it and
                # may grant itself membership for the duration of the move.
                await conn.execute(await quoted(conn, "GRANT %I TO CURRENT_USER", role))
                await conn.execute(await quoted(conn, "REASSIGN OWNED BY %I TO CURRENT_USER", role))
                await conn.execute(await quoted(conn, "REVOKE %I FROM CURRENT_USER", role))

            await conn.execute(schema)
            logger.info("Schema applied from %s as %s", SCHEMA_PATH, admin)

            for table, privileges in APP_TABLE_PRIVILEGES.items():
                await conn.execute(await quoted(conn, "REVOKE ALL ON TABLE %I FROM %I", table, role))
                await conn.execute(await quoted(conn, f"GRANT {privileges} ON TABLE %I TO %I", table, role))
            logger.info("Granted %s row privileges only", role)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
