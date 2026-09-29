"""Create a user, or reset a user's password.

There is no sign-up endpoint: accounts are created by an operator, inside the
API container, which already has the database credentials:

  docker compose exec -T api python create_user.py alice < password.txt
  kubectl exec -i -n learningsteps deploy/learningsteps-api -- python create_user.py alice < password.txt

The password is read from stdin (first line), never from the command line,
where it would end up in shell history and the process list.

  --reset           set a new password for an existing user; ends their sessions
  --adopt-orphans   give this user the entries created before accounts existed
  --admin           make (or keep) this local account an administrator; with
                    --reset, omitting it removes the role. Entra users get the
                    role from Entra instead (the "Admin" app role)
"""
import argparse
import asyncio
import sys

import asyncpg

from repositories.postgres_repository import PostgresDB
from security import hash_password_sync

MIN_PASSWORD_LENGTH = 12


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("username")
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--adopt-orphans", action="store_true")
    parser.add_argument("--admin", action="store_true")
    args = parser.parse_args()

    username = args.username.strip().lower()
    if not 1 <= len(username) <= 64:
        print("Username must be 1-64 characters", file=sys.stderr)
        return 2

    if sys.stdin.isatty():
        import getpass

        password = getpass.getpass("Password: ")
    else:
        password = sys.stdin.readline().rstrip("\r\n")
    if not MIN_PASSWORD_LENGTH <= len(password) <= 256:
        print(f"Password must be {MIN_PASSWORD_LENGTH}-256 characters", file=sys.stderr)
        return 2

    async with PostgresDB() as db:
        existing = await db.get_user_by_username(username)
        password_hash = hash_password_sync(password)
        if existing and not args.reset:
            print(f"User {username} exists; pass --reset to change the password", file=sys.stderr)
            return 1
        if not existing and args.reset:
            print(f"User {username} does not exist", file=sys.stderr)
            return 1

        if existing:
            await db.set_password(existing["id"], password_hash)
            await db.set_admin(existing["id"], args.admin)
            user_id = existing["id"]
            print(f"Password reset for {username}; existing sessions ended")
        else:
            try:
                user_id = (await db.create_user(username, password_hash, is_admin=args.admin))["id"]
            except asyncpg.UniqueViolationError:
                print(f"User {username} exists", file=sys.stderr)
                return 1
            print(f"Created {'administrator' if args.admin else 'user'} {username}")

        if args.adopt_orphans:
            count = await db.adopt_orphan_entries(user_id)
            print(f"Assigned {count} ownerless entries to {username}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
