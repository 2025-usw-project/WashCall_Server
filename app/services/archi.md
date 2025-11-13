# WashCall Server 프로젝트 분석

## 📁 프로젝트 구조

```
WashCall_Server/
├── main.py                      # FastAPI 애플리케이션 진입점
├── requirements.txt             # Python 패키지 의존성
├── .env.example                 # 환경변수 템플릿
└── app/
    ├── database.py              # MySQL 연결 풀 관리
    ├── arduino_service/         # Arduino 하드웨어 통신
    │   ├── router.py           # 세탁기 상태 업데이트 API
    │   └── schemas.py          # Arduino 데이터 스키마
    ├── web_service/            # 웹/모바일 클라이언트 API
    │   ├── router.py           # 사용자 API 엔드포인트
    │   └── schemas.py          # API 요청/응답 스키마
    ├── websocket/              # WebSocket 실시간 통신
    │   └── manager.py          # 연결 관리 및 브로드캐스트
    ├── notifications/          # 푸시 알림
    │   └── fcm.py             # Firebase Cloud Messaging
    ├── auth/                   # 인증 시스템
    │   └── security.py        # JWT 토큰 발급/검증
    ├── services/               # 외부 서비스 연동
    │   ├── ai_summary.py      # Google Gemini AI 요약
    │   └── kma_weather.py     # 기상청 날씨 API
    └── utils/
        └── timer.py           # 타이머 계산 유틸리티
```

---

## 🏗️ 서버 아키텍처

### **1. 기술 스택**
- **웹 프레임워크**: FastAPI (비동기 처리)
- **데이터베이스**: MySQL (연결 풀링)
- **인증**: JWT (Bearer Token)
- **실시간 통신**: WebSocket + FCM 푸시 알림
- **AI**: Google Gemini API
- **외부 API**: 기상청(KMA) 단기예보 API

### **2. 3-Tier 아키�ecture**

```
┌─────────────────────────────────────────────┐
│   클라이언트 (웹/모바일 + Arduino IoT)        │
└─────────────────────────────────────────────┘
                    ↓ ↑
┌─────────────────────────────────────────────┐
│  API Layer (FastAPI)                         │
│  - arduino_service: IoT 데이터 수신          │
│  - web_service: 사용자 API                   │
│  - WebSocket: 실시간 상태 전송               │
└─────────────────────────────────────────────┘
                    ↓ ↑
┌─────────────────────────────────────────────┐
│  Business Logic Layer                        │
│  - 세탁기 상태 관리                          │
│  - 알림 구독 시스템                          │
│  - AI 기반 추천 생성                         │
│  - 통계 데이터 수집                          │
└─────────────────────────────────────────────┘
                    ↓ ↑
┌─────────────────────────────────────────────┐
│  Data Layer (MySQL)                          │
│  - machine_table: 세탁기 정보                │
│  - user_table: 사용자 정보                   │
│  - notify_subscriptions: 개별 알림           │
│  - room_subscriptions: 세탁실 구독           │
│  - time_table: 코스별 평균 시간              │
│  - busy_table: 혼잡도 통계                   │
└─────────────────────────────────────────────┘
```

---

## 🔥 핵심 기능

### **1. Arduino Service ([app/arduino_service/router.py](cci:7://file:///c:/Users/zxcizc/Desktop/Projects/WashCall_Server/app/arduino_service/router.py:0:0-0:0))**

#### **POST `/update`** - 세탁기 상태 업데이트
Arduino에서 실시간으로 세탁기 진동 센서 데이터를 전송하여 상태를 업데이트합니다.

**주요 로직:**
- **상태 전환 감지**:
  - `FINISHED → WASHING`: 세탁 시작 (`first_update` 기록)
  - `WASHING → SPINNING`: 탈수 시작 (`spinning_update` 기록, 세탁 시간 계산)
  - `SPINNING → FINISHED`: 완료 (FCM 푸시 알림 전송)

- **통계 데이터 수집**:
  - 코스별 평균 소요 시간 (`time_table`)
  - 세탁/탈수 구간 시간 (`avg_washing_time`, `avg_spinning_time`)
  - 혼잡도 통계 (`busy_table`: 요일+시간대별 사용 빈도)
  - 기준점 자동 계산 (`NewWashThreshold`, `NewSpinThreshold`)

- **이상치 필터링**: 기존 평균의 ±50% 범위를 벗어나는 데이터 제외

```python
# 예시: 세탁 완료 시 알림 전송
if current_status == "SPINNING" and data.status == "FINISHED":
    await broadcast_room_status(machine_id, "FINISHED")  # 세탁실 구독자
    await broadcast_notify(machine_id, "FINISHED")       # 개별 알림 구독자
```

---

### **2. Web Service ([app/web_service/router.py](cci:7://file:///c:/Users/zxcizc/Desktop/Projects/WashCall_Server/app/web_service/router.py:0:0-0:0))**

#### **사용자 인증**
- **POST `/register`**: 회원가입 (자동으로 1번 세탁실 구독)
- **POST `/login`**: JWT 토큰 발급 + FCM 토큰 저장
- **POST `/logout`**: 토큰 무효화

