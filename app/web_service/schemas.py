from pydantic import BaseModel, RootModel, Field
from typing import List, Dict, Annotated


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
    isusing: int  # 0: 알림 미등록, 1: 알림 등록됨


class LoadResponse(BaseModel):
    isreserved: int  # 0: 예약 안함, 1: 예약함
    machine_list: List[MachineItem]


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
    timer: int  # 예상 소요 시간 (분)