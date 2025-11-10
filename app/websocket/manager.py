import asyncio
import json
import time
from contextlib import suppress
from typing import Dict, List

from fastapi import WebSocket
from loguru import logger

from app.database import get_db_connection
from app.notifications.fcm import send_to_tokens
from app.utils.timer import compute_remaining_minutes


class ConnectionManager:
    def __init__(self):
        self.active: Dict[int, List[WebSocket]] = {}

    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        self.active.setdefault(user_id, [])
        if websocket not in self.active[user_id]:
            self.active[user_id].append(websocket)
        logger.info("WS connected user_id={} active_conns={}", user_id, len(self.active[user_id]))

    def disconnect(self, user_id: int, websocket: WebSocket):
    
        conns = self.active.get(user_id)
        
        if not conns:
            return
        
        try:
            conns.remove(websocket)
        except ValueError:
            pass
        
        # 🔥 모든 연결이 끊겼을 때 last_login 기록
        if not conns:
            self.active.pop(user_id, None)
            
            # WebSocket 완전히 끊김 = 마지막으로 온라인이었던 시간
            current_time = int(time.time())
            
            try:
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "UPDATE user_table SET last_login = %s WHERE user_id = %s",
                        (current_time, user_id))
                    conn.commit()
                logger.info(f"✅ WebSocket 완전 종료: user_id={user_id}, last_login={current_time}")
            except Exception as e:
                logger.error(f"❌ last_login 업데이트 실패: user_id={user_id}, error={str(e)}", exc_info=True)
        
        logger.info("WS disconnected user_id={}", user_id)

    async def send_to_user(self, user_id: int, data: dict):
        conns = list(self.active.get(user_id, []))
        if not conns:
            return
        text = json.dumps(data)
        safe = text if len(text) <= 1000 else text[:1000] + "..."
        logger.info("WS send user_id={} payload={} targets={}", user_id, safe, len(conns))
        for ws in conns:
            try:
                await ws.send_text(text)
            except Exception:
                # Drop broken connections on send failure
                try:
                    conns.remove(ws)
                except Exception:
                    pass
                logger.warning("WS send failed and connection dropped user_id={}", user_id)

    async def broadcast(self, data: dict):
        """Send the same payload to every active WebSocket connection."""
        for user_id in list(self.active.keys()):
            await self.send_to_user(user_id, data)

    def has_connections(self) -> bool:
        return any(self.active.values())


manager = ConnectionManager()


TIMER_SYNC_INTERVAL_SECONDS = 60
_timer_sync_task: asyncio.Task | None = None


async def broadcast_room_status(machine_id: int, status: str):
    """
    방 구독자에게 WebSocket + FCM 알림 전송
    ❗️ FINISHED 상태일 때만 FCM 푸시 알림 전송 (알림 스팸 방지)
    """
    now_ts = int(time.time())

    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT room_id, room_name, machine_name, course_name, UNIX_TIMESTAMP(first_update) AS first_ts FROM machine_table WHERE machine_id = %s",
            (machine_id,)
        )
        m = cursor.fetchone()
        if not m:
            logger.warning(f"broadcast_room_status: machine_id={machine_id} not found")
            return
        
        room_id = m["room_id"]
        room_name = m.get("room_name", "세탁실")
        machine_name = m.get("machine_name", "세탁기")
        course_name = m.get("course_name")
        first_ts = m.get("first_ts")
        avg_minutes = None

        if course_name:
            cursor.execute(
                "SELECT avg_time FROM time_table WHERE course_name = %s",
                (course_name,)
            )
            row_avg = cursor.fetchone()
            if row_avg and row_avg.get("avg_time") is not None:
                try:
                    avg_minutes = int(row_avg.get("avg_time"))
                except Exception:
                    logger.warning("broadcast_room_status: avg_time parse failed course=%s value=%s", course_name, row_avg.get("avg_time"))

        timer_minutes, negative = compute_remaining_minutes(first_ts, avg_minutes, now_ts)
        if negative:
            timer_minutes = None
        
        cursor.execute(
            "SELECT DISTINCT user_id FROM room_subscriptions WHERE room_id = %s",
            (room_id,)
        )
        users = cursor.fetchall() or []
    
    # 1. WebSocket으로 실시간 전송 (모든 상태)
    for u in users:
        await manager.send_to_user(int(u["user_id"]), {
            "type": "room_status",
            "machine_id": machine_id,
            "status": status,
            "room_id": room_id,
            "room_name": room_name,
            "machine_name": machine_name,
            "timer": timer_minutes,
        })
    
    # 2. FCM 푸시 알림은 FINISHED 상태일 때만
    if status != "FINISHED":
        logger.info(f"FCM 스킵 (room): machine_id={machine_id}, status={status}")
        return
    
    uids = [int(u["user_id"]) for u in users]
    if not uids:
        logger.info(f"FCM 스킵 (room): machine_id={machine_id}, 구독자 없음")
        return
    
    # 3. FCM 토큰 조회
    with get_db_connection() as conn:
        cur = conn.cursor()
        placeholders = ",".join(["%s"] * len(uids))
        cur.execute(
            f"SELECT fcm_token FROM user_table WHERE user_id IN ({placeholders}) AND fcm_token IS NOT NULL",
            tuple(uids)
        )
        rows = cur.fetchall() or []
    
    tokens = [r[0] for r in rows if r and r[0]]
    if not tokens:
        logger.info(f"FCM 스킵 (room): machine_id={machine_id}, 유효한 토큰 없음")
        return
    
    # 4. FCM 전송 (FINISHED 상태만)
    try:
        title = f"🎉 {room_name} 세탁 완료!"
        body = f"{machine_name}의 세탁이 완료되었습니다."
        data = {
            "machine_id": str(machine_id),
            "room_id": str(room_id),
            "status": status,
            "click_action": "index.html",
            "type": "wash_complete"
        }
        
        logger.info(f"📤 FCM 전송 (room): machine_id={machine_id}, 대상={len(tokens)}명")
        result = send_to_tokens(tokens, title, body, data)
        logger.info(f"✅ FCM 전송 완료 (room): {result}")
        
    except Exception as e:
        logger.error(f"❌ FCM 전송 실패 (room): machine_id={machine_id}, error={str(e)}", exc_info=True)


