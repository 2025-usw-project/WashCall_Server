from collections import defaultdict
from datetime import datetime
import time
from statistics import mean

import holidays
import pytz
from fastapi import APIRouter
from fastapi import HTTPException, WebSocket, Query, Header
from fastapi.concurrency import run_in_threadpool
from loguru import logger

from app.auth.security import (
    hash_password, verify_password, issue_jwt, get_current_user, decode_jwt, is_admin
)
from app.database import get_db_connection
from app.services.ai_summary import generate_summary
from app.services.kma_weather import fetch_kma_weather
from app.utils.timer import compute_remaining_minutes
from app.web_service.schemas import (
    RegisterRequest, RegisterResponse,
    LoginRequest, LoginResponse,
    LogoutRequest,
    LoadRequest, LoadResponse, MachineItem,
    ReserveRequest, NotifyMeRequest,
    AdminAddDeviceRequest, SetFcmTokenRequest, AdminAddRoomRequest, AdminAddRoomResponse,
    DeviceSubscribeRequest, CongestionResponse,
    SurveyRequest, SurveyResponse,
    StartCourseRequest, StartCourseResponse,
    StatusContext, TimeContext, WeatherContext, TotalsContext, RoomSummary, AlertContext,
    TipResponse,
)
from app.websocket.manager import broadcast_room_status, broadcast_notify
from app.websocket.manager import manager

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
        
        # 유저 생성
        cursor.execute(
            "INSERT INTO user_table (user_username, user_password, user_role, user_snum) VALUES (%s, %s, %s, %s)",
            (body.user_username, hashed, role_int, body.user_snum)
        )
        
        # 새로 생성된 user_id 가져오기
        new_user_id = cursor.lastrowid
        
        # 자동으로 1번 방 구독 추가
        cursor.execute(
            "INSERT INTO room_subscriptions (user_id, room_id) VALUES (%s, %s)",
            (new_user_id, 1)
        )
        
        conn.commit()
    return RegisterResponse(message="register ok")

@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest):
    import time
    
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM user_table WHERE user_snum = %s", (body.user_snum,))
        user = cursor.fetchone()
        
        if not user or not verify_password(body.user_password, user.get("user_password", "")):
            raise HTTPException(status_code=401, detail="invalid credentials")
        
        role_str = role_to_str(user.get("user_role"))
        token = issue_jwt(int(user["user_id"]), role_str)
        
        # 🔥 last_login 시간 기록 (현재 시간)
        current_time = int(time.time())
        
        cursor.execute(
            "UPDATE user_table SET user_token = %s, fcm_token = %s, last_login = %s WHERE user_id = %s",
            (token, body.fcm_token, current_time, user["user_id"]))
        conn.commit()
        
        logger.info(f"✅ 로그인: user_id={user['user_id']}, last_login={current_time}")
        
        return LoginResponse(access_token=token)

