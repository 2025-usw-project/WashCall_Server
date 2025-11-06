# Firebase 웹 푸시 설정 가이드

## 서버 측 설정 완료 ✅

서버는 이미 Firebase Admin SDK를 통해 FCM v1 API를 사용하도록 설정되어 있습니다.

### Service Account
- 파일: `washcallproject-firebase-adminsdk-fbsvc-a48f08326a.json`
- Project ID: `washcallproject`
- Project Number: `401971602509`

---

## 웹 클라이언트 설정

### 1. Firebase SDK 설치

```bash
npm install firebase
```

### 2. Firebase 초기화 (JavaScript/TypeScript)

```javascript
// firebase-config.js
import { initializeApp } from "firebase/app";
import { getMessaging, getToken, onMessage } from "firebase/messaging";

const firebaseConfig = {
  apiKey: "AIzaSyD0MBr9do9Hl3AJsNv0yZJRupDT1l-8dVE",
  authDomain: "washcallproject.firebaseapp.com",
  projectId: "washcallproject",
  storageBucket: "washcallproject.firebasestorage.app",
  messagingSenderId: "401971602509",
  appId: "1:401971602509:web:45ee34d4ed2454555aa804",
  measurementId: "G-K4FHGY7MZT"
};

// Firebase 초기화
const app = initializeApp(firebaseConfig);
const messaging = getMessaging(app);

export { messaging };
```

### 3. FCM 토큰 받기

```javascript
// requestPermission.js
import { getToken } from "firebase/messaging";
import { messaging } from "./firebase-config";

// VAPID 공개키 (웹 푸시 인증서)
const VAPID_KEY = "BCyYOy8xvlx73JHB2ZikUoNI19l7qmkTnpzQvqmlheaiXwelDy9SLa4LhRcx3wG82gwdtMlFcQH3lqr3_5pwGm8";

async function requestNotificationPermission() {
  try {
    // 알림 권한 요청
    const permission = await Notification.requestPermission();
    
    if (permission === "granted") {
      console.log("알림 권한 허용됨");
      
      // FCM 토큰 가져오기
      const token = await getToken(messaging, {
        vapidKey: VAPID_KEY
      });
      
      console.log("FCM Token:", token);
      
      // 이 토큰을 서버로 전송 (로그인 시 또는 별도 API)
      await sendTokenToServer(token);
      
      return token;
    } else {
      console.log("알림 권한 거부됨");
      return null;
    }
  } catch (error) {
    console.error("FCM 토큰 받기 실패:", error);
    return null;
  }
}

async function sendTokenToServer(fcmToken) {
  // 로그인 시
  await fetch("https://your-server.com/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      user_snum: 12345678,
      user_password: "password",
      fcm_token: fcmToken  // ← FCM 토큰 포함
    })
  });
  
  // 또는 별도 API
  const jwt = localStorage.getItem("access_token");
  await fetch("https://your-server.com/set_fcm_token", {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${jwt}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      fcm_token: fcmToken
    })
  });
}

export { requestNotificationPermission };
```

### 4. 포그라운드 메시지 수신

```javascript
// foreground-messaging.js
import { onMessage } from "firebase/messaging";
import { messaging } from "./firebase-config";

// 앱이 열려 있을 때 메시지 수신
onMessage(messaging, (payload) => {
  console.log("포그라운드 메시지 수신:", payload);
  
  const { title, body } = payload.notification;
  const { machine_id, room_id, status } = payload.data;
  
  // 커스텀 알림 표시
  new Notification(title, {
    body: body,
    icon: "/icon.png",
    badge: "/badge.png",
    data: payload.data
  });
  
  // UI 업데이트 등 추가 처리
  updateMachineStatus(machine_id, status);
});

function updateMachineStatus(machineId, status) {
  // 세탁기 상태 업데이트 로직
  console.log(`세탁기 ${machineId} 상태: ${status}`);
}
```

### 5. Service Worker 설정 (`firebase-messaging-sw.js`)

프로젝트 루트의 `public/firebase-messaging-sw.js` 파일 생성:

```javascript
// public/firebase-messaging-sw.js
importScripts('https://www.gstatic.com/firebasejs/9.0.0/firebase-app-compat.js');
importScripts('https://www.gstatic.com/firebasejs/9.0.0/firebase-messaging-compat.js');

firebase.initializeApp({
  apiKey: "AIzaSyD0MBr9do9Hl3AJsNv0yZJRupDT1l-8dVE",
  authDomain: "washcallproject.firebaseapp.com",
  projectId: "washcallproject",
  storageBucket: "washcallproject.firebasestorage.app",
  messagingSenderId: "401971602509",
  appId: "1:401971602509:web:45ee34d4ed2454555aa804"
});

const messaging = firebase.messaging();

// 백그라운드 메시지 수신
messaging.onBackgroundMessage((payload) => {
  console.log('백그라운드 메시지 수신:', payload);
  
  const notificationTitle = payload.notification.title;
  const notificationOptions = {
    body: payload.notification.body,
    icon: '/icon.png',
    badge: '/badge.png',
    data: payload.data
  };

  self.registration.showNotification(notificationTitle, notificationOptions);
});

// 알림 클릭 처리
self.addEventListener('notificationclick', (event) => {
  console.log('알림 클릭:', event);
  event.notification.close();
  
  const data = event.notification.data;
  const clickAction = data.click_action || 'index.html';
  
  event.waitUntil(
    clients.openWindow(clickAction)
  );
});
```

---

## 서버 측 FCM 전송 코드 (이미 구현됨)

서버는 `app/notifications/fcm.py`에서 Firebase Admin SDK를 통해 FCM 메시지를 전송합니다:

```python
# 자동으로 실행됨 - 수정 불필요
from firebase_admin import messaging

notif = messaging.Notification(title="🎉 세탁 완료!", body="빨래를 꺼내주세요!")
data = {
    "machine_id": "1",
    "room_id": "1",
    "status": "FINISHED",
    "type": "wash_complete"
}
msg = messaging.MulticastMessage(
    notification=notif,
    data=data,
    tokens=[token1, token2, ...]
)
response = messaging.send_multicast(msg)
```

---

## 중요 정보 요약

### 웹 푸시 인증 키 (VAPID Key)
```
BCyYOy8xvlx73JHB2ZikUoNI19l7qmkTnpzQvqmlheaiXwelDy9SLa4LhRcx3wG82gwdtMlFcQH3lqr3_5pwGm8
```

### 프로젝트 정보
- **Project ID**: `washcallproject`
- **Project Number**: `401971602509`
- **App ID**: `1:401971602509:web:45ee34d4ed2454555aa804`

---

## 알림 전송 플로우

1. **사용자**: 웹에서 알림 권한 허용 → FCM 토큰 받음
2. **사용자**: 로그인 시 FCM 토큰을 서버로 전송
3. **서버**: `user_table`에 `fcm_token` 저장
4. **Arduino**: 세탁 완료 시 `/update` 엔드포인트 호출
5. **서버**: 
   - WebSocket으로 실시간 브로드캐스트
   - FCM으로 푸시 알림 전송 (FINISHED 상태만)
6. **웹 클라이언트**: 
   - 포그라운드: `onMessage()` 핸들러 실행
   - 백그라운드: Service Worker가 알림 표시

---

## 테스트 방법

### 1. FCM 토큰 확인
브라우저 콘솔에서:
```javascript
await requestNotificationPermission();
// FCM Token: eAbC1234... 출력됨
```

### 2. 서버에서 테스트 전송
```python
# Python 테스트 스크립트
from app.notifications.fcm import send_to_tokens

tokens = ["your_fcm_token_here"]
result = send_to_tokens(
    tokens=tokens,
    title="테스트 알림",
    body="FCM 웹 푸시 테스트입니다!",
    data={"test": "true"}
)
print(result)  # {'attempted': 1, 'sent': 1, 'v1': True}
```

---

## 문제 해결

### 알림이 안 오는 경우
1. **브라우저 알림 권한** 확인 (차단되지 않았는지)
2. **FCM 토큰** 제대로 받았는지 확인
3. **Service Worker** 등록되었는지 확인
4. **서버 로그** 확인: `FCM 전송 완료` 메시지가 있는지
5. **HTTPS** 필수: 로컬 테스트는 `localhost`만 가능

### CORS 오류
서버의 `main.py`에서 웹 도메인이 `allow_origins`에 추가되어 있는지 확인

---

## 패키지 설치

서버에서 firebase-admin 패키지 설치:
```bash
pip install -r requirements.txt
```

이제 서버가 재시작되면 새로운 Firebase 프로젝트로 FCM v1 API를 통해 웹 푸시 알림을 전송할 수 있습니다! 🎉