async def broadcast_notify(machine_id: int, status: str):
    """
    개별 세탁기 구독자에게 WebSocket + FCM 알림 전송
    ❗️ FINISHED 상태일 때만 FCM 푸시 알림 전송 (알림 스팸 방지)
    ❗️ FINISHED 후 알림 자동 해제
    """
    now_ts = int(time.time())

    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT machine_uuid, machine_name, room_id, course_name, UNIX_TIMESTAMP(first_update) AS first_ts FROM machine_table WHERE machine_id = %s",
            (machine_id,)
        )
        mu = cursor.fetchone()
        if not mu:
            logger.warning(f"broadcast_notify: machine_id={machine_id} not found")
            return
        
        machine_uuid = mu.get("machine_uuid")
        machine_name = mu.get("machine_name", "세탁기")
        course_name = mu.get("course_name")
        first_ts = mu.get("first_ts")
        avg_minutes = None

        if course_name:
            cursor.execute(
                "SELECT avg_time FROM time_table WHERE course_name = %s",
                (course_name,)
            )
            avg_row = cursor.fetchone()
            if avg_row and avg_row.get("avg_time") is not None:
                try:
                    avg_minutes = int(avg_row.get("avg_time"))
                except Exception:
                    logger.warning("broadcast_notify: avg_time parse failed course=%s value=%s", course_name, avg_row.get("avg_time"))

        timer_minutes, negative = compute_remaining_minutes(first_ts, avg_minutes, now_ts)
        if negative:
            timer_minutes = None
        
        cursor.execute(
            "SELECT user_id FROM notify_subscriptions WHERE machine_uuid = %s",
            (machine_uuid,)
        )
        users = cursor.fetchall() or []
    
    # 1. WebSocket으로 실시간 전송 (모든 상태)
    for u in users:
        await manager.send_to_user(int(u["user_id"]), {
            "type": "notify",
            "machine_id": machine_id,
            "status": status,
            "timer": timer_minutes,
        })
    
    # 2. FCM 푸시 알림은 FINISHED 상태일 때만
    if status != "FINISHED":
        logger.info(f"FCM 스킵: machine_id={machine_id}, status={status} (FINISHED 아님)")
        return
    
    uids = [int(u["user_id"]) for u in users]
    if not uids:
        logger.info(f"FCM 스킵: machine_id={machine_id}, 구독자 없음")
        return
    
    # 3. FCM 토큰 조회
    with get_db_connection() as conn:
        cur = conn.cursor()
        placeholders = ",".join(["%s"] * len(uids))
        cur.execute(
            f"SELECT fcm_token FROM user_table WHERE user_id IN ({placeholders}) AND fcm_token IS NOT NULL",
            tuple(uids)
        )
        rows = cur.fetchall() or []
    
    tokens = [r[0] for r in rows if r and r[0]]
    if not tokens:
        logger.info(f"FCM 스킵: machine_id={machine_id}, 유효한 토큰 없음")
        return
    
    # 4. FCM 전송 (백그라운드 알림)
    try:
        title = "🎉 세탁 완료!"
        body = f"{machine_name}의 세탁이 완료되었습니다. 빨래를 꺼내주세요!"
        data = {
            "machine_id": str(machine_id),
            "room_id": str(mu.get("room_id")),
            "status": status,
            "click_action": "index.html",
            "type": "wash_complete"
        }
        
        logger.info(f"📤 FCM 전송 시작: machine_id={machine_id}, 대상={len(tokens)}명")
        result = send_to_tokens(tokens, title, body, data)
        logger.info(f"✅ FCM 전송 완료: {result}")
        
    except Exception as e:
        logger.error(f"❌ FCM 전송 실패: machine_id={machine_id}, error={str(e)}", exc_info=True)
    
    # 5. 알림 자동 해제 (FINISHED 후 구독 해제)
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM notify_subscriptions WHERE machine_uuid = %s",
                (machine_uuid,)
            )
            deleted_count = cur.rowcount
            conn.commit()
            
            if deleted_count > 0:
                logger.info(f"🔕 알림 자동 해제 완료: machine_uuid={machine_uuid}, 해제된 구독={deleted_count}개")
            else:
                logger.info(f"알림 해제 스킵: machine_uuid={machine_uuid}, 구독 없음")
                
    except Exception as e:
        logger.error(f"❌ 알림 자동 해제 실패: machine_uuid={machine_uuid}, error={str(e)}", exc_info=True)


