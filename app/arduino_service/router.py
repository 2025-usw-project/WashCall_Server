from fastapi import APIRouter, HTTPException
from .schemas import UpdateData, DeviceUpdateRequest, DeviceUpdateResponse
from app.database import get_db_connection

router = APIRouter()

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
            
            # 2차, 만약 status가 FINISHED라면 표준값 INSERT도 수행
            if data.status == "FINISHED":
                cursor.execute(
                    "SELECT machine_uuid FROM machine_table WHERE machine_id=%s",
                    (data.machine_id,)
                )
                result = cursor.fetchone()
                if result is None:
                    raise HTTPException(status_code=404, detail="machine_id not found")
                machine_uuid = result[0]

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
            conn.commit()

        return {"message": "received"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Update failed: {str(e)}")

@router.post("/device_update", response_model=DeviceUpdateResponse)
async def device_update(request: DeviceUpdateRequest):
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # 기기의 표준값 갱신
            query = """
            UPDATE machine_table
            SET avgwashingstandard=%s, avgspinningstandard=%s, lastupdate=%s
            WHERE machine_id=%s
            """
            cursor.execute(query, (
                request.avg_washing_standard,
                request.avg_spinning_standard,
                request.timestamp,
                request.machine_id
            ))
            conn.commit()
        return DeviceUpdateResponse(
            message="received",
            avg_washing_standard=request.avg_washing_standard,
            avg_spinning_standard=request.avg_spinning_standard
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Device update failed: {str(e)}")
