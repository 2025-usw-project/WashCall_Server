# 🔔 FCM 백그라운드 푸시 알림 구현 계획

## 📋 목표
웹 앱이 **닫혀있거나 백그라운드**에 있어도 서버에서 보낸 FCM 메시지를 받을 수 있도록 구현

---

## 🏗️ 시스템 아키텍처

```
[세탁기 상태 변경]
        ↓
[FastAPI 서버]
        ↓
   [WebSocket Manager]
        ├─→ [WebSocket 연결된 클라이언트] → 실시간 업데이트
        └─→ [FCM 전송 (백그라운드 사용자용)]
                    ↓
            [Firebase Cloud Messaging]
                    ↓
            [브라우저 Service Worker]
                    ↓
            [푸시 알림 표시] 🔔
```

---

## ✅ 현재 상태 (이미 구현됨)

### 클라이언트 (웹)
- ✅ `service-worker.js` - Firebase SDK 임포트 및 백그라운드 메시지 핸들러
- ✅ `push.js` - FCM 토큰 발급 및 권한 요청
- ✅ Firebase 설정 완료

### 서버
- ✅ `app/notifications/fcm.py` - Firebase Admin SDK 통합
- ✅ Firebase 서비스 계정 JSON 파일 (`washcallproject-firebase-adminsdk-*.json`)
- ✅ `/set_fcm_token` API 엔드포인트 (토큰 저장)

---

## 🚀 구현 단계별 계획

### Phase 1: 환경 설정 (10분)

#### 1.1 서버 환경 변수 설정
```bash
# .env 파일 생성/수정
FIREBASE_CREDENTIALS_FILE=/path/to/washcallproject-firebase-adminsdk-fbsvc-6c0cc1e55f.json
# 또는
GOOGLE_APPLICATION_CREDENTIALS=/path/to/washcallproject-firebase-adminsdk-fbsvc-6c0cc1e55f.json
```

#### 1.2 Firebase Console 설정 확인
```
1. https://console.firebase.google.com 접속
2. washcall-server 프로젝트 선택
3. 프로젝트 설정 → 클라우드 메시징
4. "웹 푸시 인증서" (VAPID Key) 확인
5. push.js와 service-worker.js의 Firebase 설정 일치 확인
```

---

### Phase 2: 데이터베이스 스키마 확인 (5분)

#### 2.1 FCM 토큰 저장 테이블 확인
```sql
-- users 테이블에 fcm_token 컬럼이 있는지 확인
DESCRIBE users;

-- 없으면 추가
ALTER TABLE users ADD COLUMN fcm_token VARCHAR(512) DEFAULT NULL;
```

#### 2.2 알림 구독 정보 확인
```sql
-- notify_me 테이블 확인 (어떤 사용자가 어떤 세탁기를 구독하는지)
DESCRIBE notify_me;

-- 예상 구조:
-- user_id, machine_id, isusing (1=구독, 0=해제)
```

---

### Phase 3: 서버 FCM 전송 로직 구현 (30분)

#### 3.1 WebSocket Manager 수정
```python
# app/websocket/manager.py

class ConnectionManager:
    async def send_status_update_and_fcm(
        self, 
        machine_id: int, 
        new_status: str,
        db_conn
    ):
        """
        1. WebSocket으로 실시간 업데이트 전송
        2. 해당 세탁기를 구독한 사용자에게 FCM 전송
        """
        # Step 1: WebSocket 전송 (기존 로직)
        await self.broadcast_status_update(machine_id, new_status)
        
        # Step 2: FCM 전송 (신규)
        if new_status == 'FINISHED':
            await self.send_fcm_to_subscribers(machine_id, db_conn)
    
    async def send_fcm_to_subscribers(self, machine_id: int, db_conn):
        """
        특정 세탁기를 구독한 사용자들에게 FCM 전송
        """
        from app.notifications.fcm import send_to_tokens
        
        # 1. 구독자 조회
        cursor = db_conn.cursor(dictionary=True)
        query = """
            SELECT u.fcm_token, u.user_username, m.machine_name
            FROM notify_me nm
            JOIN users u ON nm.user_id = u.user_id
            JOIN machines m ON nm.machine_id = m.machine_id
            WHERE nm.machine_id = %s 
              AND nm.isusing = 1
              AND u.fcm_token IS NOT NULL
              AND u.fcm_token != ''
        """
        cursor.execute(query, (machine_id,))
        subscribers = cursor.fetchall()
        
        if not subscribers:
            return  # 구독자 없음
        
        # 2. FCM 토큰 추출
        tokens = [sub['fcm_token'] for sub in subscribers]
        machine_name = subscribers[0]['machine_name']
        
        # 3. FCM 전송
        title = "세탁 완료! 🎉"
        body = f"{machine_name}의 세탁이 완료되었습니다."
        data = {
            "machine_id": str(machine_id),
            "status": "FINISHED",
            "click_action": "index.html"  # 알림 클릭 시 이동할 페이지
        }
        
        result = send_to_tokens(tokens, title, body, data)
        print(f"FCM 전송 결과: {result}")
```

