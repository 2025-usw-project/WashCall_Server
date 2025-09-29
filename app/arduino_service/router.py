from fastapi import APIRouter
from .schemas import (
    RegisterDevice, DeviceData, UpdateData,
    DeviceUpdateRequest, DeviceUpdateResponse
)
from app.storage.state import washing_values, spinning_values

router = APIRouter()


@router.post("/register_device")
async def register_device(device: RegisterDevice):
    return {"message": "register_machine ok"}

@router.post("/devices")
async def devices(data: DeviceData):
    return {"message": "received"}

@router.post("/update")
async def update(data: UpdateData):
    # machine_id별로 washing_standard, spinning_standard를 저장
    washing_list = washing_values.setdefault(data.machine_id, [])   #washing_values에 data.machine_id 키가 있으면 키에 
    spinning_list = spinning_values.setdefault(data.machine_id, [])     #해당하는 값을 넣고, 없다면 data.machine_id(키)와 [](값)를 추가
    washing_list.append(data.washing_standard)
    spinning_list.append(data.spinning_standard)
    
    return {"message": "received finished"}

@router.post("/device_update", response_model=DeviceUpdateResponse)
async def device_update(request: DeviceUpdateRequest):
    washing_list = washing_values.get(request.machine_id, [])   #washing_values에 request.machine_id라는 키가 있다 -> 
    spinning_list = spinning_values.get(request.machine_id, [])     #키에 해당하는 값 넣음, 없으면 빈 리스트 넣음

    # 평균 계산, 값 없으면 0.0 반환
    avg_washing = sum(washing_list) / len(washing_list) if washing_list else 0.0
    avg_spinning = sum(spinning_list) / len(spinning_list) if spinning_list else 0.0

    return DeviceUpdateResponse(
        avg_washing_standard = avg_washing,
        avg_spinning_standard = avg_spinning
    )
