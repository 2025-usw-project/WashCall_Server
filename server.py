from fastapi import FastAPI
from pydantic import BaseModel  #BaseModel은 데이터의 구조와 타입(형식)을 명확하게 지정하고, 입력되는 데이터에 대해 자동으로 검증과 변환을 수행하는 클래스
from enum import Enum
from typing import List

app = FastAPI()

class RegisterDevice(BaseModel):    #Pydantic이라는 Python 라이브러리의 BaseModel을 상속받아 데이터 모델을 정의
    machine_id: int
    room_id: int
    machine_name: str
    battery_capacity: int

class StatusEnum(str, Enum):    #str을 상속 API 문서는 값이 string 형이어야하는 것을 알게됨 (FastAPI)
    WASHING = "WASHING"
    DRYING = "DRYING"
    FINISHED = "FINISHED"

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

# 메모리 저장용 딕셔너리: machine_id 별 리스트 보관
washing_values = {}
drying_values = {}

@app.post("/register_device")
async def register_device(device: RegisterDevice):
    return {"message": "register_machine ok"}

@app.post("/devices")
async def devices(data: DeviceData):
    return {"message": "received"}

@app.post("/update")
async def update(data: UpdateData):
    # machine_id별로 washing_standard, drying_standard를 저장
    washing_list = washing_values.setdefault(data.machine_id, [])   #washing_values에 data.machine_id 키가 있으면 키에 
    drying_list = drying_values.setdefault(data.machine_id, [])     #해당하는 값을 넣고, 없다면 data.machine_id(키)와 [](값)를 추가
    washing_list.append(data.washing_standard)
    drying_list.append(data.drying_standard)
    
    return {"message": "received finished"}

@app.post("/device_update", response_model=DeviceUpdateResponse)
async def device_update(request: DeviceUpdateRequest):
    washing_list = washing_values.get(request.machine_id, [])   #washing_values에 request.machine_id라는 키가 있다 -> 
    drying_list = drying_values.get(request.machine_id, [])     #키에 해당하는 값 넣음, 없으면 빈 리스트 넣음

    # 평균 계산, 값 없으면 0.0 반환
    avg_washing = sum(washing_list) / len(washing_list) if washing_list else 0.0
    avg_drying = sum(drying_list) / len(drying_list) if drying_list else 0.0

    return DeviceUpdateResponse(
        avg_washing_standard = avg_washing,
        avg_drying_standard = avg_drying
    )
