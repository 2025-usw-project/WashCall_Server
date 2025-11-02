from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.middleware.cors import CORSMiddleware
import asyncio

from app.arduino_service.router import router as arduino_router
from app.web_service.router import router as android_router

# 데이터베이스 연결 설정 추가
from app.database import get_db_connection
import logging

load_dotenv()

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Laundry API", version="1.0.0")

# Android 앱과의 통신을 위해 CORS 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # consider restricting to explicit origins in production
    allow_credentials=True,  # cookies won't be sent; bearer tokens must be set explicitly by clients
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type"],  # ensure Authorization is allowed in CORS preflight
)

app.include_router(arduino_router, tags=["arduino"])
app.include_router(android_router, tags=["android"])


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=getattr(app, "description", None),
        routes=app.routes,
    )
    components = openapi_schema.setdefault("components", {})
    security_schemes = components.setdefault("securitySchemes", {})
    security_schemes["bearerAuth"] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
    }

    # Mark protected endpoints with bearer security
    protected = {
        "/logout": ["post"],
        "/load": ["post"],
        "/reserve": ["post"],
        "/notify_me": ["post"],
        "/admin/add_device": ["post"],
        "/admin/add_room": ["post"],
        "/set_fcm_token": ["post"],
        "/rooms": ["get"],
        "/device_subscribe": ["get"],
        "/statistics/congestion": ["get"],
    }
    for path, methods in protected.items():
        path_item = openapi_schema.get("paths", {}).get(path)
        if not path_item:
            continue
        for method in methods:
            op = path_item.get(method)
            if op is not None:
                op.setdefault("security", [{"bearerAuth": []}])

    # Remove access_token from request models in docs (migration away from body tokens)
    schemas = components.setdefault("schemas", {})
    remove_token_in = [
        "LogoutRequest",
        "DeviceSubscribeRequest",
        "LoadRequest",
        "ReserveRequest",
        "NotifyMeRequest",
        "AdminAddDeviceRequest",
        "AdminAddRoomRequest",
        "SetFcmTokenRequest",
    ]
    for name in remove_token_in:
        schema = schemas.get(name)
        if not schema or "properties" not in schema:
            continue
        props = schema["properties"]
        if "access_token" in props:
            props.pop("access_token", None)
        if "required" in schema and isinstance(schema["required"], list):
            schema["required"] = [r for r in schema["required"] if r != "access_token"]

    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi


@app.get("/health")
async def health():
    """서버 및 데이터베이스 상태 확인"""
    try:
        # 데이터베이스 연결 테스트
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
        
        return {
            "status": "ok",
            "database": "connected"
        }
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return {
            "status": "error",
            "database": "disconnected",
            "error": str(e)
        }


@app.on_event("startup")
async def startup_event():
    """서버 시작 시 데이터베이스 연결 확인 (백오프 재시도)"""
    logger.info("Starting Laundry API Server...")
    last_error = None
    for attempt in range(5):
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT VERSION()")
                version = cursor.fetchone()
                logger.info(f"Database connected successfully: MySQL {version}")
                last_error = None
                break
        except Exception as e:
            last_error = e
            logger.error(f"DB connect attempt {attempt+1}/5 failed: {e}")
            await asyncio.sleep(1 + attempt)
    if last_error is not None:
        logger.warning("DB not ready; server will start but database operations may fail")


@app.on_event("shutdown")
async def shutdown_event():
    """서버 종료 시 정리 작업"""
    logger.info("Shutting down Laundry API Server...")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
