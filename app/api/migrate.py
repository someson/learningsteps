"""One-shot database migration, run as a Kubernetes Job before each deploy.

Terraform cannot reach the private Flexible Server, so this Job does the
in-database setup that the VM deployment did by hand:

  1. create (or re-password) the application role from the app DSN
  2. restrict the database to that role
  3. apply database_setup.sql *as the application role*, so it owns its tables

Idempotent: safe to run on every deploy. Re-running after a password
rotation (postgres_password_version bump) resets the role's password.

Reads two connection strings from mounted files, never from the environment:
  ADMIN_DATABASE_URL_FILE  server admin (only the migrator identity can read it)
  DATABASE_URL_FILE        application role
"""
import asyncio
import logging
import os
from urllib.parse import unquote, urlparse

import asyncpg

logging.basicConfig(level=logging.INFO, format="%(asctime)s - migrate - %(levelname)s - %(message)s")
logger = logging.getLogger("migrate")

SCHEMA_PATH = os.getenv("SCHEMA_PATH", "/app/database_setup.sql")


def read_secret(env_var: str) -> str:
    with open(os.environ[env_var]) as f:
        return f.read().strip()


async def quoted(conn: asyncpg.Connection, template: str, *args: str) -> str:
    """Build a DDL statement with server-side quoting.

    DDL cannot take bind parameters, so identifiers and literals are quoted
    by Postgres itself via format(%I / %L) rather than by string formatting.
    """
    placeholders = ", ".join(f"${i}::text" for i in range(1, len(args) + 1))
    return await conn.fetchval(f"SELECT format('{template}', {placeholders})", *args)


async def main() -> None:
    admin_dsn = read_secret("ADMIN_DATABASE_URL_FILE")
    app_dsn = read_secret("DATABASE_URL_FILE")

    app = urlparse(app_dsn)
    role, password, database = unquote(app.username), unquote(app.password), app.path.lstrip("/")

    conn = await asyncpg.connect(admin_dsn)
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", role)
        verb = "ALTER" if exists else "CREATE"
        await conn.execute(await quoted(conn, f"{verb} ROLE %I WITH LOGIN PASSWORD %L", role, password))
        logger.info("%s role %s", "Updated" if exists else "Created", role)

        await conn.execute(await quoted(conn, "REVOKE ALL ON DATABASE %I FROM PUBLIC", database))
        await conn.execute(await quoted(conn, "GRANT CONNECT, TEMPORARY ON DATABASE %I TO %I", database, role))
        await conn.execute(await quoted(conn, "GRANT USAGE, CREATE ON SCHEMA public TO %I", role))
        logger.info("Granted %s access to database %s", role, database)
    finally:
        await conn.close()

    with open(SCHEMA_PATH) as f:
        schema = f.read()

    conn = await asyncpg.connect(app_dsn)
    try:
        async with conn.transaction():
            await conn.execute(schema)
        logger.info("Schema applied from %s", SCHEMA_PATH)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