#### 3.2 아두이노 라우터에서 호출
```python
# app/arduino_service/router.py

@router.post("/update_status")
async def update_machine_status(
    request: UpdateStatusRequest,
    db = Depends(get_db_connection)
):
    """세탁기 상태 업데이트 (아두이노에서 호출)"""
    
    # 1. DB 업데이트
    cursor = db.cursor()
    cursor.execute(
        "UPDATE machines SET status = %s WHERE machine_id = %s",
        (request.status, request.machine_id)
    )
    db.commit()
    
    # 2. WebSocket + FCM 전송
    await manager.send_status_update_and_fcm(
        request.machine_id,
        request.status,
        db
    )
    
    return {"message": "ok"}
```

---

### Phase 4: 클라이언트 Service Worker 개선 (15분)

#### 4.1 service-worker.js 개선
```javascript
// service-worker.js

messaging.onBackgroundMessage((payload) => {
    console.log('[Service Worker] 백그라운드 메시지 수신:', payload);
    
    // 서버가 보낸 notification 객체
    const notificationTitle = payload.notification.title;
    const notificationOptions = {
        body: payload.notification.body,
        icon: '/images/favicon.png',  // 알림 아이콘
        badge: '/images/badge.png',   // 작은 배지 아이콘
        tag: payload.data?.machine_id || 'washcall',  // 중복 알림 방지
        requireInteraction: true,  // 사용자가 수동으로 닫을 때까지 유지
        data: payload.data  // 클릭 시 사용할 데이터
    };

    // 알림 표시
    return self.registration.showNotification(
        notificationTitle, 
        notificationOptions
    );
});

// 알림 클릭 시
self.addEventListener('notificationclick', event => {
    event.notification.close();
    
    // data에서 machine_id 추출
    const data = event.notification.data || {};
    const targetUrl = data.click_action || 'index.html';
    
    // 페이지 열기
    event.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true })
            .then(clientList => {
                // 이미 열린 창이 있으면 포커스
                for (let client of clientList) {
                    if (client.url.includes(targetUrl) && 'focus' in client) {
                        return client.focus();
                    }
                }
                // 없으면 새 창 열기
                if (clients.openWindow) {
                    return clients.openWindow(targetUrl);
                }
            })
    );
});
```

#### 4.2 index.html - Service Worker 등록 확인
```html
<!-- index.html head 또는 body 끝에 추가 -->
<script>
    // Firebase 스크립트 먼저 로드
    <script src="https://www.gstatic.com/firebasejs/8.10.0/firebase-app.js"></script>
    <script src="https://www.gstatic.com/firebasejs/8.10.0/firebase-messaging.js"></script>
    
    <!-- 그 다음 push.js 로드 -->
    <script src="js/push.js"></script>
</script>
```

---

### Phase 5: 포그라운드 메시지 처리 (10분)

