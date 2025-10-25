from fastapi import APIRouter, HTTPException
from .schemas import (
    RegisterDevice, DeviceData, UpdateData,
    DeviceUpdateRequest, DeviceUpdateResponse
)
from ..database import get_db_connection
import time

router = APIRouter()


@router.post("/register_device")
async def register_device(device: RegisterDevice):
    """새로운 세탁기를 등록"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # machine_table에 새 기기 삽입
            query = """
                INSERT INTO machine_table 
                (machine_id, machine_name, room_id, battery_capacity, battery, status, last_update, timestamp)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """
            values = (
                device.machine_id,
                device.machine_name,
                device.room_id,
                device.battery_capacity,
                device.battery_capacity,  # 초기 배터리는 최대 용량
                "IDLE",
                int(time.time()),
                int(time.time())
            )
            
            cursor.execute(query, values)
            conn.commit()
            
            return {
                "message": "register_machine ok",
                "machine_id": device.machine_id
            }
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Registration failed: {str(e)}")


@router.post("/devices")
async def devices(data: DeviceData):
    """세탁기 정보를 받아서 데이터베이스에 저장"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # machine_table 업데이트
            query = """
                UPDATE machine_table 
                SET status = %s, 
                    battery = %s, 
                    last_update = %s,
                    timestamp = %s
                WHERE machine_id = %s
            """
            values = (
                data.status.value,
                data.battery,
                data.last_update,
                int(time.time()),
                data.machine_id
            )
            
            cursor.execute(query, values)
            conn.commit()
            
            return {"message": "received"}
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Update failed: {str(e)}")


@router.post("/update")
async def update(data: UpdateData):
    """세탁기 상태 업데이트 및 기준값 저장"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 1. machine_table 업데이트
            update_query = """
                UPDATE machine_table 
                SET status = %s, 
                    battery = %s, 
                    last_update = %s,
                    timestamp = %s
                WHERE machine_id = %s
            """
            cursor.execute(update_query, (
                data.status.value,
                data.battery,
                data.last_update,
                int(time.time()),
                data.machine_id
            ))
            
            # 2. standard_table에 기준값 저장
            standard_query = """
                INSERT INTO standard_table (machine_id, washing_standard, spinning_standard)
                VALUES (%s, %s, %s)
            """
            cursor.execute(standard_query, (
                data.machine_id,
                data.washing_standard,
                data.spinning_standard
            ))
            
            conn.commit()
            
            return {"message": "received finished"}
            
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Update failed: {str(e)}")


@router.post("/device_update", response_model=DeviceUpdateResponse)
async def device_update(request: DeviceUpdateRequest):
    """특정 세탁기의 평균 기준값 조회 및 업데이트"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            
            # 1. 해당 machine_id의 평균 기준값 계산
            query = """
                SELECT 
                    AVG(washing_standard) as avg_washing,
                    AVG(spinning_standard) as avg_spinning,
                    COUNT(*) as count
                FROM standard_table
                WHERE machine_id = %s
            """
            cursor.execute(query, (request.machine_id,))
            result = cursor.fetchone()
            
            if not result or result['count'] == 0:
                # 데이터가 없으면 0.0 반환
                return DeviceUpdateResponse(
                    avg_washing_standard=0.0,
                    avg_spinning_standard=0.0
                )
            
            avg_washing = float(result['avg_washing'] or 0.0)
            avg_spinning = float(result['avg_spinning'] or 0.0)
            
            # 2. machine_table의 평균값 필드 업데이트
            update_query = """
                UPDATE machine_table 
                SET avg_washing_standard = %s,
                    avg_spinning_standard = %s,
                    last_update = %s
                WHERE machine_id = %s
            """
            cursor.execute(update_query, (
                avg_washing,
                avg_spinning,
                request.timestamp,
                request.machine_id
            ))
            
            conn.commit()
            
            return DeviceUpdateResponse(
                avg_washing_standard=avg_washing,
                avg_spinning_standard=avg_spinning
            )
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Device update failed: {str(e)}")


@router.get("/all_devices")
async def get_all_devices():
    """모든 세탁기 정보 조회"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            
            query = """
                SELECT machine_id, machine_name, room_id, room_name, 
                       status, battery, battery_capacity, last_update,
                       avg_washing_standard, avg_spinning_standard
                FROM machine_table
            """
            
            cursor.execute(query)
            devices = cursor.fetchall()
            
            return {"devices": devices}
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch devices: {str(e)}")