@router.post("/logout")
async def logout(body: LogoutRequest, authorization: str | None = Header(None)):
    import time
    
    token = _resolve_token(authorization, getattr(body, "access_token", None))
    
    try:
        user = get_current_user(token)
    except Exception:
        raise HTTPException(status_code=401, detail="invalid token")
    
    # 🔥 로그아웃 시 last_login 시간 기록
    current_time = int(time.time())
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE user_table SET user_token = NULL, last_login = %s WHERE user_id = %s", 
            (current_time, user["user_id"]))
        conn.commit()
    
    logger.info(f"✅ 로그아웃: user_id={user['user_id']}, last_login={current_time}")
    
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

    try:
        payload = decode_jwt(token)
        role_in_jwt = str(payload.get("role", "")).upper()
    except Exception:
        role_in_jwt = ""

    user_id = int(user["user_id"])
    now_ts = int(time.time())

    rows: list[dict] = []
    course_avg_map: dict[str, int] = {}
    notify_set: set[str] = set()
    isreserved = 0
    room_reservation_counts: dict[int, int] = {}
    room_notify_counts: dict[int, int] = {}
    recent_finished_count = 0

    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)

        if role_in_jwt == "ADMIN":
            cursor.execute(
                """
                SELECT m.machine_id,
                       m.machine_uuid,
                       m.room_id,
                       COALESCE(rt.room_name, m.room_name) AS room_name,
                       m.machine_name,
                       m.status,
                       m.machine_type,
                       m.course_name,
                       UNIX_TIMESTAMP(m.first_update) AS first_ts
                FROM machine_table m
                JOIN room_subscriptions rs ON m.room_id = rs.room_id
                LEFT JOIN room_table rt ON m.room_id = rt.room_id
                WHERE rs.user_id = %s
                """,
                (user_id,),
            )
        else:
            cursor.execute(
                """
                SELECT m.machine_id,
                       m.machine_uuid,
                       m.room_id,
                       COALESCE(rt.room_name, m.room_name) AS room_name,
                       m.machine_name,
                       m.status,
                       m.machine_type,
                       m.course_name,
                       UNIX_TIMESTAMP(m.first_update) AS first_ts
                FROM machine_table m
                JOIN room_subscriptions rs ON m.room_id = rs.room_id
                LEFT JOIN room_table rt ON m.room_id = rt.room_id
                WHERE rs.user_id = %s
                """,
                (user_id,),
            )
        rows = cursor.fetchall() or []

        course_names = {row.get("course_name") for row in rows if row.get("course_name")}
        if course_names:
            placeholders = ",".join(["%s"] * len(course_names))
            cursor.execute(
                f"SELECT course_name, avg_time FROM time_table WHERE course_name IN ({placeholders})",
                tuple(course_names),
            )
            for course_row in cursor.fetchall() or []:
                course_name = course_row.get("course_name")
                avg_time_val = course_row.get("avg_time")
                if course_name and avg_time_val is not None:
                    try:
                        course_avg_map[course_name] = int(avg_time_val)
                    except Exception:
                        logger.warning(
                            "load: avg_time parsing failed for course=%s value=%s",
                            course_name,
                            avg_time_val,
                        )

        cursor.execute(
            "SELECT machine_uuid FROM notify_subscriptions WHERE user_id = %s",
            (user_id,),
        )
        notify_rows = cursor.fetchall() or []
        notify_set = {row["machine_uuid"] for row in notify_rows}

        cursor.execute(
            """
            SELECT MAX(isreserved) as max_reserved
            FROM reservation_table
            WHERE user_id = %s
            """,
            (user_id,),
        )
        reserve_row = cursor.fetchone()
        isreserved = int(reserve_row.get("max_reserved") or 0) if reserve_row else 0

        room_ids = {int(row["room_id"]) for row in rows if row.get("room_id") is not None}
        if room_ids:
            placeholders_rooms = ",".join(["%s"] * len(room_ids))

            cursor.execute(
                f"""
                SELECT room_id, COUNT(*) AS cnt
                FROM reservation_table
                WHERE room_id IN ({placeholders_rooms}) AND isreserved = 1
                GROUP BY room_id
                """,
                tuple(room_ids),
            )
            for rec in cursor.fetchall() or []:
                room_reservation_counts[int(rec.get("room_id"))] = int(rec.get("cnt") or 0)

            cursor.execute(
                f"""
                SELECT m.room_id, COUNT(*) AS cnt
                FROM notify_subscriptions ns
                JOIN machine_table m ON ns.machine_uuid = m.machine_uuid
                WHERE m.room_id IN ({placeholders_rooms})
                GROUP BY m.room_id
                """,
                tuple(room_ids),
            )
            for rec in cursor.fetchall() or []:
                room_notify_counts[int(rec.get("room_id"))] = int(rec.get("cnt") or 0)

            lookback_ts = now_ts - 1800  # 30분 내 FINISHED 장비 수
            params = tuple(room_ids) + ("FINISHED", lookback_ts)
            cursor.execute(
                f"""
                SELECT COUNT(*) AS cnt
                FROM machine_table
                WHERE room_id IN ({placeholders_rooms})
                    AND status = %s
                    AND timestamp >= %s
                """,
                params,
            )
            finished_row = cursor.fetchone()
            recent_finished_count = int(finished_row.get("cnt") or 0) if finished_row else 0

    machines: list[MachineItem] = []
    room_stats: dict[int, dict] = defaultdict(lambda: {
        "room_name": "",
        "total": 0,
        "busy": 0,
        "timers": [],
    })

    busy_statuses = {"WASHING", "SPINNING", "DRYING"}

    for r in rows:
        status = (r.get("status") or "").upper()
        course_name = r.get("course_name")
        first_ts_val = r.get("first_ts")
        first_ts_int = None
        if first_ts_val is not None:
            try:
                first_ts_int = int(first_ts_val)
            except Exception:
                logger.warning("load: invalid first_ts value=%s for machine_id=%s", first_ts_val, r.get("machine_id"))

        timer_val: int | None = None
        if status in busy_statuses and course_name:
            avg_minutes = course_avg_map.get(course_name)
            timer_val, negative = compute_remaining_minutes(first_ts_int, avg_minutes, now_ts)
            if negative:
                timer_val = None

        machines.append(
            MachineItem(
                machine_id=int(r["machine_id"]),
                room_name=r.get("room_name") or "",
                machine_name=r.get("machine_name") or "",
                status=r.get("status") or "",
                machine_type=r.get("machine_type") or "washer",
                isusing=1 if r.get("machine_uuid") in notify_set else 0,
                timer=timer_val,
            )
        )

        room_id = int(r.get("room_id") or 0)
        stats = room_stats[room_id]
        stats["room_name"] = r.get("room_name") or stats["room_name"]
        stats["total"] += 1
        if status in busy_statuses:
            stats["busy"] += 1
        if timer_val is not None:
            stats["timers"].append(timer_val)

    kst = pytz.timezone("Asia/Seoul")
    now_dt = datetime.now(tz=kst)
    weekday_labels = ["월", "화", "수", "목", "금", "토", "일"]
    weekday_label = weekday_labels[now_dt.weekday()]
    kr_holidays = holidays.KR()
    is_holiday = now_dt.date() in kr_holidays
    is_weekend = now_dt.weekday() >= 5

    time_context = TimeContext(
        iso_timestamp=now_dt.isoformat(),
        weekday=weekday_label,
        hour=now_dt.hour,
        is_holiday=is_holiday,
        is_weekend=is_weekend,
    )

    weather_raw = await run_in_threadpool(fetch_kma_weather, now_dt)
    weather_context = WeatherContext(**weather_raw) if weather_raw else None

    room_summaries: list[RoomSummary] = []
    for room_id, stats in room_stats.items():
        total = stats["total"]
        busy = stats["busy"]
        idle = max(total - busy, 0)
        timers = stats["timers"]
        avg_remaining = mean(timers) if timers else None
        max_remaining = max(timers) if timers else None
        reservation_count = room_reservation_counts.get(room_id, 0)
        notify_count = room_notify_counts.get(room_id, 0)

        estimated_wait: float | None = None
        if max_remaining is not None:
            per_cycle = avg_remaining if avg_remaining is not None else max_remaining
            estimated_wait = max_remaining + reservation_count * (per_cycle or 0)

        room_summaries.append(
            RoomSummary(
                room_id=room_id,
                room_name=stats["room_name"],
                machines_total=total,
                machines_busy=busy,
                machines_idle=idle,
                avg_remaining_minutes=avg_remaining,
                max_remaining_minutes=max_remaining,
                reservation_count=reservation_count,
                notify_count=notify_count,
                estimated_wait_minutes=estimated_wait,
            )
        )

    totals = TotalsContext(
        machines_total=sum(stats["total"] for stats in room_stats.values()),
        machines_busy=sum(stats["busy"] for stats in room_stats.values()),
        machines_idle=sum(max(stats["total"] - stats["busy"], 0) for stats in room_stats.values()),
        reservations_total=sum(room_reservation_counts.values()),
        notify_total=sum(room_notify_counts.values()),
    )

    alerts = AlertContext(
        recent_finished_count=recent_finished_count,
        active_notify_subscriptions=sum(room_notify_counts.values()),
    )

    status_context = StatusContext(
        time=time_context,
        weather=weather_context,
        totals=totals,
        rooms=room_summaries,
        alerts=alerts,
    )

    return LoadResponse(
        isreserved=isreserved,
        machine_list=machines,
        status_context=status_context,
    )


