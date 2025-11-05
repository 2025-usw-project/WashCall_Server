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
    """
    방 구독자에게 WebSocket + FCM 알림 전송
    ❗️ FINISHED 상태일 때만 FCM 푸시 알림 전송 (알림 스팸 방지)
    """
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT room_id, room_name, machine_name FROM machine_table WHERE machine_id = %s",
            (machine_id,)
        )
        m = cursor.fetchone()
        if not m:
            logger.warning(f"broadcast_room_status: machine_id={machine_id} not found")
            return
        
        room_id = m["room_id"]
        room_name = m.get("room_name", "세탁실")
        machine_name = m.get("machine_name", "세탁기")
        
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
            "machine_name": machine_name
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
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT machine_uuid, machine_name, room_id FROM machine_table WHERE machine_id = %s", (machine_id,))
        mu = cursor.fetchone()
        if not mu:
            logger.warning(f"broadcast_notify: machine_id={machine_id} not found")
            return
        
        machine_uuid = mu.get("machine_uuid")
        machine_name = mu.get("machine_name", "세탁기")
        
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
            "status": status
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
