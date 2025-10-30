from fastapi import APIRouter
from fastapi import HTTPException, WebSocket, Query, Header
import time
from app.android_service.schemas import (
    RegisterRequest, RegisterResponse,
    LoginRequest, LoginResponse,
    LogoutRequest,
    LoadRequest, LoadResponse, MachineItem,
    ReserveRequest, NotifyMeRequest,
    AdminAddDeviceRequest, SetFcmTokenRequest, AdminAddRoomRequest, AdminAddRoomResponse,
    DeviceSubscribeRequest,
)
from app.auth.security import (
    hash_password, verify_password, issue_jwt, get_current_user, decode_jwt, is_admin
)
from app.websocket.manager import manager
from app.database import get_db_connection

router = APIRouter()

def role_to_str(val) -> str:
    try:
        return "ADMIN" if int(val) == 1 else "USER"
    except Exception:
        return "ADMIN" if str(val).upper() == "ADMIN" else "USER"


def _resolve_token(authorization: str | None, fallback_token: str | None = None) -> str:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1]
    if fallback_token:
        return fallback_token
    raise HTTPException(status_code=401, detail="invalid token")


@router.post("/register", response_model=RegisterResponse)
async def register(body: RegisterRequest):
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT user_id FROM user_table WHERE user_username = %s", (body.user_username,))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail="username already exists")

        hashed = hash_password(body.user_password)
        role_int = 1 if (body.user_role is True) else 0
        cursor.execute(
            "INSERT INTO user_table (user_username, user_password, user_role, user_snum) VALUES (%s, %s, %s, %s)",
            (body.user_username, hashed, role_int, body.user_snum)
        )
        conn.commit()
    return RegisterResponse(message="register ok")

@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest):
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM user_table WHERE user_snum = %s", (body.user_snum,))
        user = cursor.fetchone()
        if not user or not verify_password(body.user_password, user.get("user_password", "")):
            raise HTTPException(status_code=401, detail="invalid credentials")

        role_str = role_to_str(user.get("user_role"))
        token = issue_jwt(int(user["user_id"]), role_str)
        cursor.execute(
            "UPDATE user_table SET user_token = %s, fcm_token = %s WHERE user_id = %s",
            (token, body.fcm_token, user["user_id"]))
        conn.commit()
    return LoginResponse(access_token=token)

@router.post("/logout")
async def logout(body: LogoutRequest, authorization: str | None = Header(None)):
    token = _resolve_token(authorization, getattr(body, "access_token", None))
    try:
        user = get_current_user(token)
    except Exception:
        raise HTTPException(status_code=401, detail="invalid token")

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE user_table SET user_token = NULL WHERE user_id = %s", (user["user_id"],))
        conn.commit()
    return {"message": "logout ok"}


## Removed legacy GET /device_subscribe endpoint

@router.post("/device_subscribe")
async def device_subscribe_post(body: DeviceSubscribeRequest, authorization: str | None = Header(None)):
    # Use header bearer token if present; fallback to body.access_token for backward compatibility
    token = _resolve_token(authorization, getattr(body, "access_token", None))
    try:
        user = get_current_user(token)
    except Exception:
        raise HTTPException(status_code=401, detail="invalid token")

    rid = int(body.room_id)
    user_id = int(user["user_id"])
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        # Ensure room exists by id
        cursor.execute("SELECT 1 FROM room_table WHERE room_id = %s", (rid,))
        r = cursor.fetchone()
        if not r:
            raise HTTPException(status_code=404, detail="room not found")
        # Insert subscription if not exists
        c2 = conn.cursor()
        c2.execute(
            "SELECT 1 FROM room_subscriptions WHERE user_id = %s AND room_id = %s",
            (user_id, rid)
        )
        exists = c2.fetchone()
        if not exists:
            c2.execute(
                "INSERT INTO room_subscriptions (user_id, room_id) VALUES (%s, %s)",
                (user_id, rid)
            )
        conn.commit()
    return {"message": "subscribe ok"}