@router.get("/tip", response_model=TipResponse)
async def get_tip(authorization: str | None = Header(None)):
    """Generate AI-powered laundry room status tip."""
    token = _resolve_token(authorization, None)
    try:
        user = get_current_user(token)
    except Exception:
        raise HTTPException(status_code=401, detail="invalid token")

    user_id = int(user["user_id"])
    now_ts = int(time.time())
    now_dt = datetime.now(tz=pytz.timezone("Asia/Seoul"))
    kr_holidays = holidays.country_holidays("KR")

    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        
        # Fetch machines for user's subscribed rooms
        cursor.execute(
            """
            SELECT m.machine_id, m.room_id, m.status, m.course_name,
                   COALESCE(rt.room_name, m.room_name) AS room_name,
                   UNIX_TIMESTAMP(m.first_update) AS first_ts
            FROM machine_table m
            JOIN room_subscriptions rs ON m.room_id = rs.room_id
            LEFT JOIN room_table rt ON m.room_id = rt.room_id
            WHERE rs.user_id = %s
            """,
            (user_id,)
        )
        machines = cursor.fetchall() or []

        # Fetch course averages
        course_names = {m.get("course_name") for m in machines if m.get("course_name")}
        course_avg_map = {}
        if course_names:
            placeholders = ",".join(["%s"] * len(course_names))
            cursor.execute(
                f"SELECT course_name, avg_time FROM time_table WHERE course_name IN ({placeholders})",
                tuple(course_names),
            )
            for row in cursor.fetchall() or []:
                cn = row.get("course_name")
                avg = row.get("avg_time")
                if cn and avg is not None:
                    try:
                        course_avg_map[cn] = int(avg)
                    except Exception:
                        pass

        # Aggregate by room
        room_stats = defaultdict(lambda: {"total": 0, "busy": 0, "room_name": ""})
        room_remaining_times = defaultdict(list)
        
        for m in machines:
            room_id = m.get("room_id")
            room_name = m.get("room_name", "")
            status = (m.get("status") or "").upper()
            
            room_stats[room_id]["room_name"] = room_name
            room_stats[room_id]["total"] += 1
            
            if status in {"WASHING", "SPINNING"}:
                room_stats[room_id]["busy"] += 1
                
                course_name = m.get("course_name")
                first_ts = m.get("first_ts")
                if course_name and first_ts is not None:
                    avg_minutes = course_avg_map.get(course_name)
                    if avg_minutes:
                        try:
                            remaining, negative = compute_remaining_minutes(int(first_ts), avg_minutes, now_ts)
                            if not negative and remaining is not None:
                                room_remaining_times[room_id].append(remaining)
                        except Exception:
                            pass

        # Fetch reservations per room
        cursor.execute(
            """
            SELECT room_id, COUNT(*) as cnt
            FROM reservation_table
            WHERE isreserved = 1
            GROUP BY room_id
            """
        )
        room_reservation_counts = {row["room_id"]: row["cnt"] for row in cursor.fetchall() or []}

        # Fetch notify subscriptions per room
        cursor.execute(
            """
            SELECT m.room_id, COUNT(*) as cnt
            FROM notify_subscriptions ns
            JOIN machine_table m ON ns.machine_uuid = m.machine_uuid
            GROUP BY m.room_id
            """
        )
        room_notify_counts = {row["room_id"]: row["cnt"] for row in cursor.fetchall() or []}

        # Count recent finished machines (last 30 minutes)
        cursor.execute(
            """
            SELECT COUNT(*) as cnt FROM machine_table
            WHERE status = 'FINISHED' AND UNIX_TIMESTAMP(first_update) >= %s
            """,
            (now_ts - 1800,)
        )
        row = cursor.fetchone()
        recent_finished_count = row.get("cnt", 0) if row else 0

    # Build time context
    weekday_kr = ["월", "화", "수", "목", "금", "토", "일"][now_dt.weekday()]
    hour_24 = now_dt.hour
    is_holiday = now_dt.date() in kr_holidays
    holiday_name = kr_holidays.get(now_dt.date()) if is_holiday else None
    
    time_context = TimeContext(
        weekday_kr=weekday_kr,
        hour_24h=hour_24,
        hour_12h=hour_24 if hour_24 <= 12 else hour_24 - 12,
        period_kr="오전" if hour_24 < 12 else "오후",
        is_holiday=is_holiday,
        holiday_name=holiday_name,
    )

    # Fetch weather
    weather_raw = await run_in_threadpool(fetch_kma_weather, now_dt)
    weather_context = WeatherContext(**weather_raw) if weather_raw else None

    # Build room summaries
    room_summaries = []
    for room_id, stats in room_stats.items():
        total = stats["total"]
        busy = stats["busy"]
        idle = max(total - busy, 0)
        reservation_count = room_reservation_counts.get(room_id, 0)
        notify_count = room_notify_counts.get(room_id, 0)
        
        remaining_list = room_remaining_times.get(room_id, [])
        avg_remaining = mean(remaining_list) if remaining_list else None
        max_remaining = max(remaining_list) if remaining_list else None
        
        per_cycle = None
        if stats.get("room_name"):
            for m in machines:
                if m.get("room_id") == room_id and m.get("course_name"):
                    per_cycle = course_avg_map.get(m["course_name"])
                    if per_cycle:
                        break
        
        estimated_wait = None
        if max_remaining is not None:
            estimated_wait = max_remaining + reservation_count * (per_cycle or 0)

        room_summaries.append(
            RoomSummary(
                room_id=room_id,
                room_name=stats["room_name"],
                machines_total=total,
                machines_busy=busy,
                machines_idle=idle,
                avg_remaining_minutes=avg_remaining,
                max_remaining_minutes=max_remaining,
                reservation_count=reservation_count,
                notify_count=notify_count,
                estimated_wait_minutes=estimated_wait,
            )
        )

    totals = TotalsContext(
        machines_total=sum(stats["total"] for stats in room_stats.values()),
        machines_busy=sum(stats["busy"] for stats in room_stats.values()),
        machines_idle=sum(max(stats["total"] - stats["busy"], 0) for stats in room_stats.values()),
        reservations_total=sum(room_reservation_counts.values()),
        notify_total=sum(room_notify_counts.values()),
    )

    alerts = AlertContext(
        recent_finished_count=recent_finished_count,
        active_notify_subscriptions=sum(room_notify_counts.values()),
    )

    status_context = StatusContext(
        time=time_context,
        weather=weather_context,
        totals=totals,
        rooms=room_summaries,
        alerts=alerts,
    )

    # Generate AI tip
    tip_message = None
    try:
        status_dict = status_context.model_dump()
        tip_message = await run_in_threadpool(generate_summary, status_dict)
    except Exception as exc:
        logger.warning(f"AI tip generation failed: {exc}")
    
    if not tip_message:
        tip_message = "세탁실 정보를 불러올 수 없습니다."
    
    return TipResponse(tip_message=tip_message)


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


