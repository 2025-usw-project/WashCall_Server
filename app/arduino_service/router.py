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
            cursor = conn.cursor(buffered=True)
            
            try:
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
                    device.battery_capacity,
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
            finally:
                cursor.close()
                
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Registration failed: {str(e)}")


@router.post("/devices")
async def devices(data: DeviceData):
    """세탁기 정보를 받아서 데이터베이스에 저장"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor(buffered=True)
            
            try:
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
            finally:
                cursor.close()
                
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Update failed: {str(e)}")


@router.post("/update")
async def update(data: UpdateData):
    """세탁기 상태 업데이트 및 기준값 저장"""
    try:
        with get_db_connection() as conn:
            cursor = None
            try:
                cursor = conn.cursor(buffered=True)
                
                # 1. machine_id로 machine_uuid 조회
                uuid_query = "SELECT machine_uuid FROM machine_table WHERE machine_id = %s"
                cursor.execute(uuid_query, (data.machine_id,))
                result = cursor.fetchone()
                
                if not result:
                    raise HTTPException(status_code=404, detail=f"Machine ID {data.machine_id} not found")
                
                machine_uuid = result[0]
                
                # 2. machine_table 업데이트
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
                
                # 3. standard_table에 기준값 저장
                standard_query = """
                    INSERT INTO standard_table (machine_uuid, washing_standard, spinning_standard)
                    VALUES (%s, %s, %s)
                """
                cursor.execute(standard_query, (
                    machine_uuid,
                    data.washing_standard,
                    data.spinning_standard
                ))
                
                conn.commit()
                
                return {"message": "received finished"}
                
            except HTTPException:
                conn.rollback()
                raise
            except Exception as e:
                conn.rollback()
                raise HTTPException(status_code=500, detail=f"Update failed: {str(e)}")
            finally:
                if cursor:
                    cursor.close()
                    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@router.post("/device_update", response_model=DeviceUpdateResponse)
async def device_update(request: DeviceUpdateRequest):
    """특정 세탁기의 평균 기준값 조회 및 업데이트"""
    try:
        with get_db_connection() as conn:
            cursor = None
            try:
                cursor = conn.cursor(dictionary=True, buffered=True)
                
                # 1. machine_id로 machine_uuid 조회
                uuid_query = "SELECT machine_uuid FROM machine_table WHERE machine_id = %s"
                cursor.execute(uuid_query, (request.machine_id,))
                uuid_result = cursor.fetchone()
                
                if not uuid_result:
                    raise HTTPException(status_code=404, detail=f"Machine ID {request.machine_id} not found")
                
                machine_uuid = uuid_result['machine_uuid']
                
                # 2. 해당 machine_uuid의 평균 기준값 계산
                query = """
                    SELECT 
                        AVG(washing_standard) as avg_washing,
                        AVG(spinning_standard) as avg_spinning,
                        COUNT(*) as count
                    FROM standard_table
                    WHERE machine_uuid = %s
                """
                cursor.execute(query, (machine_uuid,))
                result = cursor.fetchone()
                
                if not result or result['count'] == 0:
                    return DeviceUpdateResponse(
                        avg_washing_standard=0.0,
                        avg_spinning_standard=0.0
                    )
                
                avg_washing = float(result['avg_washing'] or 0.0)
                avg_spinning = float(result['avg_spinning'] or 0.0)
                washing_count = int(result['count'])  # ✅ 세탁 기준값 개수
                spinning_count = int(result['count'])  # ✅ 탈수 기준값 개수 (동일)
                
                # 3. machine_table의 평균값 및 개수 필드 업데이트
                update_query = """
                    UPDATE machine_table 
                    SET avg_washing_standard = %s,
                        avg_spinning_standard = %s,
                        avg_washing_num = %s,
                        avg_spinning_num = %s,
                        last_update = %s
                    WHERE machine_id = %s
                """
                cursor.execute(update_query, (
                    avg_washing,
                    avg_spinning,
                    washing_count,   # ✅ 추가
                    spinning_count,  # ✅ 추가
                    request.timestamp,
                    request.machine_id
                ))
                
                conn.commit()
                
                return DeviceUpdateResponse(
                    avg_washing_standard=avg_washing,
                    avg_spinning_standard=avg_spinning
                )
                
            except HTTPException:
                conn.rollback()
                raise
            except Exception as e:
                conn.rollback()
                raise HTTPException(status_code=500, detail=f"Update failed: {str(e)}")
            finally:
                if cursor:
                    cursor.close()
                    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@router.get("/all_devices")
async def get_all_devices():
    """모든 세탁기 정보 조회"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor(dictionary=True, buffered=True)
            
            try:
                query = """
                    SELECT machine_uuid, machine_id, machine_name, room_id, room_name, 
                           status, battery, battery_capacity, last_update,
                           avg_washing_standard, avg_spinning_standard
                    FROM machine_table
                """
                
                cursor.execute(query)
                devices = cursor.fetchall()
                
                return {"devices": devices}
            finally:
                cursor.close()
                
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch devices: {str(e)}")


@router.get("/device/{machine_id}")
async def get_device_by_id(machine_id: int):
    """특정 세탁기 정보 조회"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor(dictionary=True, buffered=True)
            
            try:
                query = "SELECT * FROM machine_table WHERE machine_id = %s"
                cursor.execute(query, (machine_id,))
                device = cursor.fetchone()
                
                if not device:
                    raise HTTPException(status_code=404, detail="Machine not found")
                
                return device
            finally:
                cursor.close()
                
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch device: {str(e)}")


@router.get("/standards/{machine_id}")
async def get_standards_history(machine_id: int, limit: int = 10):
    """특정 세탁기의 기준값 이력 조회"""
    try:
        with get_db_connection() as conn:
            cursor = None
            try:
                cursor = conn.cursor(dictionary=True, buffered=True)
                
                # machine_id로 machine_uuid 조회
                uuid_query = "SELECT machine_uuid FROM machine_table WHERE machine_id = %s"
                cursor.execute(uuid_query, (machine_id,))
                uuid_result = cursor.fetchone()
                
                if not uuid_result:
                    raise HTTPException(status_code=404, detail=f"Machine ID {machine_id} not found")
                
                machine_uuid = uuid_result['machine_uuid']
                
                # 기준값 이력 조회
                query = """
                    SELECT standard_id, machine_uuid, 
                           washing_standard, spinning_standard, created_at
                    FROM standard_table
                    WHERE machine_uuid = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                """
                cursor.execute(query, (machine_uuid, limit))
                standards = cursor.fetchall()
                
                return {"standards": standards, "count": len(standards)}
                
            finally:
                if cursor:
                    cursor.close()
                    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch standards: {str(e)}")
