from __future__ import annotations

from pydantic import BaseModel, RootModel, Field
from typing import List, Dict, Annotated, Optional


class TimeContext(BaseModel):
    iso_timestamp: str
    weekday: str
    hour: int
    is_holiday: bool
    is_weekend: bool


class WeatherContext(BaseModel):
    source: str = "KMA"
    base_time: Optional[str] = None
    forecast_time: Optional[str] = None
    precipitation_probability: Optional[float] = None
    precipitation_type: Optional[str] = None
    rainfall_last_hour: Optional[float] = None
    temperature: Optional[float] = None
    humidity: Optional[float] = None


class RoomSummary(BaseModel):
    room_id: int
    room_name: str
    machines_total: int
    machines_busy: int
    machines_idle: int
    avg_remaining_minutes: Optional[float] = None
    max_remaining_minutes: Optional[float] = None
    reservation_count: int = 0
    notify_count: int = 0
    estimated_wait_minutes: Optional[float] = None


class AlertContext(BaseModel):
    recent_finished_count: int = 0
    active_notify_subscriptions: int = 0


class TotalsContext(BaseModel):
    machines_total: int
    machines_busy: int
    machines_idle: int
    reservations_total: int
    notify_total: int


class StatusContext(BaseModel):
    time: TimeContext
    weather: WeatherContext | None = None
    totals: TotalsContext
    rooms: List[RoomSummary]
    alerts: AlertContext


class RegisterRequest(BaseModel):
    user_username: str
    user_password: str
    user_role: bool | None = None  # True: admin, False/None: user
    user_snum: int | None = None   # 학번


class RegisterResponse(BaseModel):
    message: str


class LoginRequest(BaseModel):
    user_snum: int
    user_password: str
    fcm_token: str


class LoginResponse(BaseModel):
    access_token: str


class LogoutRequest(BaseModel):
    access_token: str | None = None


class DeviceSubscribeRequest(BaseModel):
    access_token: str | None = None
    room_id: int


class LoadRequest(BaseModel):
    access_token: str | None = None


class MachineItem(BaseModel):
    machine_id: int
    room_name: str
    machine_name: str
    status: str
    machine_type: str  # "washer" or "dryer"
    isusing: int  # 0: 알림 미등록, 1: 알림 등록됨
    timer: int | None = None  # 남은 시간(분)


class LoadResponse(BaseModel):
    isreserved: int  # 0: 예약 안함, 1: 예약함
    machine_list: List[MachineItem]
    status_context: StatusContext | None = None


class ReserveRequest(BaseModel):
    access_token: str | None = None
    room_id: int
    isreserved: int


class NotifyMeRequest(BaseModel):
    access_token: str | None = None
    machine_id: int
    isusing: int


class AdminAddDeviceRequest(BaseModel):
    access_token: str | None = None
    room_id: int
    machine_id: int
    machine_name: str


class AdminMachinesRequest(BaseModel):
    access_token: str | None = None
    room_id: int


class AdminAddRoomRequest(BaseModel):
    access_token: str | None = None
    room_name: str


class AdminAddRoomResponse(BaseModel):
    room_id: int


class SetFcmTokenRequest(BaseModel):
    access_token: str | None = None
    fcm_token: str


class CongestionResponse(RootModel[Dict[str, Annotated[List[int], Field(min_length=24, max_length=24)]]]):
    """요일 키(월~일) -> 24길이 정수 배열 매핑"""
    pass


class SurveyRequest(BaseModel):
    satisfaction: int = Field(..., ge=1, le=5, description="만족도 (1-5)")
    suggestion: str = Field(..., description="건의사항")


class SurveyResponse(BaseModel):
    message: str


class StartCourseRequest(BaseModel):
    machine_id: int
    course_name: str


class StartCourseResponse(BaseModel):
    timer: int | None  # 남은 시간 (분)


class TipResponse(BaseModel):
    tip_message: str