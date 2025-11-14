import os
import time
import hashlib
import jwt
from typing import Optional

from app.database import get_db_connection

ALGORITHM = "HS256"
SECRET = os.getenv("JWT_SECRET", "dev_secret")


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(password: str, hashed: str) -> bool:
    return hash_password(password) == hashed


def issue_jwt(user_id: int, role: str) -> str:
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "role": role,
        "iat": now,
        "exp": now + 60 * 60 * 24 * 30,  # 1 month expiration
        "jti": f"{user_id}-{now}",
    }
    return jwt.encode(payload, SECRET, algorithm=ALGORITHM)


def decode_jwt(token: str) -> dict:
    return jwt.decode(token, SECRET, algorithms=[ALGORITHM])


def get_user_by_username(username: str) -> Optional[dict]:
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM user_table WHERE user_username = %s", (username,))
        return cursor.fetchone()


def get_user_by_id(user_id: int) -> Optional[dict]:
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM user_table WHERE user_id = %s", (user_id,))
        return cursor.fetchone()


def get_current_user(access_token: str) -> dict:
    payload = decode_jwt(access_token)
    user_id = int(payload.get("sub"))
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM user_table WHERE user_id = %s", (user_id,))
        user = cursor.fetchone()
        if not user or user.get("user_token") != access_token:
            raise ValueError("Invalid token")
        return user


def is_admin(user: dict) -> bool:
    val = user.get("user_role")
    if isinstance(val, int):
        return val == 1
    return str(val).upper() == "ADMIN"