@router.post("/start_course", response_model=StartCourseResponse)
async def start_course(body: StartCourseRequest, authorization: str | None = Header(None)):
    """세탁 코스 시작 - course_name과 first_update만 설정 (상태는 /update로만 변경)"""

    token = _resolve_token(authorization, None)
    try:
        get_current_user(token)
    except Exception:
        raise HTTPException(status_code=401, detail="invalid token")

    now_ts = int(time.time())
    timer_minutes: int | None = None
    negative_time = False

    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)

        # 1. machine_id 존재 확인 + first_update 조회
        cursor.execute(
            """
            SELECT machine_id,
                   status,
                   UNIX_TIMESTAMP(first_update) AS first_ts
            FROM machine_table
            WHERE machine_id = %s
            """,
            (body.machine_id,)
        )
        machine = cursor.fetchone()

        if not machine:
            raise HTTPException(status_code=404, detail="machine not found")

        first_ts = machine.get("first_ts")

        # 2. time_table에서 평균 시간 조회 (분 단위)
        cursor.execute(
            "SELECT avg_time FROM time_table WHERE course_name = %s",
            (body.course_name,)
        )
        time_row = cursor.fetchone()
        avg_minutes: int | None = None
        if time_row and time_row.get("avg_time") is not None:
            try:
                avg_minutes = int(time_row.get("avg_time"))
            except Exception:
                logger.warning(
                    "start_course: avg_time parsing failed for course=%s value=%s",
                    body.course_name,
                    time_row.get("avg_time"),
                )

        timer_minutes, negative_time = compute_remaining_minutes(first_ts, avg_minutes, now_ts)
        if negative_time:
            timer_minutes = None

        # 3. machine_table 업데이트 (course_name과 first_update만 설정, 상태는 변경하지 않음)
        set_clauses = [
            "timestamp = %s",
            "first_update = FROM_UNIXTIME(%s)",
        ]
        params: list = [
            now_ts,
            now_ts,
        ]

        if not negative_time:
            set_clauses.append("course_name = %s")
            params.append(body.course_name)
        else:
            set_clauses.append("course_name = NULL")

        update_sql = f"UPDATE machine_table SET {', '.join(set_clauses)} WHERE machine_id = %s"
        params.append(body.machine_id)
        cursor.execute(update_sql, tuple(params))

        conn.commit()

        # ✅ 4. WebSocket 브로드캐스트 (현재 상태로)
        current_status = machine.get("status", "IDLE")
        try:
            await broadcast_room_status(body.machine_id, current_status)
            await broadcast_notify(body.machine_id, current_status)
        except Exception as e:
            logger.error(f"WebSocket 브로드캐스트 실패: {str(e)}")

        logger.info(
            "✅ %s 세탁 시작: %s (avg=%s분, timer=%s분)",
            body.machine_id,
            body.course_name,
            avg_minutes,
            timer_minutes,
        )

        return StartCourseResponse(
            timer=timer_minutes,
        )


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
    rooms = [{"room_id": int(r["room_id"]), "room_name": (r.get("room_name") or f"Room {r['room_id']}") } for r in rows ]
    return {"rooms": rooms}