#### 5.1 push.js - 포그라운드 메시지 리스너 추가
```javascript
// js/push.js 끝에 추가

// ❗️ 웹 앱이 열려있을 때 메시지 수신 처리
messaging.onMessage((payload) => {
    console.log('[Foreground] 메시지 수신:', payload);
    
    // 브라우저 자체 알림 표시 (포그라운드)
    const notificationTitle = payload.notification.title;
    const notificationOptions = {
        body: payload.notification.body,
        icon: '/images/favicon.png'
    };
    
    // 권한이 있으면 알림 표시
    if (Notification.permission === 'granted') {
        new Notification(notificationTitle, notificationOptions);
    }
    
    // 또는 커스텀 UI로 표시 (선택사항)
    // showCustomNotification(payload);
});
```

---

### Phase 6: 테스트 시나리오 (20분)

#### 6.1 단위 테스트
```python
# test_fcm.py

import asyncio
from app.notifications.fcm import send_to_tokens

def test_fcm_send():
    """FCM 전송 테스트"""
    # 실제 토큰 (테스트용)
    test_token = "YOUR_TEST_FCM_TOKEN"
    
    result = send_to_tokens(
        tokens=[test_token],
        title="테스트 알림",
        body="FCM 전송 테스트입니다.",
        data={"test": "true"}
    )
    
    print(f"전송 결과: {result}")
    assert result['sent'] > 0, "FCM 전송 실패"

if __name__ == "__main__":
    test_fcm_send()
```

#### 6.2 통합 테스트 시나리오

**시나리오 1: 웹 앱 열려있을 때**
```
1. 웹 앱 접속 (index.html)
2. "전체 알림 켜기" 클릭
3. 권한 허용
4. 세탁기 선택 (토글 on)
5. 아두이노에서 상태 변경 (FINISHED)
6. ✅ 브라우저에 알림 표시 확인 (Foreground)
```

**시나리오 2: 웹 앱 백그라운드**
```
1. 웹 앱 접속 → 알림 켜기 → 세탁기 선택
2. 다른 탭으로 이동 (웹 앱은 백그라운드)
3. 아두이노에서 상태 변경 (FINISHED)
4. ✅ OS 알림 표시 확인 (Service Worker)
```

**시나리오 3: 브라우저 완전히 닫힘**
```
1. 웹 앱 접속 → 알림 켜기 → 세탁기 선택
2. 브라우저 완전히 종료
3. 아두이노에서 상태 변경 (FINISHED)
4. ✅ OS 알림 표시 확인 (Service Worker 백그라운드 실행)
```

---

### Phase 7: 디버깅 및 로깅 (15분)

#### 7.1 서버 로깅 강화
```python
# app/websocket/manager.py

import logging
logger = logging.getLogger(__name__)

async def send_fcm_to_subscribers(self, machine_id: int, db_conn):
    try:
        # ... FCM 전송 로직 ...
        
        logger.info(f"FCM 전송: machine_id={machine_id}, subscribers={len(subscribers)}")
        logger.info(f"FCM 결과: {result}")
        
    except Exception as e:
        logger.error(f"FCM 전송 실패: {e}", exc_info=True)
```

#### 7.2 클라이언트 디버깅
```javascript
// Chrome DevTools → Application → Service Workers
// "service-worker.js" 상태 확인

// Console에서 확인
navigator.serviceWorker.getRegistrations().then(regs => {
    console.log('등록된 Service Workers:', regs);
});

// FCM 토큰 확인
messaging.getToken().then(token => {
    console.log('현재 FCM 토큰:', token);
});
```

---

## 📊 데이터 흐름 다이어그램

```
[사용자] 
   ↓ (1) 알림 권한 허용
[push.js]
   ↓ (2) FCM 토큰 발급
[Firebase SDK]
   ↓ (3) 토큰을 서버로 전송
[POST /set_fcm_token]
   ↓ (4) DB에 저장
[users.fcm_token]

──────────────────────────

[세탁기] → [아두이노]
   ↓ (5) 상태 변경 (FINISHED)
[POST /update_status]
   ↓ (6) DB 업데이트 + 구독자 조회
[WebSocket Manager]
   ├─→ (7a) WebSocket 실시간 전송
   └─→ (7b) FCM 전송
         ↓
   [Firebase Cloud Messaging]
         ↓
   [Service Worker]
         ↓ (8) 백그라운드 처리
   [OS 알림 표시] 🔔
```

---

## ⚙️ 환경별 설정

