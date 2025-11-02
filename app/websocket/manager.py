from typing import Dict, List
import json
from fastapi import WebSocket
from loguru import logger

from app.database import get_db_connection
from app.notifications.fcm import send_to_tokens


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
        if not conns:
            self.active.pop(user_id, None)
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


manager = ConnectionManager()


async def broadcast_room_status(machine_id: int, status: str):
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT room_id, room_name, machine_name FROM machine_table WHERE machine_id = %s",
            (machine_id,)
        )
        m = cursor.fetchone()
        if not m:
            return
        room_id = m["room_id"]
        cursor.execute(
            "SELECT DISTINCT user_id FROM room_subscriptions WHERE room_id = %s",
            (room_id,)
        )
        users = cursor.fetchall() or []
    for u in users:
        await manager.send_to_user(int(u["user_id"]), {
            "type": "room_status",
            "machine_id": machine_id,
            "status": status,
            "room_id": room_id,
            "room_name": m.get("room_name"),
            "machine_name": m.get("machine_name")
        })
    uids = [int(u["user_id"]) for u in users]
    if uids:
        with get_db_connection() as conn:
            cur = conn.cursor()
            placeholders = ",".join(["%s"] * len(uids))
            cur.execute(
                f"SELECT fcm_token FROM user_table WHERE user_id IN ({placeholders}) AND fcm_token IS NOT NULL",
                tuple(uids)
            )
            rows = cur.fetchall() or []
        tokens = [r[0] for r in rows if r and r[0]]
        if tokens:
            title = "세탁기 상태 변경"
            body = f"{m.get('room_name')} {m.get('machine_name')}: {status}"
            data = {
                "machine_id": machine_id,
                "room_id": room_id,
                "status": status,
            }
            send_to_tokens(tokens, title, body, data)


async def broadcast_notify(machine_id: int, status: str):
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT machine_uuid, machine_name, room_id FROM machine_table WHERE machine_id = %s", (machine_id,))
        mu = cursor.fetchone()
        if not mu:
            return
        machine_uuid = mu.get("machine_uuid")
        cursor.execute(
            "SELECT user_id FROM notify_subscriptions WHERE machine_uuid = %s",
            (machine_uuid,)
        )
        users = cursor.fetchall() or []
    for u in users:
        await manager.send_to_user(int(u["user_id"]), {
            "type": "notify",
            "machine_id": machine_id,
            "status": status
        })
    uids = [int(u["user_id"]) for u in users]
    if uids:
        with get_db_connection() as conn:
            cur = conn.cursor()
            placeholders = ",".join(["%s"] * len(uids))
            cur.execute(
                f"SELECT fcm_token FROM user_table WHERE user_id IN ({placeholders}) AND fcm_token IS NOT NULL",
                tuple(uids)
            )
            rows = cur.fetchall() or []
        tokens = [r[0] for r in rows if r and r[0]]
        if tokens:
            title = "세탁기 상태 변경"
            body = f"{mu.get('machine_name')}: {status}"
            data = {
                "machine_id": machine_id,
                "room_id": mu.get("room_id"),
                "status": status,
            }
            send_to_tokens(tokens, title, body, data)
