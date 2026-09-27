"""Seed or manage local user credentials for Drishti Workbench.

Usage:
    python scripts/seed_users.py [--username operator] [--role operator] [--display-name "Plant Operator"]
"""

import argparse
import getpass
import os
import sys
from pathlib import Path

# Add backend directory to sys.path so app imports work
backend_dir = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(backend_dir))

from app.services import auth_service  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed or update Drishti users.")
    parser.add_argument("--username", default="operator", help="Username to create/update")
    parser.add_argument("--role", default="operator", choices=["operator", "demo", "admin"], help="User role")
    parser.add_argument("--display-name", default="Plant Operator", help="Display name")
    parser.add_argument("--password", default=None, help="Password (prompted securely if omitted)")

    args = parser.parse_args()

    # Initialize tables and default seed accounts
    auth_service.seed_initial_users()

    password = args.password or os.environ.get("SEED_OPERATOR_PASSWORD")
    if not password:
        password = getpass.getpass(f"Enter password for '{args.username}': ")

    existing = auth_service.get_user_by_username(args.username)
    if existing:
        print(f"User '{args.username}' already exists (id={existing['id']}, role={existing['role']}).")
    else:
        user = auth_service.create_user(
            username=args.username,
            password=password,
            display_name=args.display_name,
            role=args.role,
        )
        print(f"Created user '{user['username']}' with id={user['id']}.")

    print("Seed complete. Judge demo account and operator account are ready.")


if __name__ == "__main__":
    main()
