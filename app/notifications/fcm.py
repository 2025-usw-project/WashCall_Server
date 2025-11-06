from typing import List, Optional, Dict
from loguru import logger

# Firebase Admin SDK (v1 API) - 필수
try:
    import firebase_admin  # type: ignore
    from firebase_admin import messaging  # type: ignore
except Exception as e:
    logger.error(f"❌ Firebase Admin SDK import failed: {e}")
    raise ImportError("Firebase Admin SDK is required for FCM v1 API") from e


def _chunked(items: List[str], size: int = 500) -> List[List[str]]:
    """FCM v1 API supports up to 500 tokens per multicast request"""
    return [items[i:i + size] for i in range(0, len(items), size)]


def send_to_tokens(tokens: List[str], title: str, body: str, data: Optional[Dict] = None) -> Dict:
    """Send push notifications to device tokens using Firebase Admin SDK v1 API.
    
    Firebase Admin SDK must be initialized in main.py startup event before calling this function.
    
    Args:
        tokens: List of FCM device tokens (web or mobile)
        title: Notification title
        body: Notification body
        data: Optional data payload (will be converted to strings)
    
    Returns:
        Dict with keys: attempted (int), sent (int), v1 (bool), errors (list)
    """
    # 토큰 정리
    tokens = [t for t in (tokens or []) if t]
    if not tokens:
        logger.warning("⚠️ FCM 전송 스킵: 토큰이 없습니다")
        return {"attempted": 0, "sent": 0, "v1": True}

    # Firebase Admin SDK 초기화 확인
    if not firebase_admin._apps:  # type: ignore[attr-defined]
        logger.error("❌ Firebase Admin SDK가 초기화되지 않았습니다")
        raise RuntimeError("Firebase Admin SDK must be initialized before sending notifications")

    logger.info(f"🔥 FCM v1 API 사용 - 토큰 수: {len(tokens)}")
    
    # Notification 객체 생성
    notif = messaging.Notification(title=title, body=body)  # type: ignore[call-arg]
    
    # Data payload를 문자열로 변환
    data_str = {str(k): str(v) for k, v in (data or {}).items()}
    
    # 배치 전송 (FCM v1은 최대 500개 토큰/요청)
    attempted = 0
    sent_total = 0
    failed_tokens = []
    
    try:
        for batch in _chunked(tokens):
            msg = messaging.MulticastMessage(
                notification=notif,
                data=data_str,
                tokens=batch
            )  # type: ignore[call-arg]
            
            # 전송
            resp = messaging.send_multicast(msg)
            attempted += len(batch)
            success_count = int(getattr(resp, "success_count", 0))
            failure_count = int(getattr(resp, "failure_count", 0))
            sent_total += success_count
            
            # 실패한 토큰 기록
            if failure_count > 0 and hasattr(resp, 'responses'):
                for idx, response in enumerate(resp.responses):
                    if not response.success:
                        failed_tokens.append({
                            "token": batch[idx][:20] + "...",
                            "error": str(response.exception) if response.exception else "Unknown"
                        })
            
            logger.info(f"📤 배치 전송 완료: success={success_count}, fail={failure_count}")
        
        logger.info(f"✅ FCM v1 전송 완료: attempted={attempted}, sent={sent_total}")
        
        result = {
            "attempted": attempted,
            "sent": sent_total,
            "v1": True
        }
        
        if failed_tokens:
            result["errors"] = failed_tokens
            logger.warning(f"⚠️ 실패한 토큰 수: {len(failed_tokens)}")
        
        return result
        
    except Exception as e:
        logger.error(f"❌ FCM v1 API 전송 실패: {e}", exc_info=True)
        raise
