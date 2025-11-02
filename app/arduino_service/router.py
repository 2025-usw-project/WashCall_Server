from fastapi import APIRouter, HTTPException
from .schemas import UpdateData, DeviceUpdateRequest, DeviceUpdateResponse
from app.database import get_db_connection
from app.websocket.manager import broadcast_room_status, broadcast_notify
import json

router = APIRouter()

def calculate_and_update_thresholds(cursor, machine_uuid: int):
    # 1. 평균값 계산
        query = """
            SELECT 
                AVG(wash_avg_magnitude) as avg_wash_avg,
                AVG(wash_max_magnitude) as avg_wash_max,
                AVG(spin_max_magnitude) as avg_spin_max,
                COUNT(*) as record_count
            FROM standard_table
            WHERE machine_uuid = %s
                AND wash_avg_magnitude IS NOT NULL
                AND wash_max_magnitude IS NOT NULL
                AND spin_max_magnitude IS NOT NULL
        """
        cursor.execute(query, (machine_uuid,))
        result = cursor.fetchone()
        
        if result and result[3] > 0:  # record_count > 0
            avg_wash_avg, avg_wash_max, avg_spin_max, record_count = result
            
            # 2. 새로운 기준점 계산
            # 새로운 세탁 기준점 = (평균 세탁 진동) x 0.7
            NewWashThreshold = avg_wash_avg * 0.7
            
            # 새로운 탈수 기준점 = (평균 최대 세탁 진동 + 평균 최대 탈수 진동) / 2
            NewSpinThreshold = (avg_wash_max + avg_spin_max) / 2
            
            # 3. machine_table 업데이트
            update_query = """
                UPDATE machine_table
                SET 
                    NewWashThreshold = %s,
                    NewSpinThreshold = %s,
                    NewWashThreshold_num = %s,
                    NewSpinThreshold_num = %s,
                    last_update = UNIX_TIMESTAMP()
                WHERE machine_uuid = %s
            """
            cursor.execute(update_query, (
                NewWashThreshold,
                NewSpinThreshold,
                record_count,
                record_count,
                machine_uuid
            ))


@router.post("/update")
async def update(data: UpdateData):
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # 1차 UPDATE (항상 실행)
            if data.status in ("WASHING", "SPINNING", "FINISHED"):
                query = """
                UPDATE machine_table SET status=%s, battery=%s, timestamp=%s
                WHERE machine_id=%s
                """
                cursor.execute(query, (data.status, data.battery, data.timestamp, data.machine_id))

            # 2차, 만약 status가 FINISHED라면 표준값 INSERT + 기준점 자동 계산
            if data.status == "FINISHED":
                cursor.execute(
                    "SELECT machine_uuid FROM machine_table WHERE machine_id=%s",
                    (data.machine_id,)
                )

                result = cursor.fetchone()
                if result is None:
                    raise HTTPException(status_code=404, detail="machine_id not found")

                machine_uuid = result[0]

                # standard_table에 데이터 삽입
                query2 = """
                INSERT INTO standard_table (machine_uuid, wash_avg_magnitude, wash_max_magnitude, spin_max_magnitude)
                VALUES (%s, %s, %s, %s)
                """
                cursor.execute(query2, (
                    machine_uuid,
                    data.wash_avg_magnitude,
                    data.wash_max_magnitude,
                    data.spin_max_magnitude,
                ))

                # 새로운 기준점 자동 계산
                calculate_and_update_thresholds(cursor, machine_uuid)

            # ✅ 중요: DB 커밋을 먼저 실행 (WebSocket 브로드캐스트 전에)
            conn.commit()

            # ✅ 핵심 수정: 모든 상태 변경에 대해 WebSocket 알림 전송
            # 상태가 변경될 때마다 구독 중인 사용자들에게 실시간 알림
            if data.status in ("WASHING", "SPINNING", "FINISHED"):
                # room 구독자들에게 알림
                await broadcast_room_status(data.machine_id, data.status)
                # 개별 기기 구독자들에게 알림  
                await broadcast_notify(data.machine_id, data.status)

            return {"message": "received"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Update failed: {str(e)}")
    

@router.post("/device_update", response_model=DeviceUpdateResponse)
async def device_update(request: DeviceUpdateRequest):
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # machine_table에서 해당 기기의 기준점 조회
            query = """
                SELECT NewWashThreshold, NewSpinThreshold
                FROM machine_table
                WHERE machine_id = %s
            """
            cursor.execute(query, (request.machine_id,))
            result = cursor.fetchone()
            
            if result is None:
                raise HTTPException(status_code=404, detail="machine_id not found")
            
            NewWashThreshold, NewSpinThreshold = result
            
            # 기준점이 NULL이면 기본값 반환 (또는 에러)
            if NewWashThreshold is None or NewSpinThreshold is None:
                raise HTTPException(
                    status_code=404, 
                    detail="Thresholds not calculated yet. Please complete at least one wash cycle."
                )
            
            # last_update 갱신 (선택사항)
            update_query = """
                UPDATE machine_table
                SET last_update = %s
                WHERE machine_id = %s
            """
            cursor.execute(update_query, (request.timestamp, request.machine_id))
            conn.commit()
            
            return DeviceUpdateResponse(
                message="received",
                NewWashThreshold=NewWashThreshold,
                NewSpinThreshold=NewSpinThreshold
            )
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Device update failed: {str(e)}")
