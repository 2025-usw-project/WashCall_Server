# 🔥 FCM 웹 푸시 문제 해결 가이드

## 현재 상황 분석

로그를 보면:
```
✅ FCM 전송 완료 (room): {'attempted': 6, 'sent': 0, 'legacy': True}
✅ FCM 전송 완료: {'attempted': 1, 'sent': 0, 'legacy': True}
```

**문제**: `sent: 0` (전송 실패) + `legacy: True` (Legacy API 사용)

---

## 📋 체크리스트

### 1. 서버 재시작 후 로그 확인

서버를 재시작하고 다음 로그를 확인하세요:

```bash
# 서버 시작 시
✅ Firebase Admin SDK initialized: washcallproject-firebase-adminsdk-fbsvc-a48f08326a.json

# FCM 전송 시 (다음 중 하나가 나와야 함)
🔥 FCM v1 API 사용 - 토큰 수: X
✅ FCM v1 전송 완료: attempted=X, sent=X

# 또는 오류 로그
❌ FCM v1 API 전송 실패: [오류 메시지]
⚠️ Legacy FCM API 사용 (비추천)
❌ FCM_SERVER_KEY가 설정되지 않음 - 알림 전송 불가
```

**예상 문제**:
- Firebase Admin SDK가 초기화되지 않음
- FCM 토큰 형식이 잘못됨 (앱 토큰 vs 웹 토큰)
- Service Account 파일 경로 오류

---

## 🔍 웹 푸시 vs 앱 푸시

### 중요: FCM 토큰 종류가 다릅니다!

**안드로이드/iOS 앱 토큰**:
```
eAbC1234...xyz (약 152자)
```

**웹 브라우저 토큰**:
```
eAbC5678...abc (약 152자, 형식 다름)
```

현재 DB에 저장된 토큰이 **웹 토큰**인지 확인 필요!

---

## 🌐 웹 클라이언트 설정 방법

### 1단계: Service Worker 등록

웹 프로젝트의 `public/` 폴더에 `firebase-messaging-sw.js` 파일 복사

```
your-web-project/
├── public/
│   └── firebase-messaging-sw.js  ← 이 파일 필요!
├── src/
│   └── App.jsx
└── package.json
```

### 2단계: Firebase SDK 설치

```bash
npm install firebase
```

### 3단계: FCM 토큰 받기

`WEB_PUSH_CLIENT_SETUP.html` 파일을 브라우저에서 열어서:
1. "알림 권한 요청" 클릭
2. "FCM 토큰 받기" 클릭
3. 토큰 복사

### 4단계: 서버에 토큰 전송

```javascript
// 로그인 시
const response = await fetch('https://your-server.com/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
        user_snum: 12345678,
        user_password: "password",
        fcm_token: "웹에서_받은_FCM_토큰"  // ← 웹 토큰!
    })
});

// 또는 별도로
const jwt = "로그인_후_받은_JWT_토큰";
await fetch('https://your-server.com/set_fcm_token', {
    method: 'POST',
    headers: {
        'Authorization': `Bearer ${jwt}`,
        'Content-Type': 'application/json'
    },
    body: JSON.stringify({
        fcm_token: "웹에서_받은_FCM_토큰"
    })
});
```

---

## 🧪 테스트 방법

### 1. Firebase Admin SDK 초기화 확인

서버 로그에서:
```
✅ Firebase Admin SDK initialized: washcallproject-firebase-adminsdk-fbsvc-a48f08326a.json
```

이 메시지가 없으면 → Service Account 파일 경로 오류

### 2. FCM 토큰 확인

브라우저 콘솔에서:
```javascript
// FCM 토큰 받기
const token = await getToken(messaging, {
    vapidKey: "BCyYOy8xvlx73JHB2ZikUoNI19l7qmkTnpzQvqmlheaiXwelDy9SLa4LhRcx3wG82gwdtMlFcQH3lqr3_5pwGm8"
});
console.log("FCM Token:", token);
```

### 3. DB에서 토큰 확인

```sql
SELECT user_id, user_snum, fcm_token FROM user_table WHERE user_id = 13;
```

토큰이 NULL이거나 비어있으면 → 클라이언트가 토큰을 서버에 전송하지 않음

### 4. 수동 알림 테스트

Python에서:
```python
from app.notifications.fcm import send_to_tokens

# DB에서 가져온 실제 토큰
tokens = ["eAbC1234...xyz"]

result = send_to_tokens(
    tokens=tokens,
    title="테스트 알림",
    body="FCM 웹 푸시 테스트입니다!",
    data={"test": "true", "machine_id": "2"}
)

print(result)
# 성공: {'attempted': 1, 'sent': 1, 'v1': True}
# 실패: {'attempted': 1, 'sent': 0, 'legacy': True}
```

---

## ❌ 일반적인 오류

### 오류 1: "Firebase Admin SDK가 초기화되지 않음"
**원인**: Service Account 파일 경로가 잘못됨
**해결**:
```bash
# 파일이 존재하는지 확인
ls -la washcallproject-firebase-adminsdk-fbsvc-a48f08326a.json

# .env 파일 확인
cat .env | grep FIREBASE_CREDENTIALS_FILE
```

### 오류 2: "Invalid registration token"
**원인**: 잘못된 토큰 형식 (앱 토큰을 웹에 사용하거나 반대)
**해결**: 웹에서 받은 토큰인지 확인

### 오류 3: "Requested entity was not found"
**원인**: Project ID가 잘못됨
**해결**: Service Account JSON 파일의 `project_id` 확인

### 오류 4: "sent: 0"이지만 오류 없음
**원인**: 
- 토큰이 만료됨
- 토큰이 유효하지 않음
- 브라우저에서 알림 권한 거부됨

**해결**:
1. 브라우저에서 알림 권한 다시 요청
2. 새 FCM 토큰 받기
3. 서버에 새 토큰 전송

---

## 🔐 HTTPS 필수!

웹 푸시는 **HTTPS**에서만 작동합니다 (로컬 테스트는 `localhost` 가능).

- ✅ `https://washcall.space`
- ✅ `http://localhost:5500`
- ❌ `http://192.168.x.x:5500` (IP 주소는 HTTPS 필요)

---

## 📊 성공 로그 예시

```
2025-11-06 17:51:34 | INFO | 🔥 FCM v1 API 사용 - 토큰 수: 1
2025-11-06 17:51:34 | INFO | 배치 전송 완료: success=1, fail=0
2025-11-06 17:51:34 | INFO | ✅ FCM v1 전송 완료: attempted=1, sent=1
```

`success=1` → 알림 전송 성공! 🎉

---

## 🆘 여전히 안 되면?

1. **서버 재시작** 후 전체 로그 확인
2. **브라우저 콘솔** 오류 확인
3. **FCM 토큰** DB에 제대로 저장되었는지 확인
4. **Service Worker** 등록되었는지 확인 (브라우저 개발자 도구 → Application → Service Workers)
5. **알림 권한** 확인 (브라우저 설정 → 사이트 설정 → 알림)

---

## 🎯 다음 단계

1. 서버 재시작
2. 로그에서 정확한 오류 확인
3. 웹 클라이언트에서 FCM 토큰 받기
4. DB에 토큰 저장 확인
5. 알림 테스트

수정된 `fcm.py` 파일이 이제 상세한 로그를 출력하므로, 서버를 재시작하고 다시 테스트해보세요!