async def _gather_machine_timers(now_ts: int) -> list[dict]:
    """Fetch all machines with their remaining timers."""
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT machine_id,
                   status,
                   room_id,
                   room_name,
                   course_name,
                   UNIX_TIMESTAMP(first_update) AS first_ts
            FROM machine_table
            """
        )
        machines = cursor.fetchall() or []

        course_names = {row.get("course_name") for row in machines if row.get("course_name")}
        course_avg_map: Dict[str, int] = {}
        if course_names:
            placeholders = ",".join(["%s"] * len(course_names))
            cursor.execute(
                f"SELECT course_name, avg_time FROM time_table WHERE course_name IN ({placeholders})",
                tuple(course_names),
            )
            for course_row in cursor.fetchall() or []:
                cname = course_row.get("course_name")
                avg_time = course_row.get("avg_time")
                if cname and avg_time is not None:
                    try:
                        course_avg_map[cname] = int(avg_time)
                    except Exception:
                        logger.warning(
                            "timer_sync: avg_time parsing failed for course=%s value=%s",
                            cname,
                            avg_time,
                        )

    payloads: list[dict] = []
    for row in machines:
        status = (row.get("status") or "").upper()
        course_name = row.get("course_name")
        timer_val: int | None = None
        if status in {"WASHING", "SPINNING"} and course_name:
            avg_minutes = course_avg_map.get(course_name)
            first_ts = row.get("first_ts")
            timer_val, negative = compute_remaining_minutes(first_ts, avg_minutes, now_ts)
            if negative:
                timer_val = None

        payloads.append(
            {
                "machine_id": int(row["machine_id"]),
                "room_id": row.get("room_id"),
                "room_name": row.get("room_name"),
                "status": status,
                "timer": timer_val,
            }
        )

    return payloads


async def broadcast_timer_snapshot():
    if not manager.has_connections():
        return

    now_ts = int(time.time())
    machines = await _gather_machine_timers(now_ts)
    if not machines:
        return

    await manager.broadcast(
        {
            "type": "timer_sync",
            "timestamp": now_ts,
            "machines": machines,
        }
    )


async def _timer_sync_loop():
    logger.info("Timer sync loop started interval=%ss", TIMER_SYNC_INTERVAL_SECONDS)
    try:
        while True:
            try:
                await broadcast_timer_snapshot()
            except Exception:
                logger.exception("timer_sync_loop: iteration failed")
            await asyncio.sleep(TIMER_SYNC_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        logger.info("Timer sync loop cancelled")
        raise


async def start_timer_sync_loop():
    global _timer_sync_task
    if TIMER_SYNC_INTERVAL_SECONDS <= 0:
        logger.warning("Timer sync loop disabled (interval <= 0)")
        return
    if _timer_sync_task and not _timer_sync_task.done():
        return
    _timer_sync_task = asyncio.create_task(_timer_sync_loop())


async def stop_timer_sync_loop():
    global _timer_sync_task
    if not _timer_sync_task:
        return
    _timer_sync_task.cancel()
    with suppress(asyncio.CancelledError):
        await _timer_sync_task
    _timer_sync_task = None
