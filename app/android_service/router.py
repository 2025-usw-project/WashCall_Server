from fastapi import APIRouter
from fastapi import HTTPException, WebSocket, Query
import time
from app.android_service.schemas import (
    RegisterRequest, RegisterResponse,
    LoginRequest, LoginResponse,
    LogoutRequest,
    LoadRequest, LoadResponse, MachineItem,
    ReserveRequest, NotifyMeRequest,
    AdminAddDeviceRequest, SetFcmTokenRequest, AdminAddRoomRequest, AdminMachinesRequest, AdminAddRoomResponse
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
        cursor.execute("UPDATE user_table SET user_token = %s WHERE user_id = %s", (token, user["user_id"]))
        conn.commit()
    return LoginResponse(access_token=token)

@router.post("/logout")
async def logout(body: LogoutRequest):
    try:
        user = get_current_user(body.access_token)
    except Exception:
        raise HTTPException(status_code=401, detail="invalid token")

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE user_table SET user_token = NULL WHERE user_id = %s", (user["user_id"],))
        conn.commit()
    return {"message": "logout ok"}


@router.get("/device_subscribe")
async def device_subscribe_get(room_name: str = Query(...), user_snum: str = Query(...)):
    try:
        snum = int(user_snum)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid user_snum")

    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        # Resolve user_id from user_snum
        cursor.execute("SELECT user_id FROM user_table WHERE user_snum = %s", (snum,))
        u = cursor.fetchone()
        if not u:
            raise HTTPException(status_code=404, detail="user not found")
        user_id = int(u["user_id"])

        # Resolve room_id from room_name
        cursor.execute("SELECT room_id FROM machine_table WHERE room_name = %s LIMIT 1", (room_name,))
        r = cursor.fetchone()
        if not r:
            raise HTTPException(status_code=404, detail="room not found")
        room_id = int(r.get("room_id"))

        # Insert subscription if not exists
        c2 = conn.cursor()
        c2.execute(
            "SELECT 1 FROM room_subscriptions WHERE user_id = %s AND room_id = %s",
            (user_id, room_id)
        )
        exists = c2.fetchone()
        if not exists:
            c2.execute(
                "INSERT INTO room_subscriptions (user_id, room_id) VALUES (%s, %s)",
                (user_id, room_id)
            )
        conn.commit()
    return {"message": "subscribe ok"}

@router.post("/load", response_model=LoadResponse)
async def load(body: LoadRequest):
    try:
        user = get_current_user(body.access_token)
    except Exception:
        raise HTTPException(status_code=401, detail="invalid token")

    user_id = int(user["user_id"])
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT m.machine_id, m.room_name, m.machine_name, m.status
            FROM machine_table m
            JOIN room_subscriptions rs ON m.room_id = rs.room_id
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
async def reserve(body: ReserveRequest):
    if body.isreserved not in (0, 1):
        raise HTTPException(status_code=400, detail="isreserved must be 0 or 1")
    try:
        user = get_current_user(body.access_token)
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
        conn.commit()
    return {"message": "reserve ok"}

@router.post("/notify_me")
async def notify_me(body: NotifyMeRequest):
    try:
        user = get_current_user(body.access_token)
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
        conn.commit()
    return {"message": "notify ok"}

@router.post("/notify_me_off")
async def notify_me_off(body: NotifyMeRequest):
    try:
        user = get_current_user(body.access_token)
    except Exception:
        raise HTTPException(status_code=401, detail="invalid token")

    user_id = int(user["user_id"])
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT machine_uuid FROM machine_table WHERE machine_id = %s", (body.machine_id,))
        m = cursor.fetchone()
        if not m:
            raise HTTPException(status_code=404, detail="machine not found")
        machine_uuid = m.get("machine_uuid")
        cursor.execute(
            "DELETE FROM notify_subscriptions WHERE user_id = %s AND machine_uuid = %s",
            (user_id, machine_uuid)
        )
        conn.commit()
    return {"message": "notify off ok"}

@router.post("/admin/machines")
async def admin_machines(body: AdminMachinesRequest):
    # Admin-only: list machines in a room
    try:
        user = get_current_user(body.access_token)
    except Exception:
        raise HTTPException(status_code=401, detail="invalid token")
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="forbidden")

    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT machine_id, machine_name, status FROM machine_table WHERE room_id = %s AND machine_id IS NOT NULL",
            (body.room_id,)
        )
        rows = cursor.fetchall() or []
    machine_list = [
        {
            "machine_id": int(r.get("machine_id")),
            "machine_name": r.get("machine_name") or "",
            "status": r.get("status") or ""
        } for r in rows
    ]
    return {"machine_list": machine_list}

@router.post("/admin_add_device")
async def admin_add_device(body: AdminAddDeviceRequest):
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        # Derive room_name from existing records or fallback
        cursor.execute("SELECT room_name FROM machine_table WHERE room_id = %s LIMIT 1", (body.room_id,))
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
async def admin_add_room(body: AdminAddRoomRequest):
    # Admin-only: create a new room_id with given room_name, return room_id
    try:
        user = get_current_user(body.access_token)
    except Exception:
        raise HTTPException(status_code=401, detail="invalid token")
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="forbidden")

    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COALESCE(MAX(room_id), 0) + 1 AS next_id FROM machine_table")
        row = cur.fetchone()
        next_id = int(row[0] if not isinstance(row, dict) else row.get("next_id", 1))

        # Insert placeholder row to persist room_name mapping
        cur.execute(
            """
            INSERT INTO machine_table (machine_id, machine_name, room_id, room_name, battery_capacity, battery, status, last_update, timestamp)
            VALUES (NULL, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            ("", next_id, body.room_name, 0, 0, "IDLE", int(time.time()), int(time.time()))
        )
        conn.commit()
    return {"room_id": next_id}

@router.post("/set_fcm_token")
async def set_fcm_token(body: SetFcmTokenRequest):
    try:
        user = get_current_user(body.access_token)
    except Exception:
        raise HTTPException(status_code=401, detail="invalid token")

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE user_table SET fcm_token = %s WHERE user_id = %s", (body.fcm_token, int(user["user_id"])) )
        conn.commit()
    return {"message": "set fcm token ok"}

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
