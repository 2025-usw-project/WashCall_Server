from fastapi import APIRouter, HTTPException
from .schemas import UpdateData, DeviceUpdateRequest, DeviceUpdateResponse
from app.database import get_db_connection
from app.websocket.manager import broadcast_room_status, broadcast_notify
import json
from datetime import datetime, timedelta
import pytz
import logging
import traceback

router = APIRouter()
logger = logging.getLogger(__name__)

WEEKDAY_MAP = {
    0: '월',  # Monday
    1: '화',  # Tuesday
    2: '수',  # Wednesday
    3: '목',  # Thursday
    4: '금',  # Friday
    5: '토',  # Saturday
    6: '일'   # Sunday
}

KST = pytz.timezone('Asia/Seoul')
MIN_TIMESTAMP = 1577836800  # 2020-01-01


def timestamp_to_weekday_hour(unix_timestamp):
    """
    Unix timestamp(초 단위)를 서울 시간대 기준으로 요일과 시간대로 변환
    """
    dt = datetime.fromtimestamp(unix_timestamp, tz=pytz.UTC)
    dt_kst = dt.astimezone(KST)

    weekday = dt_kst.weekday()
    hour = dt_kst.hour

    day_str = WEEKDAY_MAP[weekday]
    return day_str, hour

def calculate_and_update_thresholds(cursor, machine_uuid: int):
    """
    기준점 자동 계산 (dictionary=True 지원)
    """
    logger.info(f"기준점 계산 시작: machine_uuid={machine_uuid}")
    
    try:
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
        
        logger.info(f"기준점 계산 결과: {result}")
        
        # ✅ dict 키로 접근
        if result and result.get('record_count') and result['record_count'] > 0:
            avg_wash_avg = result['avg_wash_avg']
            avg_wash_max = result['avg_wash_max']
            avg_spin_max = result['avg_spin_max']
            record_count = result['record_count']
            
            logger.info(
                f"평균값: wash_avg={avg_wash_avg}, wash_max={avg_wash_max}, "
                f"spin_max={avg_spin_max}, count={record_count}"
            )
            
            # 2. 새로운 기준점 계산
            # 새로운 세탁 기준점 = (평균 세탁 진동) x 0.7
            NewWashThreshold = avg_wash_avg * 0.7
            
            # 새로운 탈수 기준점 = (평균 최대 세탁 진동 + 평균 최대 탈수 진동) / 2
            NewSpinThreshold = (avg_wash_max + avg_spin_max) / 2
            
            logger.info(
                f"새로운 기준점: NewWashThreshold={NewWashThreshold}, "
                f"NewSpinThreshold={NewSpinThreshold}"
            )
            
            # 3. machine_table 업데이트
            update_query = """
            UPDATE machine_table
            SET
                NewWashThreshold = %s,
                NewSpinThreshold = %s,
                NewWashThreshold_num = %s,
                NewSpinThreshold_num = %s
            WHERE machine_uuid = %s
            """
            
            cursor.execute(update_query, (
                NewWashThreshold,
                NewSpinThreshold,
                record_count,
                record_count,
                machine_uuid
            ))
            
            logger.info(f"기준점 업데이트 완료: machine_uuid={machine_uuid}")
        else:
            logger.warning(f"기준점 계산 불가: record_count가 0 이하입니다. result={result}")
    
    except Exception as e:
        logger.error(f"기준점 계산 중 오류: {str(e)}", exc_info=True)
        # 기준점 계산 실패해도 진행 (중요하지 않음)

