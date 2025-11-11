from enum import Enum
from pydantic import BaseModel
from typing import Optional

class StatusEnum(str, Enum):
    WASHING = "WASHING"
    SPINNING = "SPINNING"
    FINISHED = "FINISHED"
    EXT_VIBE = "EXT_VIBE"
    OFF = "OFF"

# /update용 스키마
class UpdateData(BaseModel):
    machine_id: int
    secret_key: str
    status: StatusEnum
    machine_type: str
    timestamp: int
    battery: Optional[int] = None
    wash_avg_magnitude: float = None  # FINISHED일 때만
    wash_max_magnitude: float = None
    spin_max_magnitude: float = None

# /device_update용 스키마
class DeviceUpdateRequest(BaseModel):
    machine_id: int
    timestamp: int

class DeviceUpdateResponse(BaseModel):
    message: str = "received"
    NewWashThreshold: float = None  # 컬럼명 변경
    NewSpinThreshold: float = None  # 컬럼명 변경


# /raw_data용 스키마 (magnitude 기반)
class RawDataRequest(BaseModel):
    machine_id: int
    timestamp: int
    magnitude: float
    deltaX: float
    deltaY: float
    deltaZ: float
    secret_key: Optional[str] = None  # 호환성을 위해 받되 무시


class RawDataResponse(BaseModel):
    message: str = "receive ok"
