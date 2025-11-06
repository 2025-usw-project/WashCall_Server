# 🔥 FCM v1 API 전용 구성

## ✅ 변경 완료

Legacy FCM API가 완전히 제거되었습니다. 이제 **Firebase Admin SDK v1 API만** 사용합니다.

---

## 📋 주요 변경 사항

### `app/notifications/fcm.py`

**제거됨**:
- ❌ Legacy HTTP API (urllib)
- ❌ FCM_SERVER_KEY 환경변수
- ❌ Legacy 엔드포인트
- ❌ Fallback 로직

**유지됨**:
- ✅ Firebase Admin SDK v1 API
- ✅ MulticastMessage (최대 500 토큰/배치)
- ✅ 상세한 에러 로깅
- ✅ 실패한 토큰 추적

---

## 🚀 동작 방식

### 1. 초기화 (main.py)
```python
# 서버 시작 시 자동 실행
import firebase_admin
from firebase_admin import credentials

cred = credentials.Certificate("washcallproject-firebase-adminsdk-fbsvc-a48f08326a.json")
firebase_admin.initialize_app(cred)
```

### 2. 알림 전송 (fcm.py)
```python
# FCM v1 API로 전송
from firebase_admin import messaging

notif = messaging.Notification(title="🎉 세탁 완료!", body="빨래를 꺼내주세요!")
msg = messaging.MulticastMessage(
    notification=notif,
    data={"machine_id": "2", "status": "FINISHED"},
    tokens=["token1", "token2", ...]
)
resp = messaging.send_multicast(msg)
```

---

## 📊 응답 형식

### 성공 시:
```python
{
    "attempted": 6,      # 시도한 토큰 수
    "sent": 6,           # 성공한 토큰 수
    "v1": True          # FCM v1 사용 여부
}
```

### 일부 실패 시:
```python
{
    "attempted": 6,
    "sent": 4,
    "v1": True,
    "errors": [
        {
            "token": "eAbC1234...",
            "error": "Registration token not registered"
        },
        {
            "token": "xyz5678...",
            "error": "Invalid token format"
        }
    ]
}
```

---

## 🔍 로그 예시

### 성공 케이스:
```
🔥 FCM v1 API 사용 - 토큰 수: 6
📤 배치 전송 완료: success=6, fail=0
✅ FCM v1 전송 완료: attempted=6, sent=6
```

### 일부 실패 케이스:
```
🔥 FCM v1 API 사용 - 토큰 수: 6
📤 배치 전송 완료: success=4, fail=2
⚠️ 실패한 토큰 수: 2
✅ FCM v1 전송 완료: attempted=6, sent=4
```

### 초기화 안됨:
```
❌ Firebase Admin SDK가 초기화되지 않았습니다
RuntimeError: Firebase Admin SDK must be initialized before sending notifications
```

---

## ⚠️ 필수 요구사항

### 1. Firebase Admin SDK 패키지
```bash
pip install firebase-admin==6.5.0
```

### 2. Service Account 파일
```
washcallproject-firebase-adminsdk-fbsvc-a48f08326a.json
```

### 3. 환경 변수 (.env)
```env
FIREBASE_CREDENTIALS_FILE=washcallproject-firebase-adminsdk-fbsvc-a48f08326a.json
```

### 4. 서버 시작 시 초기화
`main.py`의 `startup_event()`에서 자동으로 초기화됩니다.

---

## 🎯 토큰 형식

### 웹 푸시 토큰 (VAPID)
```
eAbC1234567890abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ...
```

### 모바일 앱 토큰
```
fGhI9876543210ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890abcdefghijklm...
```

**중요**: 웹과 모바일 토큰 형식이 다르지만, FCM v1 API는 **둘 다 지원**합니다!

---

## 🔧 에러 처리

### 토큰 없음
```python
⚠️ FCM 전송 스킵: 토큰이 없습니다
return {"attempted": 0, "sent": 0, "v1": True}
```

### 초기화 안됨
```python
❌ Firebase Admin SDK가 초기화되지 않았습니다
raise RuntimeError(...)
```

### 전송 실패
```python
❌ FCM v1 API 전송 실패: [상세 에러]
raise Exception(...)
```

---

## 🧪 테스트 방법

### 1. 서버 시작
```bash
python main.py
```

### 2. 로그 확인
```
✅ Firebase Admin SDK initialized: washcallproject-firebase-adminsdk-fbsvc-a48f08326a.json
✅ Database connected successfully: MySQL ...
```

### 3. 알림 트리거
Arduino에서 세탁 완료 → `/update` 엔드포인트 호출

### 4. 로그 확인
```
🔥 FCM v1 API 사용 - 토큰 수: X
📤 배치 전송 완료: success=X, fail=0
✅ FCM v1 전송 완료: attempted=X, sent=X
```

---

## 📝 일반적인 에러

### "Invalid registration token"
**원인**: 토큰 형식이 잘못됨
**해결**: 웹 클라이언트에서 새 토큰 받기

### "Registration token not registered"
**원인**: 토큰이 만료되었거나 앱/브라우저가 삭제됨
**해결**: 새 토큰 받기 및 DB 업데이트

### "Requested entity was not found"
**원인**: Project ID가 잘못됨
**해결**: Service Account JSON 파일 확인

### "The default Firebase app does not exist"
**원인**: Firebase Admin SDK가 초기화되지 않음
**해결**: 서버 재시작 및 startup 로그 확인

---

## ✨ 장점

1. **공식 API**: Google이 공식 지원하는 최신 API
2. **보안**: Service Account 기반 인증 (Server Key보다 안전)
3. **기능**: 더 많은 기능 지원 (우선순위, TTL, 조건부 전송 등)
4. **에러 처리**: 토큰별 상세한 에러 정보
5. **성능**: 배치 전송으로 효율적 (500 토큰/요청)
6. **호환성**: 웹과 모바일 모두 지원

---

## 🎉 완료!

이제 서버를 재시작하면 **FCM v1 API만** 사용하여 안전하고 효율적으로 푸시 알림을 전송할 수 있습니다.

Legacy API는 완전히 제거되었으므로, `FCM_SERVER_KEY` 환경변수는 더 이상 필요하지 않습니다.
