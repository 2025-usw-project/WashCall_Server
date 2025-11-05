# 🔔 FCM 백그라운드 푸시 알림 테스트 가이드

## 📋 목차
1. [전제 조건](#전제-조건)
2. [테스트 시나리오](#테스트-시나리오)
3. [예상 동작](#예상-동작)
4. [트러블슈팅](#트러블슈팅)
5. [로그 확인](#로그-확인)

---

## 전제 조건

### ✅ 클라이언트 (WashCall-Web)
- [x] Firebase 프로젝트 설정 완료
- [x] `service-worker.js`에 Firebase SDK 추가
- [x] `js/push.js`에서 FCM 토큰 획득 및 서버 등록
- [x] `js/main.js`에 알림 클릭 시 스크롤 로직 추가

### ✅ 서버 (WashCall_Server)
- [x] `app/notifications/fcm.py` - FCM 전송 함수
- [x] `app/websocket/manager.py` - FINISHED 상태만 FCM 전송
- [x] Firebase Admin SDK 설정 (환경 변수 또는 JSON 키)

---

## 테스트 시나리오

### 🧪 시나리오 1: 웹 앱이 **열려있을 때** (Foreground)

**절차:**
1. 웹 브라우저에서 `index.html` 페이지 열기
2. 특정 세탁기의 "이 세탁기 알림 받기" 토글 켜기
   - 알림 권한 팝업이 뜨면 **허용** 클릭
   - "알림이 등록되었습니다" 메시지 확인
3. (테스트용) 해당 세탁기 상태를 `FINISHED`로 변경

**예상 결과:**
- ✅ WebSocket으로 실시간 UI 업데이트 (상태 변경)
- ✅ "세탁기 X 상태 변경: 세탁 완료" 팝업 표시
- ✅ 토글이 자동으로 꺼짐
- ✅ FCM 푸시 알림은 **전송되지만 브라우저가 자동으로 숨김** (Foreground에서는 알림이 표시되지 않음)

---

### 🧪 시나리오 2: 웹 앱이 **닫혀있을 때** (Background) ⭐️ 핵심

**절차:**
1. 웹 브라우저에서 `index.html` 페이지 열기
2. 특정 세탁기의 "이 세탁기 알림 받기" 토글 켜기
   - 알림 권한 허용
3. **브라우저 탭을 닫거나 최소화**
4. (테스트용) 해당 세탁기 상태를 `FINISHED`로 변경

**예상 결과:**
- ✅ 시스템 알림 팝업 표시
  - 제목: "🎉 세탁 완료!"
  - 내용: "{세탁기명}의 세탁이 완료되었습니다. 빨래를 꺼내주세요!"
  - 버튼: "확인하기", "닫기"
- ✅ 알림 클릭 시:
  - 브라우저 창이 자동으로 열림
  - 해당 세탁기 카드로 자동 스크롤
  - 노란색 하이라이트 효과 (2초간)
- ✅ DB에서 알림 자동 해제 (`notify_subscriptions` 삭제)

---

### 🧪 시나리오 3: 알림 클릭 → 특정 세탁기로 스크롤

**절차:**
1. 시나리오 2를 따라 백그라운드 알림 수신
2. 알림의 "확인하기" 버튼 클릭 (또는 알림 본문 클릭)

**예상 결과:**
- ✅ 브라우저가 `index.html#machine-123` 형태로 열림
- ✅ 자동으로 해당 세탁기 카드로 스크롤
- ✅ 카드 배경색이 노란색으로 2초간 깜빡임
- ✅ 개발자 콘솔에 스크롤 로그 출력:
  ```
  [main.js] Service Worker로부터 메시지 수신: {type: "SCROLL_TO_MACHINE", machine_id: "123"}
  [main.js] 세탁기로 스크롤 완료: machine_id=123
  ```

---

### 🧪 시나리오 4: 방(Room) 구독자에게 알림 전송

**절차:**
1. 특정 방(Room)을 구독
2. 해당 방의 세탁기 상태를 `FINISHED`로 변경

**예상 결과:**
- ✅ 방 구독자 전체에게 FCM 알림 전송
- ✅ 알림 제목: "🎉 {방 이름} 세탁 완료!"
- ✅ 알림 내용: "{세탁기명}의 세탁이 완료되었습니다."

---

### 🧪 시나리오 5: WASHING/SPINNING 상태에서는 FCM 전송 안 함

**절차:**
1. 세탁기 알림 구독
2. 브라우저 닫기
3. 세탁기 상태를 `WASHING`으로 변경

**예상 결과:**
- ✅ 시스템 알림 **표시 안 됨** (알림 스팸 방지)
- ✅ 서버 로그에 `FCM 스킵: status=WASHING` 출력

---

## 예상 동작

### 📤 서버 로그 (manager.py)

**FINISHED 상태로 변경 시:**
```log
📤 FCM 전송 시작: machine_id=1, 대상=3명
✅ FCM 전송 완료: {'success': 3, 'failure': 0}
🔕 알림 자동 해제 완료: machine_uuid=abc123, 해제된 구독=3개
```

**WASHING/SPINNING 상태일 때:**
```log
FCM 스킵: machine_id=1, status=WASHING (FINISHED 아님)
```

**구독자가 없을 때:**
```log
FCM 스킵: machine_id=1, 구독자 없음
```

**FCM 토큰이 없을 때:**
```log
FCM 스킵: machine_id=1, 유효한 토큰 없음
```

### 🖥️ 클라이언트 로그 (service-worker.js)

**백그라운드 메시지 수신:**
```log
[service-worker.js] 백그라운드 메시지 수신: {
  notification: {title: "🎉 세탁 완료!", body: "세탁기 1의 세탁이 완료되었습니다. 빨래를 꺼내주세요!"},
  data: {machine_id: "1", room_id: "1", status: "FINISHED", type: "wash_complete"}
}
[service-worker.js] 알림 표시: 🎉 세탁 완료! {...}
```

**알림 클릭:**
```log
[service-worker.js] 알림 클릭됨: wash-1
[main.js] Service Worker로부터 메시지 수신: {type: "SCROLL_TO_MACHINE", machine_id: "1"}
[main.js] 세탁기로 스크롤 완료: machine_id=1
```

---

## 트러블슈팅

### ❌ 문제: 알림이 표시되지 않음

**원인 및 해결:**

1. **브라우저 알림 권한 거부됨**
   - Chrome 설정 → 개인정보 및 보안 → 사이트 설정 → 알림 → 허용 목록에 추가

2. **Service Worker가 등록되지 않음**
   - F12 → Application → Service Workers 확인
   - `service-worker.js` 파일 경로 확인
   - 콘솔에서 오류 확인

3. **FCM 토큰이 서버에 등록되지 않음**
   - 개발자 콘솔에서 `FCM Token: xxxxxx` 로그 확인
   - 서버 DB `user_table`에서 `fcm_token` 컬럼 값 확인
   ```sql
   SELECT user_id, fcm_token FROM user_table WHERE user_id = YOUR_USER_ID;
   ```

4. **Firebase 설정 오류**
   - `push.js`와 `service-worker.js`의 `firebaseConfig`가 동일한지 확인
   - Firebase 콘솔에서 프로젝트 키 재확인

5. **HTTPS 필수**
   - Service Worker는 HTTPS 또는 `localhost`에서만 작동
   - 프로덕션 환경에서는 반드시 HTTPS 사용

6. **WASHING/SPINNING 상태에서 테스트**
   - FINISHED 상태가 아니면 FCM이 전송되지 않음
   - 반드시 FINISHED 상태로 변경해서 테스트

---

### ❌ 문제: 알림 클릭 후 스크롤되지 않음

**원인 및 해결:**

1. **세탁기 카드에 `data-machine-id` 속성 누락**
   - `main.js`의 `renderMachines` 함수 확인
   - `machineDiv.dataset.machineId = machine.machine_id;` 추가 여부 확인

2. **URL 해시가 제대로 설정되지 않음**
   - 알림 클릭 시 URL이 `index.html#machine-123` 형태인지 확인
   - `service-worker.js`의 `urlWithHash` 로직 확인

3. **DOM이 로드되기 전에 스크롤 시도**
   - `handleInitialHashScroll` 함수의 `setTimeout` 시간 늘리기 (500ms → 1000ms)

4. **Service Worker 메시지 리스너 미등록**
   - `main.js`에 `setupServiceWorkerMessageListener()` 호출 확인
   - 콘솔에서 `Service Worker 메시지 리스너 등록 완료` 로그 확인

---

### ❌ 문제: 서버 로그에 "FCM 전송 실패" 출력

**원인 및 해결:**

1. **Firebase Admin SDK 미설정**
   ```bash
   # 환경 변수 설정 (Linux/Mac)
   export FIREBASE_CREDENTIALS_JSON='{"type":"service_account",...}'
   
   # 또는 JSON 파일 경로
   export GOOGLE_APPLICATION_CREDENTIALS="/path/to/serviceAccountKey.json"
   ```

2. **FCM 서버 키 만료 또는 오류**
   - Firebase 콘솔 → 프로젝트 설정 → 클라우드 메시징 → 서버 키 재생성

3. **잘못된 토큰**
   - DB에 저장된 `fcm_token`이 유효한지 확인
   - 토큰이 만료된 경우 클라이언트에서 재발급

---

### ❌ 문제: 알림이 자동으로 해제되지 않음

**원인 및 해결:**

1. **알림 자동 해제 로직 미실행**
   - `manager.py`의 `broadcast_notify` 함수 확인
   - FINISHED 상태일 때만 자동 해제됨

2. **DB 커밋 실패**
   - `conn.commit()` 호출 확인
   - DB 연결 오류 로그 확인

---

## 로그 확인

### 서버 로그 (WashCall_Server)

**실시간 로그 보기:**
```bash
cd C:\Users\zxcizc\Desktop\Projects\WashCall_Server
python main.py
```

**주요 로그 키워드:**
- `📤 FCM 전송 시작` - FCM 전송 시작
- `✅ FCM 전송 완료` - 성공
- `❌ FCM 전송 실패` - 실패 (에러 메시지 포함)
- `🔕 알림 자동 해제 완료` - 구독 해제
- `FCM 스킵` - 전송 생략 (상태 확인)

### 클라이언트 로그 (브라우저)

**개발자 도구 콘솔:**
1. F12 → Console 탭
2. 필터: `[service-worker.js]` 또는 `[main.js]`

**Service Worker 로그:**
1. F12 → Application 탭 → Service Workers
2. "Update on reload" 체크 (개발 중 자동 업데이트)
3. Service Worker 파일명 클릭 → 콘솔 확인

---

## 추가 테스트 도구

### 🔧 수동 FCM 전송 테스트 (Python)

```python
# test_fcm.py
from app.notifications.fcm import send_to_tokens

tokens = ["YOUR_FCM_TOKEN_HERE"]
title = "테스트 알림"
body = "FCM 전송 테스트입니다."
data = {
    "machine_id": "999",
    "room_id": "1",
    "status": "FINISHED",
    "type": "wash_complete",
    "click_action": "index.html"
}

result = send_to_tokens(tokens, title, body, data)
print(f"전송 결과: {result}")
```

### 🔧 Postman / cURL로 서버 API 테스트

```bash
# 세탁기 상태를 FINISHED로 변경 (Arduino 시뮬레이션)
curl -X POST https://server.washcall.space/arduino/update \
  -H "Content-Type: application/json" \
  -d '{
    "machine_id": 1,
    "status": "FINISHED",
    "timestamp": 1699999999,
    "battery": 100
  }'
```

---

## ✅ 체크리스트

### Phase 3 (서버)
- [x] `broadcast_room_status` - FINISHED 상태일 때만 FCM 전송
- [x] `broadcast_notify` - FINISHED 상태일 때만 FCM 전송
- [x] 알림 자동 해제 (`notify_subscriptions` 삭제)
- [x] 로깅 강화 (전송 시작/완료/실패/스킵)

### Phase 4 (클라이언트)
- [x] `service-worker.js` - 백그라운드 메시지 핸들러 개선
- [x] `service-worker.js` - 알림 클릭 시 창 열기 및 스크롤
- [x] `main.js` - Service Worker 메시지 리스너
- [x] `main.js` - URL 해시 스크롤 처리
- [x] `main.js` - `scrollToMachine` 함수 (하이라이트 효과)
- [x] `renderMachines` - `data-machine-id` 속성 추가

### Phase 5 (테스트)
- [ ] 시나리오 1: Foreground 테스트
- [ ] 시나리오 2: Background 테스트 ⭐️
- [ ] 시나리오 3: 알림 클릭 스크롤 테스트
- [ ] 시나리오 4: 방 구독 테스트
- [ ] 시나리오 5: WASHING 상태에서 FCM 전송 안 됨 확인
- [ ] 다양한 브라우저 테스트 (Chrome, Edge, Firefox)
- [ ] 모바일 브라우저 테스트 (Android Chrome)

---

## 📚 참고 자료

- [Firebase Cloud Messaging 공식 문서](https://firebase.google.com/docs/cloud-messaging)
- [Service Worker API (MDN)](https://developer.mozilla.org/en-US/docs/Web/API/Service_Worker_API)
- [Notification API (MDN)](https://developer.mozilla.org/en-US/docs/Web/API/Notifications_API)
- [Push API (MDN)](https://developer.mozilla.org/en-US/docs/Web/API/Push_API)

---

**작성일:** 2025-11-05 (재작성)  
**버전:** 2.0  
**작성자:** AI Assistant

