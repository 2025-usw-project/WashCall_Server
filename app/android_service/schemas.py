from pydantic import BaseModel
from typing import List


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
    access_token: str


class DeviceSubscribeRequest(BaseModel):
    access_token: str
    room_id: int


class LoadRequest(BaseModel):
    access_token: str


class MachineItem(BaseModel):
    machine_id: int
    room_name: str
    machine_name: str
    status: str


class LoadResponse(BaseModel):
    machine_list: List[MachineItem]


class ReserveRequest(BaseModel):
    access_token: str
    room_id: int
    isreserved: int


class NotifyMeRequest(BaseModel):
    access_token: str
    machine_id: int
    isusing: int


class AdminAddDeviceRequest(BaseModel):
    access_token: str
    room_id: int
    machine_id: int
    machine_name: str


class AdminMachinesRequest(BaseModel):
    access_token: str
    room_id: int


class AdminAddRoomRequest(BaseModel):
    access_token: str
    room_name: str


class AdminAddRoomResponse(BaseModel):
    room_id: int


class SetFcmTokenRequest(BaseModel):
    access_token: str
    fcm_token: str