def update_congestion_for_range(cursor, start_timestamp: int, end_timestamp: int):
    """
    세탁 시작부터 종료까지의 모든 시간대 혼잡도 +1
    예: 7시 시작 ~ 9시 종료 → 7시, 8시, 9시 각각 +1
    """
    start_dt = datetime.fromtimestamp(start_timestamp, tz=pytz.UTC).astimezone(KST)
    end_dt = datetime.fromtimestamp(end_timestamp, tz=pytz.UTC).astimezone(KST)
    
    current_dt = start_dt.replace(minute=0, second=0, microsecond=0)
    
    while current_dt <= end_dt:
        weekday = current_dt.weekday()
        hour = current_dt.hour
        day_str = WEEKDAY_MAP[weekday]
        
        congestion_query = """
        INSERT INTO busy_table (busy_day, busy_time, busy_count)
        VALUES (%s, %s, 1)
        ON DUPLICATE KEY UPDATE
            busy_count = busy_count + 1,
            updated_at = CURRENT_TIMESTAMP
        """
        cursor.execute(congestion_query, (day_str, hour))
        
        current_dt += timedelta(hours=1)


@router.post("/update")
async def update(data: UpdateData):
    """
    Arduino 상태 업데이트 처리
    - ✅ FINISHED → WASHING 전환 감지
    - ✅ FINISHED 상태일 때 last_update 갱신
    - ✅ 모든 상태 변경 시 DB 커밋
    """
    try:
        # ===== 1단계: 입력값 검증 =====
        logger.info(f"UPDATE 요청 수신: machine_id={data.machine_id}, status={data.status}")
        
        if data.timestamp is None:
            logger.error("timestamp가 None입니다")
            raise HTTPException(status_code=400, detail="timestamp이 필수입니다")
        
        if data.timestamp < MIN_TIMESTAMP:
            logger.error(f"Invalid timestamp: {data.timestamp}")
            raise HTTPException(status_code=400, detail=f"Invalid timestamp: {data.timestamp}")
        
        logger.info(f"Timestamp OK: {data.timestamp}")
        
        with get_db_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            
            # ===== 2단계: 현재 DB 상태 조회 =====
            try:
                cursor.execute(
                    "SELECT status, last_update, machine_uuid FROM machine_table WHERE machine_id=%s",
                    (data.machine_id,)
                )
                
                db_result = cursor.fetchone()
                
                if db_result is None:
                    logger.error(f"machine_id {data.machine_id}를 찾을 수 없습니다")
                    raise HTTPException(status_code=404, detail=f"machine_id {data.machine_id} not found")
                
                current_status = db_result.get("status")
                last_update_db = db_result.get("last_update")
                machine_uuid = db_result.get("machine_uuid")
                
                logger.info(f"DB 조회 완료: current_status={current_status}, machine_uuid={machine_uuid}")
                
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"DB 조회 중 오류: {str(e)}", exc_info=True)
                raise HTTPException(status_code=500, detail=f"DB 조회 실패: {str(e)}")
            
            # ===== 3단계: FINISHED → WASHING 전환 감지 =====
            if current_status == "FINISHED" and data.status == "WASHING":
                logger.info(f"✅ FINISHED → WASHING 전환 감지! first_update 기록")
                
                try:
                    first_update_query = """
                    UPDATE machine_table
                    SET first_update = FROM_UNIXTIME(%s)
                    WHERE machine_id = %s
                    """
                    cursor.execute(first_update_query, (data.timestamp, data.machine_id))
                    logger.info(f"first_update 기록 완료: {data.timestamp}")
                except Exception as e:
                    logger.error(f"first_update 기록 실패: {str(e)}", exc_info=True)
            
            # ===== 4단계: machine_table 상태 업데이트 =====
            try:
                if data.status in ("WASHING", "SPINNING", "FINISHED"):
                    logger.info(f"상태 업데이트 시작: {data.status}")
                    
                    # ✅ FINISHED 상태일 때만 last_update 갱신
                    if data.status == "FINISHED":
                        logger.info("✅ FINISHED 상태: last_update 갱신")
                        
                        # ✅ Python에서 현재 시간을 Unix timestamp (int)로 변환
                        current_time_int = int(datetime.now(KST).timestamp())
                        logger.info(f"현재 시간 (timestamp): {current_time_int}")
                        
                        if data.battery is not None:
                            query = """
                            UPDATE machine_table
                            SET status=%s, battery=%s, timestamp=%s, last_update=%s
                            WHERE machine_id=%s
                            """
                            logger.info(f"battery 포함 UPDATE (last_update={current_time_int})")
                            cursor.execute(query, (data.status, data.battery, data.timestamp, current_time_int, data.machine_id))
                        else:
                            query = """
                            UPDATE machine_table
                            SET status=%s, timestamp=%s, last_update=%s
                            WHERE machine_id=%s
                            """
                            logger.info(f"battery 제외 UPDATE (last_update={current_time_int})")
                            cursor.execute(query, (data.status, data.timestamp, current_time_int, data.machine_id))
                    else:
                        # WASHING, SPINNING: last_update 갱신 안 함
                        if data.battery is not None:
                            query = """
                            UPDATE machine_table
                            SET status=%s, battery=%s, timestamp=%s
                            WHERE machine_id=%s
                            """
                            logger.info(f"battery 포함 UPDATE")
                            cursor.execute(query, (data.status, data.battery, data.timestamp, data.machine_id))
                        else:
                            query = """
                            UPDATE machine_table
                            SET status=%s, timestamp=%s
                            WHERE machine_id=%s
                            """
                            logger.info(f"battery 제외 UPDATE")
                            cursor.execute(query, (data.status, data.timestamp, data.machine_id))
                    
                    rows_affected = cursor.rowcount
                    logger.info(f"상태 UPDATE 완료: {rows_affected}행 영향")
                    
            except Exception as e:
                logger.error(f"상태 UPDATE 중 오류: {str(e)}", exc_info=True)
                raise HTTPException(status_code=500, detail=f"상태 업데이트 실패: {str(e)}")
            
            # ===== 5단계: FINISHED 처리 =====
            if data.status == "FINISHED":
                try:
                    logger.info("FINISHED 상태: 추가 처리 시작")
                    
                    # first_update 조회
                    cursor.execute(
                        "SELECT first_update FROM machine_table WHERE machine_id=%s",
                        (data.machine_id,)
                    )
                    first_update_result = cursor.fetchone()
                    first_update_db = first_update_result.get("first_update") if first_update_result else None
                    
                    # first_update를 세탁 시작 시간으로 사용
                    if first_update_db is None:
                        logger.warning("first_update가 NULL입니다. last_update 사용")
                        if last_update_db is None:
                            logger.warning("last_update도 NULL입니다. 현재 timestamp 사용")
                            start_timestamp = data.timestamp
                        else:
                            try:
                                last_update_dt = last_update_db.replace(tzinfo=pytz.UTC).astimezone(KST)
                                start_timestamp = int(last_update_dt.timestamp())
                            except Exception as e:
                                logger.error(f"last_update 변환 실패: {str(e)}")
                                start_timestamp = data.timestamp
                    else:
                        # first_update 사용
                        try:
                            first_update_dt = first_update_db.replace(tzinfo=pytz.UTC).astimezone(KST)
                            start_timestamp = int(first_update_dt.timestamp())
                            logger.info(f"✅ first_update 사용: {start_timestamp}")
                        except Exception as e:
                            logger.error(f"first_update 변환 실패: {str(e)}")
                            start_timestamp = data.timestamp
                    
                    end_timestamp = data.timestamp
                    
                    logger.info(
                        f"세탁 시간 범위: "
                        f"{datetime.fromtimestamp(start_timestamp, KST).strftime('%Y-%m-%d %H:%M:%S')} ~ "
                        f"{datetime.fromtimestamp(end_timestamp, KST).strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                    
                    # standard_table 삽입
                    try:
                        query2 = """
                        INSERT INTO standard_table
                        (machine_uuid, wash_avg_magnitude, wash_max_magnitude, spin_max_magnitude)
                        VALUES (%s, %s, %s, %s)
                        """
                        cursor.execute(query2, (
                            machine_uuid,
                            data.wash_avg_magnitude or 0,
                            data.wash_max_magnitude or 0,
                            data.spin_max_magnitude or 0,
                        ))
                        logger.info("standard_table 삽입 완료")
                    except Exception as e:
                        logger.error(f"standard_table 삽입 실패: {str(e)}", exc_info=True)
                    
                    # 기준점 계산
                    try:
                        calculate_and_update_thresholds(cursor, machine_uuid)
                        logger.info("기준점 계산 완료")
                    except Exception as e:
                        logger.error(f"기준점 계산 실패: {str(e)}", exc_info=True)
                    
                    # 혼잡도 업데이트
                    try:
                        update_congestion_for_range(cursor, start_timestamp, end_timestamp)
                        logger.info("혼잡도 업데이트 완료")
                    except Exception as e:
                        logger.error(f"혼잡도 업데이트 실패: {str(e)}", exc_info=True)
                    
                    # first_update 초기화
                    try:
                        cursor.execute(
                            "UPDATE machine_table SET first_update = NULL WHERE machine_id = %s",
                            (data.machine_id,)
                        )
                        logger.info("first_update 초기화 완료")
                    except Exception as e:
                        logger.error(f"first_update 초기화 실패: {str(e)}", exc_info=True)
                    
                except Exception as e:
                    logger.error(f"FINISHED 처리 중 오류: {str(e)}", exc_info=True)
            
            # ===== 6단계: DB 커밋 ===== ✅ 모든 경우에 실행!
            try:
                conn.commit()
                logger.info("✅ DB 커밋 완료")
            except Exception as e:
                logger.error(f"DB 커밋 실패: {str(e)}", exc_info=True)
                raise HTTPException(status_code=500, detail=f"DB 커밋 실패: {str(e)}")
            
            # ===== 7단계: WebSocket 브로드캐스트 =====
            try:
                if data.status in ("WASHING", "SPINNING", "FINISHED"):
                    await broadcast_room_status(data.machine_id, data.status)
                    await broadcast_notify(data.machine_id, data.status)
                    logger.info("WebSocket 브로드캐스트 완료")
            except Exception as e:
                logger.error(f"WebSocket 브로드캐스트 실패: {str(e)}", exc_info=True)
            
            logger.info(f"✅ UPDATE 요청 완료: machine_id={data.machine_id}")
            return {"message": "received"}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"예기치 않은 오류 발생: {str(e)}", exc_info=True)
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Update failed: {str(e)}")

    

