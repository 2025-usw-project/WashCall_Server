from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.arduino_service.router import router as arduino_router
from app.android_service.router import router as android_router

app = FastAPI(title="Laundry API", version="1.0.0")

# Android 앱과의 통신을 위해 CORS 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(arduino_router, tags=["arduino"])
app.include_router(android_router, tags=["android"])

@app.get("/health")
async def health():
    return {"status": "ok"}