### 개발 환경 (localhost)
```javascript
// HTTPS가 아니면 Service Worker 작동 안함!
// 예외: localhost는 허용됨

// Chrome에서 테스트:
// chrome://flags/#unsafely-treat-insecure-origin-as-secure
// http://your-local-ip:5500 추가
```

### 프로덕션 환경 (HTTPS)
```nginx
# Nginx에서 Service Worker 캐싱 방지
location /service-worker.js {
    add_header Cache-Control "no-cache, no-store, must-revalidate";
    add_header Pragma "no-cache";
    add_header Expires "0";
}
```

---

## 🐛 트러블슈팅

### 문제 1: Service Worker 등록 실패
```
원인: HTTPS가 아님 (localhost 제외)
해결: HTTPS 인증서 설치 또는 ngrok 사용
```

### 문제 2: FCM 토큰 발급 실패
```
원인: Firebase 설정 오류
해결: 
1. Firebase Console에서 VAPID Key 확인
2. push.js와 service-worker.js의 firebaseConfig 일치 확인
```

### 문제 3: 백그라운드 알림 안옴
```
원인: 
1. Service Worker 미등록
2. 알림 권한 거부
3. FCM 토큰 서버 미저장

해결:
1. Chrome DevTools → Application → Service Workers 확인
2. 알림 권한 재요청
3. DB에서 users.fcm_token 확인
```

### 문제 4: 알림이 중복으로 표시됨
```
원인: tag 옵션 미설정
해결: notificationOptions에 unique tag 추가
```

---

## 📈 성능 최적화

### 1. FCM 배치 전송
```python
# 500명 이하면 한 번에 전송
# 500명 초과 시 자동으로 배치 처리 (fcm.py에 구현됨)
```

### 2. DB 쿼리 최적화
```sql
-- notify_me 테이블에 인덱스 추가
CREATE INDEX idx_notify_machine ON notify_me(machine_id, isusing);
CREATE INDEX idx_users_fcm ON users(fcm_token);
```

### 3. Service Worker 캐싱
```javascript
// service-worker.js
const CACHE_VERSION = 'v1';
// 정적 리소스 캐싱으로 로딩 속도 개선
```

---

## ✅ 체크리스트

### 서버 (Phase 1-3)
- [ ] `.env` 파일에 `FIREBASE_CREDENTIALS_FILE` 설정
- [ ] DB에 `users.fcm_token` 컬럼 확인/추가
- [ ] `app/websocket/manager.py`에 FCM 전송 로직 추가
- [ ] 아두이노 라우터에서 `send_fcm_to_subscribers` 호출
- [ ] 서버 재시작 및 로그 확인

### 클라이언트 (Phase 4-5)
- [ ] `service-worker.js` 백그라운드 핸들러 개선
- [ ] `push.js` 포그라운드 핸들러 추가
- [ ] `index.html`에 Firebase SDK 스크립트 로드 확인
- [ ] Service Worker 등록 확인 (DevTools)

### 테스트 (Phase 6)
- [ ] 포그라운드 알림 테스트
- [ ] 백그라운드 알림 테스트
- [ ] 브라우저 닫힌 상태 알림 테스트
- [ ] 여러 사용자 동시 알림 테스트

---

## 🎯 최종 목표 달성 기준

✅ **성공 조건:**
1. 웹 앱이 **완전히 닫힌 상태**에서도 알림 수신
2. 여러 사용자에게 **동시에** 알림 전송 가능
3. 알림 클릭 시 해당 페이지로 **자동 이동**
4. 알림 권한 거부 시 **우아하게** 처리

---

## 📚 참고 자료

- [Firebase Cloud Messaging 공식 문서](https://firebase.google.com/docs/cloud-messaging/js/client)
- [Service Worker API](https://developer.mozilla.org/ko/docs/Web/API/Service_Worker_API)
- [Web Push Notifications](https://web.dev/push-notifications-overview/)

---

## 🚀 다음 단계

이 계획을 따라 구현 후:
1. ✅ 기능 테스트
2. ✅ 사용자 피드백 수집
3. ✅ 성능 모니터링
4. 🔄 지속적 개선

