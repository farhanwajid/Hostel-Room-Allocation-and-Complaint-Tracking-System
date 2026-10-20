"""Set real Argon2 passwords for the seeded accounts (sample_data.sql ships invalid hashes).

Usage (from backend/):
    PYTHONPATH=. python scripts/set_admin_password.py              # one account, prompts for email
    PYTHONPATH=. python scripts/set_admin_password.py --all-demo   # every @hostel.local account, one password
"""
import sys
from getpass import getpass

from argon2 import PasswordHasher
from sqlalchemy import text

from app.db import SessionLocal


def main() -> None:
    all_demo = "--all-demo" in sys.argv
    email = None if all_demo else (input("Account email [admin@hostel.local]: ").strip() or "admin@hostel.local")
    password = getpass("New password: ")
    if len(password) < 8:
        raise SystemExit("Password must contain at least 8 characters.")
    if password != getpass("Confirm password: "):
        raise SystemExit("Passwords do not match.")

    hashed = PasswordHasher().hash(password)
    with SessionLocal.begin() as db:
        if all_demo:
            result = db.execute(text("UPDATE users SET password_hash=:h, is_active=TRUE WHERE email LIKE '%@hostel.local'"),
                                {"h": hashed})
        else:
            result = db.execute(text("UPDATE users SET password_hash=:h, is_active=TRUE WHERE email=:e"),
                                {"h": hashed, "e": email})
        if result.rowcount < 1:
            raise SystemExit("No matching user found. Load sample_data.sql or create the account first.")
    print(f"Password updated for {result.rowcount} account(s).")


if __name__ == "__main__":
    main()
