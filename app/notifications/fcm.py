from typing import List, Optional, Dict
import time
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


def _retry_with_backoff(func, max_retries: int = 3, initial_delay: float = 1.0):
    """네트워크 오류 시 지수 백오프로 재시도"""
    delay = initial_delay
    last_exception = None
    
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            last_exception = e
            error_str = str(e).lower()
            
            # 재시도 가능한 네트워크 오류인지 확인
            if any(err in error_str for err in ['connection reset', 'timeout', 'network', 'unreachable']):
                if attempt < max_retries - 1:
                    logger.warning(f"⚠️ 네트워크 오류 발생 (시도 {attempt + 1}/{max_retries}): {e}")
                    logger.info(f"🔄 {delay}초 후 재시도...")
                    time.sleep(delay)
                    delay *= 2  # 지수 백오프
                else:
                    logger.error(f"❌ 최대 재시도 횟수 초과 ({max_retries}회)")
                    raise
            else:
                # 재시도 불가능한 오류는 즉시 발생
                raise
    
    raise last_exception


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
    
    # ✅ 웹 푸시는 Data-only 메시지 권장 (Service Worker에서 처리)
    # Notification 객체는 모바일에만 필요
    # notif = messaging.Notification(title=title, body=body)
    
    # Data payload를 문자열로 변환 (title, body 포함)
    data_str = {
        "title": str(title),
        "body": str(body),
        **{str(k): str(v) for k, v in (data or {}).items()}
    }
    
    # 배치 전송 (FCM v1은 최대 500개 토큰/요청)
    attempted = 0
    sent_total = 0
    failed_tokens = []
    
    try:
        for batch in _chunked(tokens):
            # ✅ Data-only 메시지 (웹 푸시용)
            msg = messaging.MulticastMessage(
                data=data_str,
                tokens=batch
            )  # type: ignore[call-arg]
            
            # 재시도 로직을 사용하여 전송
            def send_batch():
                return messaging.send_each_for_multicast(msg)
            
            resp = _retry_with_backoff(send_batch, max_retries=3, initial_delay=0.5)
            
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
        logger.error(f"❌ FCM v1 API 전송 실패: {e}")
        logger.error(f"   에러 타입: {type(e).__name__}")
        logger.error(f"   토큰 수: {len(tokens)}")
        logger.error(f"   제목: {title}")
        logger.error(f"   본문: {body}")
        
        # 상세 에러 정보
        if hasattr(e, 'cause'):
            logger.error(f"   근본 원인: {e.cause}")
        if hasattr(e, 'response'):
            logger.error(f"   HTTP 응답: {e.response}")
        
        logger.error(f"   전체 스택: {repr(e)}", exc_info=True)
        raise