#### **세탁기 상태 조회**
- **POST `/load`**: 세탁실 전체 상태 조회
  - 사용 가능/사용 중 세탁기 현황
  - 남은 시간 계산 (코스별 평균 - 경과 시간)
  - 예약 대기열, 알림 구독 수
  - 예상 대기 시간 계산

```python
# 타이머 계산 로직
if status == "SPINNING":
    # 탈수 중: spinning_update부터 경과 시간
    avg_minutes = course_spinning_map.get(course_name)
    elapsed_minutes = (now_ts - spinning_update) // 60
    timer = max(0, avg_minutes - elapsed_minutes)
elif status == "WASHING":
    # 세탁 중: first_update부터 경과 시간
    avg_minutes = course_washing_map.get(course_name)
    elapsed_minutes = (now_ts - first_ts) // 60
    timer = max(0, avg_minutes - elapsed_minutes)
```

#### **알림 관리**
- **POST `/notify_me`**: 개별 세탁기 완료 알림 등록/해제
  - `isusing=1`: 알림 등록
  - `isusing=0`: 알림 해제
  - FINISHED 상태가 되면 자동 해제 (일회성)

- **POST `/set_fcm_token`**: FCM 토큰 등록 (푸시 알림용)

- **POST `/device_subscribe`**: 세탁실 전체 알림 구독 (영구 구독)

#### **예약 시스템**
- **POST `/reserve`**: 세탁 예약 등록/해제
  - 대기열에 추가되어 예상 대기 시간 계산에 반영

#### **AI 추천**
- **GET `/tip`**: AI 기반 세탁 시간 추천
  - 현재 세탁실 상황 분석
  - 날씨 정보 (비, 습도 등)
  - 혼잡도 통계 (요일+시간대별)
  - Google Gemini가 최적 시간대 추천

#### **관리자 기능**
- **POST `/admin/add_device`**: 세탁기 추가
- **POST `/admin/add_room`**: 세탁실 추가
- **POST `/start_course`**: 코스 시작 (웹에서 원격 시작)

#### **통계**
- **GET `/statistics/congestion`**: 혼잡도 통계 조회
- **GET `/rooms`**: 세탁실 목록

---

### **3. WebSocket Manager ([app/websocket/manager.py](cci:7://file:///c:/Users/zxcizc/Desktop/Projects/WashCall_Server/app/websocket/manager.py:0:0-0:0))**

#### **실시간 상태 업데이트**
- **연결 관리**: 사용자별 WebSocket 세션 관리
- **타이머 동기화**: 1분마다 모든 클라이언트에게 타이머 업데이트 전송

```python
# 1분마다 실행
async def broadcast_timer_snapshot():
    machines = await _gather_machine_timers(now_ts)
    await manager.broadcast({
        "type": "timer_sync",
        "timestamp": now_ts,
        "machines": machines
    })
```

#### **알림 브로드캐스트**