@router.post("/load", response_model=LoadResponse)
async def load(body: LoadRequest | None = None, authorization: str | None = Header(None)):
    token = _resolve_token(authorization, getattr(body, "access_token", None) if body else None)
    try:
        user = get_current_user(token)
    except Exception:
        raise HTTPException(status_code=401, detail="invalid token")

    # Read role from JWT (for future branching if needed)
    try:
        payload = decode_jwt(token)
        role_in_jwt = str(payload.get("role", "")).upper()
    except Exception:
        role_in_jwt = ""

    user_id = int(user["user_id"])
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        if role_in_jwt == "ADMIN":
            # Admin: show machines in rooms associated to this admin (via room_subscriptions)
            cursor.execute(
                """
                SELECT m.machine_id,
                       COALESCE(rt.room_name, m.room_name) AS room_name,
                       m.machine_name,
                       m.status
                FROM machine_table m
                JOIN room_subscriptions rs ON m.room_id = rs.room_id
                LEFT JOIN room_table rt ON m.room_id = rt.room_id
                WHERE rs.user_id = %s
                """,
                (user_id,)
            )
        else:
            # User: show machines in rooms the user subscribed to
            cursor.execute(
                """
                SELECT m.machine_id,
                       COALESCE(rt.room_name, m.room_name) AS room_name,
                       m.machine_name,
                       m.status
                FROM machine_table m
                JOIN room_subscriptions rs ON m.room_id = rs.room_id
                LEFT JOIN room_table rt ON m.room_id = rt.room_id
                WHERE rs.user_id = %s
                """,
                (user_id,)
            )
        rows = cursor.fetchall() or []

    machines = [
        MachineItem(
            machine_id=int(r["machine_id"]),
            room_name=r.get("room_name") or "",
            machine_name=r.get("machine_name") or "",
            status=r.get("status") or ""
        ) for r in rows
    ]
    return LoadResponse(machine_list=machines)

@router.post("/reserve")
async def reserve(body: ReserveRequest, authorization: str | None = Header(None)):
    if body.isreserved not in (0, 1):
        raise HTTPException(status_code=400, detail="isreserved must be 0 or 1")
    token = _resolve_token(authorization, getattr(body, "access_token", None))
    try:
        user = get_current_user(token)
    except Exception:
        raise HTTPException(status_code=401, detail="invalid token")

    user_id = int(user["user_id"])
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM reservation_table WHERE user_id = %s AND room_id = %s", (user_id, body.room_id))
        row = cursor.fetchone()
        if row:
            cursor.execute(
                "UPDATE reservation_table SET isreserved = %s WHERE user_id = %s AND room_id = %s",
                (body.isreserved, user_id, body.room_id)
            )
        else:
            cursor.execute(
                "INSERT INTO reservation_table (user_id, room_id, isreserved) VALUES (%s, %s, %s)",
                (user_id, body.room_id, body.isreserved)
            )
        cursor.execute(
            "SELECT 1 FROM room_subscriptions WHERE user_id = %s AND room_id = %s",
            (user_id, body.room_id)
        )
        exists = cursor.fetchone()
        if not exists:
            cursor.execute(
                "INSERT INTO room_subscriptions (user_id, room_id) VALUES (%s, %s)",
                (user_id, body.room_id)
            )
        conn.commit()
    return {"message": "reserve ok"}

@router.post("/notify_me")
async def notify_me(body: NotifyMeRequest, authorization: str | None = Header(None)):
    if body.isusing not in (0, 1):
        raise HTTPException(status_code=400, detail="isusing must be 0 or 1")
    token = _resolve_token(authorization, getattr(body, "access_token", None))
    try:
        user = get_current_user(token)
    except Exception:
        raise HTTPException(status_code=401, detail="invalid token")

    user_id = int(user["user_id"])
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        # Resolve machine_uuid by machine_id
        cursor.execute("SELECT machine_uuid FROM machine_table WHERE machine_id = %s", (body.machine_id,))
        m = cursor.fetchone()
        if not m:
            raise HTTPException(status_code=404, detail="machine not found")
        machine_uuid = m.get("machine_uuid") or (m["machine_uuid"] if "machine_uuid" in m else None)
        if not machine_uuid:
            raise HTTPException(status_code=404, detail="machine not found")

        if body.isusing == 1:
            cursor.execute(
                "SELECT 1 FROM notify_subscriptions WHERE user_id = %s AND machine_uuid = %s",
                (user_id, machine_uuid)
            )
            exists = cursor.fetchone()
            if not exists:
                cursor.execute(
                    "INSERT INTO notify_subscriptions (user_id, machine_uuid) VALUES (%s, %s)",
                    (user_id, machine_uuid)
                )
        else:
            cursor.execute(
                "DELETE FROM notify_subscriptions WHERE user_id = %s AND machine_uuid = %s",
                (user_id, machine_uuid)
            )
        conn.commit()
    return {"message": "notify ok"}

