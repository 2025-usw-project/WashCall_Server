# 🧺 WashCall Server

> 대학 기숙사 세탁기/건조기 실시간 모니터링 및 푸시 알림 시스템

WashCall은 Arduino IoT 센서와 연동하여 세탁기의 진동을 실시간으로 감지하고, 웹/모바일 클라이언트에 세탁 상태와 알림을 제공하는 스마트 세탁실 관리 시스템입니다.

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)](https://fastapi.tiangolo.com/)
[![MySQL](https://img.shields.io/badge/MySQL-8.0+-orange.svg)](https://www.mysql.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 📋 목차

- [주요 기능](#-주요-기능)
- [기술 스택](#-기술-스택)
- [프로젝트 구조](#-프로젝트-구조)
- [시작하기](#-시작하기)
- [API 문서](#-api-문서)
- [아키텍처](#-아키텍처)
- [환경변수](#-환경변수)

---

## ✨ 주요 기능

### 🔔 실시간 알림 시스템
- **개별 세탁기 알림**: 특정 세탁기의 완료 알림 (일회성)
- **세탁실 전체 알림**: 모든 세탁기의 완료 알림 (영구 구독)
- **WebSocket 실시간 업데이트**: 1분마다 타이머 동기화
- **FCM 푸시 알림**: Firebase Cloud Messaging (iOS PWA 지원)

### 📊 스마트 통계 및 추천
- **AI 기반 세탁 시간 추천**: Google Gemini API로 최적 시간대 제안
- **혼잡도 통계**: 요일별/시간대별 사용 패턴 분석
- **코스별 평균 시간**: 세탁/탈수 구간별 실시간 학습
- **예상 대기 시간**: 예약 대기열 기반 자동 계산

### 🌤️ 날씨 연동
- **기상청 API**: 실시간 날씨 정보 (기온, 강수확률, 습도)
- **1시간 캐싱**: DB 기반 효율적인 API 사용

### 🔐 사용자 관리
- **JWT 인증**: Bearer Token 기반 보안
- **역할 기반 접근**: USER / ADMIN 권한 관리
- **예약 시스템**: 세탁 순서 대기열

---

## 🛠️ 기술 스택

### Backend
- **FastAPI** - 고성능 비동기 웹 프레임워크
- **MySQL** - 관계형 데이터베이스 (연결 풀링)
- **WebSocket** - 실시간 양방향 통신
- **JWT** - 토큰 기반 인증

### External Services
- **Firebase Admin SDK** - FCM 푸시 알림 (v1 API)
- **Google Gemini API** - AI 기반 추천 생성
- **기상청 단기예보 API** - 날씨 정보

### IoT
- **Arduino** - 진동 센서 기반 세탁기 상태 감지

---

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

## 🚀 시작하기

### 사전 요구사항
- Python 3.11 이상
- MySQL 8.0 이상
- Firebase 프로젝트 (FCM 사용)
- Google Gemini API 키
- 기상청 API 인증키

### 설치

1. **저장소 클론**
```bash
git clone https://github.com/your-org/WashCall_Server.git
cd WashCall_Server
```

2. **가상환경 생성 및 활성화**
```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
```

3. **패키지 설치**
```bash
pip install -r requirements.txt
```

4. **환경변수 설정**
```bash
cp .env.example .env
# .env 파일 편집하여 필수 값 입력
```

5. **Firebase 인증 파일 준비**
- Firebase Console에서 서비스 계정 키 다운로드
- 프로젝트 루트에 `washcallproject-firebase-adminsdk-*.json` 저장

6. **데이터베이스 마이그레이션**
```sql
-- MySQL에서 데이터베이스 생성
CREATE DATABASE washing_machine_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
-- 테이블 스키마는 별도 SQL 파일 참조
```

### 실행

```bash
# 개발 서버 실행 (자동 리로드)
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# 프로덕션 실행
python main.py
```

서버가 실행되면 다음 URL에서 접근 가능:
- **API 문서 (Swagger)**: http://localhost:8000/docs
- **헬스체크**: http://localhost:8000/health

---

## 📚 API 문서

### 인증 (Authentication)

| Method | Endpoint | 설명 |
|--------|----------|------|
| POST | `/register` | 회원가입 |
| POST | `/login` | 로그인 (JWT 토큰 발급) |
| POST | `/logout` | 로그아웃 |

### 세탁기 상태 (Machine Status)

| Method | Endpoint | 설명 | 인증 |
|--------|----------|------|------|
| POST | `/load` | 세탁실 전체 상태 조회 | ✅ |
| GET | `/tip` | AI 기반 세탁 시간 추천 | ✅ |
| GET | `/rooms` | 세탁실 목록 | ✅ |

### 알림 관리 (Notifications)

| Method | Endpoint | 설명 | 인증 |
|--------|----------|------|------|
| POST | `/notify_me` | 개별 세탁기 알림 구독/해제 | ✅ |
| POST | `/set_fcm_token` | FCM 토큰 등록 | ✅ |
| POST | `/device_subscribe` | 세탁실 전체 알림 구독 | ✅ |

### 예약 (Reservations)

| Method | Endpoint | 설명 | 인증 |
|--------|----------|------|------|
| POST | `/reserve` | 세탁 예약 등록/해제 | ✅ |

### Arduino (IoT)

| Method | Endpoint | 설명 | 인증 |
|--------|----------|------|------|
| POST | `/update` | 세탁기 상태 업데이트 | ❌ |
| POST | `/raw_data` | Raw 센서 데이터 수신 | ❌ |

### 관리자 (Admin)

| Method | Endpoint | 설명 | 인증 |
|--------|----------|------|------|
| POST | `/admin/add_device` | 세탁기 추가 | ✅ Admin |
| POST | `/admin/add_room` | 세탁실 추가 | ✅ Admin |

### 통계 (Statistics)

| Method | Endpoint | 설명 | 인증 |
|--------|----------|------|------|
| GET | `/statistics/congestion` | 혼잡도 통계 조회 | ✅ |

### 기타

| Method | Endpoint | 설명 |
|--------|----------|------|
| GET | `/health` | 서버 및 DB 상태 확인 |
| POST | `/survey` | 설문조사 제출 |
| POST | `/start_course` | 코스 시작 (원격) |

---

## 🏗️ 아키텍처

### 시스템 구성도

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

### 세탁 프로세스 플로우

```
1. Arduino → POST /update (status=WASHING)
   ↓ first_update 기록
   ↓ WebSocket 브로드캐스트

2. Arduino → POST /update (status=SPINNING)
   ↓ spinning_update 기록
   ↓ 세탁 시간 계산 → time_table 업데이트
   ↓ WebSocket 브로드캐스트

3. Arduino → POST /update (status=FINISHED)
   ↓ 탈수 시간 계산 → time_table 업데이트
   ↓ 혼잡도 통계 업데이트 (busy_table)
   ↓ FCM 푸시 알림 전송
   ↓ notify_subscriptions 자동 해제
   ↓ WebSocket 브로드캐스트
```

### 알림 시스템

**개별 세탁기 알림 (일회성)**
- 사용자가 특정 세탁기 선택 → `POST /notify_me`
- `notify_subscriptions` 테이블에 등록
- FINISHED 상태 → FCM 푸시 + 자동 해제

**세탁실 전체 알림 (영구)**
- 세탁실 구독 → `POST /device_subscribe`
- `room_subscriptions` 테이블에 등록 (영구)
- 세탁실 내 모든 세탁기 FINISHED → FCM 푸시

**알림 스팸 방지**
- FINISHED 상태일 때만 FCM 전송
- WASHING/SPINNING → WebSocket만 사용
- 1분마다 타이머 동기화

---

## 🔧 환경변수

`.env` 파일에 다음 환경변수를 설정하세요:

```env
# Database
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your_password
DB_NAME=washing_machine_db
DB_CHARSET=utf8mb4
DB_COLLATION=utf8mb4_unicode_ci
DB_CONN_TIMEOUT=5

# JWT
JWT_SECRET=your_secret_key_here

# Firebase
FIREBASE_CREDENTIALS_FILE=washcallproject-firebase-adminsdk-*.json

# Google Gemini AI
GEMINI_API_KEY=your_gemini_api_key

# 기상청 API
KMA_AUTH_KEY=your_kma_api_key
KMA_NX=60
KMA_NY=127
```

---

## 📊 데이터베이스 스키마

### 주요 테이블

| 테이블 | 설명 |
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

## 🎯 핵심 설계 원칙

1. **알림 스팸 방지**: FCM은 FINISHED 상태일 때만, 그 외는 WebSocket
2. **일회성 알림**: FINISHED 후 notify_subscriptions에서 자동 삭제
3. **이상치 필터링**: 기존 평균의 ±50% 범위만 수락
4. **타이머 동기화**: 1분마다 전체 클라이언트 동기화
5. **데이터 캐싱**: 날씨(1시간), AI 요약(10분)
6. **비동기 처리**: FastAPI + async/await로 고성능 처리
7. **연결 풀링**: MySQL 연결 재사용으로 성능 향상

---

## 🤝 기여하기

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

## 📝 라이센스

이 프로젝트는 MIT 라이센스 하에 배포됩니다. 자세한 내용은 `LICENSE` 파일을 참조하세요.

---

## 📧 문의

프로젝트 관련 문의사항이 있으시면 이슈를 등록해주세요.

---

**Made with ❤️ by WashCall Team**
