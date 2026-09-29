"""Give the entries created before accounts existed to one user.

The user must exist: a local account (create_user.py) or a Microsoft Entra
account that has signed in at least once. Name it by username or UPN:

  kubectl exec -n learningsteps deploy/learningsteps-api -- python adopt_orphans.py student@university.edu
"""
import argparse
import asyncio
import sys

from repositories.postgres_repository import PostgresDB


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("user", help="local username or Entra UPN (e-mail-style sign-in name)")
    args = parser.parse_args()

    async with PostgresDB() as db:
        user = await db.find_user(args.user.strip().lower())
        if not user:
            print(f"No user {args.user}; Entra users appear after their first sign-in", file=sys.stderr)
            return 1
        count = await db.adopt_orphan_entries(user["id"])
        print(f"Assigned {count} ownerless entries to {user['name']}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
