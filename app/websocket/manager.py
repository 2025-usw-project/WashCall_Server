from typing import Dict, List
import json
from fastapi import WebSocket

from app.database import get_db_connection


class ConnectionManager:
    def __init__(self):
        self.active: Dict[int, List[WebSocket]] = {}

    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        self.active.setdefault(user_id, [])
        if websocket not in self.active[user_id]:
            self.active[user_id].append(websocket)

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

    async def send_to_user(self, user_id: int, data: dict):
        conns = list(self.active.get(user_id, []))
        if not conns:
            return
        text = json.dumps(data)
        for ws in conns:
            try:
                await ws.send_text(text)
            except Exception:
                # Drop broken connections on send failure
                try:
                    conns.remove(ws)
                except Exception:
                    pass


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


async def broadcast_notify(machine_id: int, status: str):
    if status != "FINISHED":
        return
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        # Resolve machine_uuid from machine_id then notify subscribers
        cursor.execute("SELECT machine_uuid FROM machine_table WHERE machine_id = %s", (machine_id,))
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
