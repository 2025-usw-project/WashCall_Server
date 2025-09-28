from enum import Enum
from pydantic import BaseModel

class StatusEnum(str, Enum):    #str을 상속 API 문서는 값이 string 형이어야하는 것을 알게됨 (FastAPI)
    WASHING = "WASHING"
    DRYING = "DRYING"
    FINISHED = "FINISHED"

class RegisterDevice(BaseModel):    #Pydantic이라는 Python 라이브러리의 BaseModel을 상속받아 데이터 모델을 정의
    machine_id: int
    room_id: int
    machine_name: str
    battery_capacity: int

class DeviceData(BaseModel):
    machine_id: int
    machine_type: str
    status: StatusEnum
    battery: int
    last_update: int

class UpdateData(BaseModel):
    machine_id: int
    status: StatusEnum
    battery: int
    last_update: int
    washing_standard: float
    drying_standard: float

class DeviceUpdateRequest(BaseModel):   #요청
    machine_id: int
    timestamp: int  # Unix time 시각을 나타내는 방식

class DeviceUpdateResponse(BaseModel):  #응답
    avg_washing_standard: float
    avg_drying_standard: float