@router.get("/statistics/congestion", response_model=CongestionResponse)
async def get_congestion_statistics(authorization: str | None = Header(None)):
    """요일/시간대별 혼잡도(사용 수) 집계 반환.

    응답 형식 예시:
    {
      "월": [0..23],
      "화": [0..23],
      ...
      "일": [0..23]
    }
    """
    # 인증 (헤더 Bearer 토큰 필수)
    token = _resolve_token(authorization, None)
    try:
        get_current_user(token)
    except Exception:
        raise HTTPException(status_code=401, detail="invalid token")

    days = ["월", "화", "수", "목", "금", "토", "일"]
    result = {d: [0] * 24 for d in days}

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT busy_day, busy_time, busy_count FROM busy_table")
            rows = cursor.fetchall() or []

            for row in rows:
                day = str(row.get("busy_day") or "")
                hour = row.get("busy_time")
                count = row.get("busy_count")
                try:
                    hour_int = int(hour)
                except Exception:
                    continue
                if day in result and 0 <= hour_int <= 23:
                    result[day][hour_int] = int(count or 0)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"failed to load congestion: {str(e)}")

    return result


@router.post("/survey", response_model=SurveyResponse)
async def submit_survey(body: SurveyRequest, authorization: str | None = Header(None)):
    """설문조사 제출
    
    만족도(1-5)와 건의사항을 받아서 데이터베이스에 저장합니다.
    """
    # 인증 (헤더 Bearer 토큰 필수)
    token = _resolve_token(authorization, None)
    try:
        get_current_user(token)
    except Exception:
        raise HTTPException(status_code=401, detail="invalid token")

    # 만족도 범위 검증 (Pydantic에서도 하지만 이중 체크)
    if body.satisfaction < 1 or body.satisfaction > 5:
        raise HTTPException(status_code=400, detail="satisfaction must be between 1 and 5")

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO survey_table (satisfaction, suggestion) VALUES (%s, %s)",
                (body.satisfaction, body.suggestion)
            )
            conn.commit()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"failed to save survey: {str(e)}")

    return SurveyResponse(message="survey ok")


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

    logger.info("WS handshake success user_id={}", user_id)
    await manager.connect(user_id, websocket)
    try:
        while True:
            # 클라이언트 keep-alive 수신(내용은 사용하지 않음)
            msg = await websocket.receive_text()
            safe = msg if len(msg) <= 500 else msg[:500] + "..."
            logger.info("WS recv user_id={} payload={}", user_id, safe)
    except Exception:
        pass
    finally:
        manager.disconnect(user_id, websocket)
        logger.info("WS closed user_id={}", user_id)
