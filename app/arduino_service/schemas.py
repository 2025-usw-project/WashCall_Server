from enum import Enum
from pydantic import BaseModel, Field
from typing import Optional, List

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


# /raw_data용 스키마
class SensorData(BaseModel):
    accel_x: List[float] = Field(..., min_length=30, max_length=30)
    accel_y: List[float] = Field(..., min_length=30, max_length=30)
    accel_z: List[float] = Field(..., min_length=30, max_length=30)
    gyro_x: List[float] = Field(..., min_length=30, max_length=30)
    gyro_y: List[float] = Field(..., min_length=30, max_length=30)
    gyro_z: List[float] = Field(..., min_length=30, max_length=30)


class RawDataRequest(BaseModel):
    machine_id: int
    secret_key: str
    timestamp: int
    sensor_data: SensorData
    status: StatusEnum


class RawDataResponse(BaseModel):
    message: str = "receive ok"