@router.post("/admin/add_device")
async def admin_add_device(body: AdminAddDeviceRequest, authorization: str | None = Header(None)):
    # Admin-only: add device to a room
    token = _resolve_token(authorization, getattr(body, "access_token", None))
    try:
        user = get_current_user(token)
    except Exception:
        raise HTTPException(status_code=401, detail="invalid token")
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="forbidden")

    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        # Derive room_name from room_table or fallback
        cursor.execute("SELECT room_name FROM room_table WHERE room_id = %s LIMIT 1", (body.room_id,))
        r = cursor.fetchone()
        room_name = (r.get("room_name") if r else None) or f"Room {body.room_id}"
        # Insert with provided machine_id
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO machine_table (machine_id, machine_name, room_id, room_name, battery_capacity, battery, status, last_update, timestamp)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (body.machine_id, body.machine_name, body.room_id, room_name, 0, 0, "IDLE", int(time.time()), int(time.time()))
        )
        conn.commit()
    return {"message": "admin add ok"}

@router.post("/admin/add_room", response_model=AdminAddRoomResponse)
async def admin_add_room(body: AdminAddRoomRequest, authorization: str | None = Header(None)):
    # Admin-only: create a new room_id with given room_name, return room_id
    token = _resolve_token(authorization, getattr(body, "access_token", None))
    try:
        user = get_current_user(token)
    except Exception:
        raise HTTPException(status_code=401, detail="invalid token")
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="forbidden")

    with get_db_connection() as conn:
        cur = conn.cursor()
        # 1) Create room
        cur.execute("INSERT INTO room_table (room_name) VALUES (%s)", (body.room_name,))
        new_id = cur.lastrowid
        # 2) Subscribe admin(user_id) to this room for association
        try:
            cur.execute("INSERT INTO room_subscriptions (user_id, room_id) VALUES (%s, %s)", (int(user["user_id"]), int(new_id)))
        except Exception:
            # Ignore duplicate or fk errors silently
            pass
        conn.commit()
    return {"room_id": int(new_id)}

@router.post("/set_fcm_token")
async def set_fcm_token(body: SetFcmTokenRequest, authorization: str | None = Header(None)):
    token = _resolve_token(authorization, getattr(body, "access_token", None))
    try:
        user = get_current_user(token)
    except Exception:
        raise HTTPException(status_code=401, detail="invalid token")

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE user_table SET fcm_token = %s WHERE user_id = %s", (body.fcm_token, int(user["user_id"])) )
        conn.commit()
    return {"message": "set fcm token ok"}


@router.get("/rooms")
async def get_rooms(
    authorization: str | None = Header(None),
    access_token: str | None = Query(None)
):
    token = _resolve_token(authorization, access_token)
    try:
        user = get_current_user(token)
    except Exception:
        raise HTTPException(status_code=401, detail="invalid token")

    user_id = int(user["user_id"])
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT rt.room_id, rt.room_name
            FROM room_table rt
            JOIN room_subscriptions rs ON rs.room_id = rt.room_id
            WHERE rs.user_id = %s
            ORDER BY rt.room_id
            """,
            (user_id,)
        )
        rows = cursor.fetchall() or []
    rooms = [{"room_id": int(r["room_id"]), "room_name": (r.get("room_name") or f"Room {r['room_id']}") } for r in rows]
    return {"rooms": rooms}

@router.get("/debug")
async def debug_dump():
    """Return all database tables and their rows dynamically as JSON.
    WARNING: Intended for debugging; exposes entire DB contents.
    """
    with get_db_connection() as conn:
        result = {}
        cur = conn.cursor()
        try:
            cur.execute("SHOW TABLES")
            tables = [row[0] for row in (cur.fetchall() or [])]
        except Exception as e:
            return {"error": f"failed to list tables: {e}"}

        for t in tables:
            c = conn.cursor(dictionary=True)
            try:
                c.execute(f"SELECT * FROM `{t}`")
                rows = c.fetchall() or []
                result[t] = rows
            except Exception as e:
                result[t] = [{"_error": str(e)}]
    return result

@router.websocket("/status_update")
async def status_update(websocket: WebSocket, token: str = Query(...)):
    # JWT 인증
    try:
        payload = decode_jwt(token)
        user_id = int(payload.get("sub"))
        # DB의 현재 토큰과 일치 확인
        with get_db_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT user_token FROM user_table WHERE user_id = %s", (user_id,))
            row = cursor.fetchone()
            if not row or row.get("user_token") != token:
                await websocket.close(code=1008)
                return
    except Exception:
        await websocket.close(code=1008)
        return

    await manager.connect(user_id, websocket)
    try:
        while True:
            # 클라이언트 keep-alive 수신(내용은 사용하지 않음)
            await websocket.receive_text()
    except Exception:
        pass
    finally:
        manager.disconnect(user_id, websocket)