**1. [broadcast_room_status](cci:1://file:///c:/Users/zxcizc/Desktop/Projects/WashCall_Server/app/websocket/manager.py:90:0-221:109)**: 세탁실 구독자에게 알림
```python
# WebSocket으로 모든 상태 전송
for user in room_subscribers:
    await manager.send_to_user(user_id, {
        "type": "room_status",
        "machine_id": machine_id,
        "status": status,
        "timer": timer_minutes
    })

# FCM은 FINISHED 상태일 때만
if status == "FINISHED":
    send_to_tokens(fcm_tokens, "세탁 완료!", body, data)
```

**2. [broadcast_notify](cci:1://file:///c:/Users/zxcizc/Desktop/Projects/WashCall_Server/app/websocket/manager.py:224:0-368:116)**: 개별 세탁기 구독자에게 알림
```python
# FINISHED 후 자동 구독 해제
if status == "FINISHED":
    send_to_tokens(fcm_tokens, "🎉 세탁 완료!", ...)
    cursor.execute("DELETE FROM notify_subscriptions WHERE machine_uuid = %s")
```

---

### **4. FCM 푸시 알림 ([app/notifications/fcm.py](cci:7://file:///c:/Users/zxcizc/Desktop/Projects/WashCall_Server/app/notifications/fcm.py:0:0-0:0))**

#### **Firebase Admin SDK v1 API 사용**
- **Data-only 메시지**: Service Worker에서 알림 제어
- **iOS PWA 지원**: WebpushConfig 설정
- **배치 전송**: 최대 500개 토큰/요청
- **재시도 로직**: 네트워크 오류 시 지수 백오프

```python
def send_to_tokens(tokens, title, body, data):
    msg = messaging.MulticastMessage(
        data={"title": title, "body": body, ...},
        webpush=messaging.WebpushConfig(
            notification=messaging.WebpushNotification(title, body),
            fcm_options=messaging.WebpushFCMOptions(link=click_url)
        ),
        tokens=tokens
    )
    return messaging.send_each_for_multicast(msg)
```

---

### **5. AI 서비스 ([app/services/ai_summary.py](cci:7://file:///c:/Users/zxcizc/Desktop/Projects/WashCall_Server/app/services/ai_summary.py:0:0-0:0))**

#### **Google Gemini API로 세탁 시간 추천**
- **입력 데이터**:
  - 현재 시간 (요일, 공휴일 여부)
  - 날씨 정보 (기온, 강수, 습도 등)
  - 세탁실 현황 (사용 가능 대수, 예약 수)
  - 혼잡도 통계 (24시간 × 7일)

- **출력**: 한 줄 추천 메시지
  - "지금보다 오늘 저녁 8시가 더 쾌적할 것 같아요! 🌙"
  - "내일 화요일 오후 2시가 가장 한산할 것 같아요! ✨"

- **캐싱**: 10분간 결과 캐시 (불필요한 API 호출 방지)

---

### **6. 날씨 서비스 ([app/services/kma_weather.py](cci:7://file:///c:/Users/zxcizc/Desktop/Projects/WashCall_Server/app/services/kma_weather.py:0:0-0:0))**

#### **기상청 단기예보 API**
- **3시간 단위 예보**: 0200, 0500, 0800, ... 2300
- **1시간 캐싱**: DB에 저장하여 불필요한 API 호출 방지
- **제공 정보**:
  - 기온 (현재/최저/최고)
  - 강수확률, 강수형태, 강수량
  - 하늘상태, 풍속, 습도 등

```python
def fetch_kma_weather(now):
    base_date, base_time = _get_base_time(now)
    cached = _fetch_from_cache(base_date, base_time, nx, ny)
    if cached:
        return cached
    
    # API 호출 → XML 파싱 → DB 캐시 저장 → 반환
```

---

## 🔐 인증 시스템 ([app/auth/security.py](cci:7://file:///c:/Users/zxcizc/Desktop/Projects/WashCall_Server/app/auth/security.py:0:0-0:0))

- **비밀번호**: SHA-256 해싱
- **JWT 토큰**: HS256 알고리즘, 30일 만료
- **Bearer Token**: Authorization 헤더로 전송
- **역할**: USER / ADMIN

---

## 📊 데이터베이스 구조

### **주요 테이블**

| 테이블 | 역할 |
|--------|------|
| `machine_table` | 세탁기 정보 (상태, 위치, 코스, 타이머) |
| `user_table` | 사용자 정보 (JWT 토큰, FCM 토큰) |
| `room_table` | 세탁실 정보 |
| `notify_subscriptions` | 개별 세탁기 알림 구독 (일회성) |
| `room_subscriptions` | 세탁실 전체 알림 구독 (영구) |
| `reservation_table` | 세탁 예약 |
| `time_table` | 코스별 평균 시간 (세탁/탈수/전체) |
| `busy_table` | 혼잡도 통계 (요일+시간대별) |
| `standard_table` | 진동 센서 기준점 데이터 |
| `weather_cache` | 날씨 API 캐시 |

---

## 🔄 핵심 워크플로우

### **1. 세탁 시작 → 완료 프로세스**

```
1. Arduino: POST /update (status=WASHING)
   → machine_table.first_update 기록
   → WebSocket 브로드캐스트

2. Arduino: POST /update (status=SPINNING)
   → machine_table.spinning_update 기록
   → 세탁 시간 계산 → time_table 업데이트
   → WebSocket 브로드캐스트

3. Arduino: POST /update (status=FINISHED)
   → 탈수 시간 계산 → time_table 업데이트
   → 전체 소요 시간 계산 (이상치 필터링)
   → 혼잡도 통계 업데이트
   → FCM 푸시 알림 전송 (세탁실 + 개별 구독자)
   → notify_subscriptions 자동 해제
   → WebSocket 브로드캐스트
```

### **2. 알림 시스템 동작**

```
시나리오 A: 사용자가 직접 세탁 시작
  → POST /start_course
  → POST /notify_me (isusing=1) - 자동 구독
  → FINISHED 시 FCM 알림 + 자동 해제

시나리오 B: 이미 작동 중인 세탁기 구독
  → POST /notify_me (isusing=1)
  → FINISHED 시 FCM 알림 + 자동 해제

빈자리 알림 (영구 구독)
  → POST /device_subscribe
  → 모든 세탁기 FINISHED 시 알림 수신
  → 구독 해제 안 됨 (수동 해제 필요)
```

---

## 💡 설계 특징

1. **알림 스팸 방지**: FCM은 FINISHED 상태일 때만, 그 외는 WebSocket
2. **일회성 알림**: FINISHED 후 자동 구독 해제
3. **이상치 필터링**: 기존 평균의 ±50% 범위만 수락
4. **타이머 동기화**: 1분마다 전체 클라이언트 동기화
5. **데이터 캐싱**: 날씨(1시간), AI 요약(10분)
6. **비동기 처리**: FastAPI + async/await로 고성능 처리
7. **연결 풀링**: MySQL 연결 재사용으로 성능 향상