@router.post("/device_update", response_model=DeviceUpdateResponse)
async def device_update(request: DeviceUpdateRequest):
    """
    기준점 조회 API
    
    요청 필드:
    - machine_id: 세탁기 ID
    
    응답:
    - NewWashThreshold: 새 세탁 기준점
    - NewSpinThreshold: 새 탈수 기준점
    """
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
                logger.error(f"machine_id {request.machine_id}를 찾을 수 없습니다")
                raise HTTPException(status_code=404, detail="machine_id not found")
            
            NewWashThreshold, NewSpinThreshold = result
            
            logger.info(f"기준점 조회: machine_id={request.machine_id}, "
                       f"Wash={NewWashThreshold}, Spin={NewSpinThreshold}")
            
            # 기준점이 NULL이면 기본값 반환 (또는 에러)
            if NewWashThreshold is None or NewSpinThreshold is None:
                logger.warning(f"기준점이 설정되지 않음: machine_id={request.machine_id}")
                raise HTTPException(
                    status_code=404,
                    detail="Thresholds not calculated yet. Please complete at least one wash cycle."
                )
            
            logger.info(f"✅ 기준점 조회 완료: machine_id={request.machine_id}")
            
            return DeviceUpdateResponse(
                message="received",
                NewWashThreshold=NewWashThreshold,
                NewSpinThreshold=NewSpinThreshold
            )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"기준점 조회 실패: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Device update failed: {str(e)}")
    