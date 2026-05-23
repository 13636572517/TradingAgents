#!/usr/bin/env python3
"""CLI tool for managing TradingAgents users.

Usage:
  python manage_users.py add <username> <password>
  python manage_users.py list
  python manage_users.py delete <username>
  python manage_users.py reset-password <username> <new_password>
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from server.database import SessionLocal, engine, Base
from server import models as _models_module  # noqa: F401 — register all models


def _ensure_tables():
    Base.metadata.create_all(bind=engine)


def add_user(username: str, password: str) -> int:
    from server.models import User
    from server.auth import hash_password
    _ensure_tables()
    db = SessionLocal()
    try:
        if db.query(User).filter(User.username == username).first():
            print(f"Error: user '{username}' already exists")
            return 1
        user = User(username=username, hashed_password=hash_password(password))
        db.add(user)
        db.commit()
        print(f"Created user '{username}'")
        return 0
    finally:
        db.close()


def list_users() -> int:
    from server.models import User
    _ensure_tables()
    db = SessionLocal()
    try:
        users = db.query(User).order_by(User.created_at).all()
        if not users:
            print("No users found")
            return 0
        print(f"{'ID':<5} {'Username':<20} {'Active':<8} Created")
        print("-" * 55)
        for u in users:
            print(f"{u.id:<5} {u.username:<20} {'Yes' if u.is_active else 'No':<8} {u.created_at}")
        return 0
    finally:
        db.close()


def delete_user(username: str) -> int:
    from server.models import User
    _ensure_tables()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            print(f"Error: user '{username}' not found")
            return 1
        db.delete(user)
        db.commit()
        print(f"Deleted user '{username}'")
        return 0
    finally:
        db.close()


def reset_password(username: str, new_password: str) -> int:
    from server.models import User
    from server.auth import hash_password
    _ensure_tables()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            print(f"Error: user '{username}' not found")
            return 1
        user.hashed_password = hash_password(new_password)
        db.commit()
        print(f"Password reset for '{username}'")
        return 0
    finally:
        db.close()


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    cmd = args[0]
    if cmd == "add" and len(args) == 3:
        return add_user(args[1], args[2])
    if cmd == "list" and len(args) == 1:
        return list_users()
    if cmd == "delete" and len(args) == 2:
        return delete_user(args[1])
    if cmd == "reset-password" and len(args) == 3:
        return reset_password(args[1], args[2])
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
