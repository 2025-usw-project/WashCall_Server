from fastapi import APIRouter, HTTPException
from .schemas import UpdateData, DeviceUpdateRequest, DeviceUpdateResponse
from app.database import get_db_connection
from app.websocket.manager import broadcast_room_status, broadcast_notify
from datetime import datetime, timedelta
import traceback
import pytz
import logging

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


def update_course_avg_time(cursor, course_name: str, elapsed_time: int):
    """
    코스별 평균 소요 시간 업데이트 (🔥 이상치 필터링 적용)
    ✅ elapsed_time은 초 단위로 입력받음
    ✅ 분 단위로 변환해서 저장
    ✅ 기존 평균의 ±50% 범위를 벗어나는 이상치 데이터 필터링
    """
    
    # ✅ 음수/0 필터링
    if elapsed_time <= 0:
        logger.warning(f"⚠️ 유효하지 않은 시간({elapsed_time}초), 기록 안함")
        return
    
    # ✅ 초를 분으로 변환 (핵심!)
    elapsed_time_minutes = elapsed_time // 60  # 정수 나눗셈으로 분 계산
    logger.info(f"⏱️ 시간 변환: {elapsed_time}초 → {elapsed_time_minutes}분")
    
    try:
        # 1단계: time_table에서 해당 코스 조회
        query_select = """
        SELECT avg_time, count_avg
        FROM time_table
        WHERE course_name = %s
        """
        cursor.execute(query_select, (course_name,))
        result = cursor.fetchone()
        
        if result is None:
            # 처음인 경우: 새로운 레코드 삽입 (분 단위)
            query_insert = """
            INSERT INTO time_table (course_name, avg_time, count_avg)
            VALUES (%s, %s, %s)
            """
            # ✅ elapsed_time_minutes를 저장!
            cursor.execute(query_insert, (course_name, elapsed_time_minutes, 1))
            logger.info(f"✅ 새로운 코스 기록: {course_name} = {elapsed_time_minutes}분")
            return
        
        # ✅ 딕셔너리 또는 튜플 모두 지원
        if isinstance(result, dict):
            existing_avg = result.get("avg_time")
            existing_count = result.get("count_avg")
        else:
            existing_avg = result[0]
            existing_count = result[1]
        
        # NULL 체크
        if existing_avg is None or existing_count is None or existing_count == 0:
            logger.warning(f"NULL/0 값 감지: avg={existing_avg}, count={existing_count}")
            # 처음이거나 잘못된 상태 → 새로 기록
            query_insert = """
            INSERT INTO time_table (course_name, avg_time, count_avg)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE
                avg_time = VALUES(avg_time),
                count_avg = VALUES(count_avg)
            """
            # ✅ elapsed_time_minutes를 저장!
            cursor.execute(query_insert, (course_name, elapsed_time_minutes, 1))
            logger.info(f"✅ 코스 '{course_name}' 새로 기록: {elapsed_time_minutes}분")
            return
        
        # ========== 🔥 이상치 필터링 로직 (핵심!) ==========
        # 기존 평균의 ±50% 범위 계산
        lower_bound = existing_avg * 0.5  # 하한선: 평균의 50%
        upper_bound = existing_avg * 1.5  # 상한선: 평균의 150%
        
        logger.info(f"📊 이상치 필터 범위: {lower_bound:.1f}분 ~ {upper_bound:.1f}분")
        logger.info(f"📊 현재 데이터: {elapsed_time_minutes}분 (기존 평균: {existing_avg}분)")
        
        # 이상치 검사
        if elapsed_time_minutes < lower_bound or elapsed_time_minutes > upper_bound:
            logger.warning(f"⚠️ 이상치 감지! {elapsed_time_minutes}분은 범위 [{lower_bound:.1f}, {upper_bound:.1f}]를 벗어남")
            logger.warning(f"⚠️ 코스 '{course_name}'의 평균 시간 업데이트를 건너뜀 (데이터 오염 방지)")
            logger.info(f"   - 기존 평균: {existing_avg}분 (횟수: {existing_count})")
            logger.info(f"   - 거부된 값: {elapsed_time_minutes}분")
            return  # 이상치는 평균 계산에 포함하지 않음
        
        logger.info(f"✅ 정상 데이터 확인: {elapsed_time_minutes}분은 유효 범위 내")
        # ====================================================
        
        # 새로운 평균 계산 (분 단위)
        new_total_time = (existing_avg * existing_count) + elapsed_time_minutes  # ✅ 분 단위!
        new_count = existing_count + 1
        new_avg = int(new_total_time / new_count)
        
        logger.info(f"코스 '{course_name}' 평균 시간 계산:")
        logger.info(f"  기존: {existing_avg}분 (횟수: {existing_count})")
        logger.info(f"  새로운: {elapsed_time_minutes}분")
        logger.info(f"  업데이트된 평균: {new_avg}분 (횟수: {new_count})")
        
        # 업데이트 (분 단위)
        query_update = """
        UPDATE time_table
        SET avg_time = %s, count_avg = %s
        WHERE course_name = %s
        """
        cursor.execute(query_update, (new_avg, new_count, course_name))
        logger.info(f"✅ 코스 '{course_name}' 평균 시간 업데이트: {new_avg}분")
        
    except Exception as e:
        logger.error(f"코스 평균 시간 업데이트 실패: {str(e)}", exc_info=True)
        raise


def update_segment_avg_time(cursor, course_name: str, elapsed_minutes: int, field_name: str):
    """
    특정 구간의 평균 시간 업데이트
    
    Parameters:
    - course_name: 코스 이름 (예: '표준', '쾌속')
    - elapsed_minutes: 경과 시간 (분 단위)
    - field_name: 'avg_washing_time' 또는 'avg_spinning_time'
    
    🔥 이상치 필터링: 기존 평균의 ±50% 범위만 수락
    """
    
    # ✅ 음수 또는 0 필터링
    if elapsed_minutes <= 0:
        logger.warning(f"⚠️ {field_name}: 유효하지 않은 시간({elapsed_minutes}분), 기록 안함")
        return
    
    try:
        # 1단계: time_table에서 해당 필드 조회
        query_select = f"""
            SELECT {field_name}, count_avg
            FROM time_table
            WHERE course_name = %s
        """
        
        cursor.execute(query_select, (course_name,))
        result = cursor.fetchone()
        
        if result is None:
            # 처음인 경우: 새로운 레코드 삽입
            query_insert = f"""
                INSERT INTO time_table (course_name, {field_name}, count_avg)
                VALUES (%s, %s, 1)
                ON DUPLICATE KEY UPDATE
                {field_name} = VALUES({field_name}),
                count_avg = VALUES(count_avg)
            """
            cursor.execute(query_insert, (course_name, elapsed_minutes))
            logger.info(f"✅ 새로운 코스 '{course_name}' {field_name} 기록: {elapsed_minutes}분")
            return
        
        # ✅ 딕셔너리 또는 튜플 모두 지원
        if isinstance(result, dict):
            existing_avg = result.get(field_name)
            existing_count = result.get("count_avg")
        else:
            existing_avg = result[0]
            existing_count = result[1]
        
        # ✅ NULL 체크
        if existing_avg is None or existing_count is None or existing_count == 0:
            logger.warning(f"⚠️ {field_name} NULL/0 값 감지: avg={existing_avg}, count={existing_count}")
            query_insert = f"""
                INSERT INTO time_table (course_name, {field_name}, count_avg)
                VALUES (%s, %s, 1)
                ON DUPLICATE KEY UPDATE
                {field_name} = VALUES({field_name}),
                count_avg = VALUES(count_avg)
            """
            cursor.execute(query_insert, (course_name, elapsed_minutes))
            logger.info(f"✅ 코스 '{course_name}' {field_name} 새로 기록: {elapsed_minutes}분")
            return
        
        # ========== 🔥 이상치 필터링 로직 ==========
        # 기존 평균의 ±50% 범위 계산
        lower_bound = existing_avg * 0.5
        upper_bound = existing_avg * 1.5
        
        logger.info(f"📊 {field_name} 필터 범위: {lower_bound:.1f}분 ~ {upper_bound:.1f}분")
        logger.info(f"📊 현재 데이터: {elapsed_minutes}분 (기존 평균: {existing_avg}분)")
        
        # 이상치 검사
        if elapsed_minutes < lower_bound or elapsed_minutes > upper_bound:
            logger.warning(f"⚠️ {field_name} 이상치 감지! {elapsed_minutes}분은 범위 [{lower_bound:.1f}, {upper_bound:.1f}]를 벗어남")
            logger.info(f"   - 기존 평균: {existing_avg}분 (횟수: {existing_count})")
            logger.info(f"   - 거부된 값: {elapsed_minutes}분")
            return
        
        logger.info(f"✅ {field_name} 정상 데이터 확인: {elapsed_minutes}분은 유효 범위 내")
        
        # ====================================================
        
        # 새로운 평균 계산
        new_total_time = (existing_avg * existing_count) + elapsed_minutes
        new_count = existing_count + 1
        new_avg = int(new_total_time / new_count)
        
        logger.info(f"코스 '{course_name}' {field_name} 계산:")
        logger.info(f" 기존: {existing_avg}분 (횟수: {existing_count})")
        logger.info(f" 새로운: {elapsed_minutes}분")
        logger.info(f" 업데이트된 평균: {new_avg}분 (횟수: {new_count})")
        
        # 업데이트
        query_update = f"""
            UPDATE time_table
            SET {field_name} = %s, count_avg = %s
            WHERE course_name = %s
        """
        cursor.execute(query_update, (new_avg, new_count, course_name))
        logger.info(f"✅ 코스 '{course_name}' {field_name} 업데이트: {new_avg}분")
        
    except Exception as e:
        logger.error(f"{field_name} 업데이트 실패: {str(e)}", exc_info=True)
        raise


@router.post("/update")
async def update(data: UpdateData):
    """
    Arduino 상태 업데이트 처리
    ✅ first_update가 NULL일 때 감지
    ✅ elapsed_time 음수 필터링
    ✅ count_avg = 0 문제 해결
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
                machine_uuid = db_result.get("machine_uuid")
                
                logger.info(f"DB 조회 완료: current_status={current_status}, machine_uuid={machine_uuid}")
                
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"DB 조회 중 오류: {str(e)}", exc_info=True)
                raise HTTPException(status_code=500, detail=f"DB 조회 실패: {str(e)}")
            
            # ===== 3단계: FINISHED → WASHING 전환 감지 =====
            if current_status == "FINISHED" and data.status == "WASHING":
                logger.info("✅ FINISHED → WASHING 전환 감지! first_update 기록")
                
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
                    
            # ===== 3-1단계: WASHING → SPINNING 전환 감지 (새로 추가!) =====
            if current_status == "WASHING" and data.status == "SPINNING":
                logger.info("✅ WASHING → SPINNING 전환 감지! spinning_update 기록")
                
                try:
                    # spinning_update 기록
                    spinning_update_query = """
                        UPDATE machine_table
                        SET spinning_update = %s
                        WHERE machine_id = %s
                    """
                    cursor.execute(spinning_update_query, (data.timestamp, data.machine_id))
                    logger.info(f"spinning_update 기록 완료: {data.timestamp}")
                    
                except Exception as e:
                    logger.error(f"spinning_update 기록 실패: {str(e)}", exc_info=True)
                
                # 🔥 세탁 시간 계산 및 기록
                try:
                    cursor.execute(
                        """
                        SELECT 
                            UNIX_TIMESTAMP(first_update) as first_timestamp,
                            course_name
                        FROM machine_table
                        WHERE machine_id=%s
                        """,
                        (data.machine_id,)
                    )
                    
                    result = cursor.fetchone()
                    if result and result.get("first_timestamp"):
                        first_timestamp = result.get("first_timestamp")
                        course_name = result.get("course_name")
                        
                        # 세탁 시간 = spinning_update(현재) - first_update
                        washing_time_seconds = int(data.timestamp) - int(first_timestamp)
                        
                        if washing_time_seconds > 0 and course_name:
                            washing_time_minutes = washing_time_seconds // 60
                            logger.info(f"세탁 시간 계산: {data.timestamp} - {first_timestamp} = {washing_time_seconds}초 = {washing_time_minutes}분")
                            update_segment_avg_time(cursor, course_name, washing_time_minutes, "avg_washing_time")
                            logger.info(f"✅ 세탁 시간 업데이트 완료")
                        else:
                            logger.warning(f"⚠️ 세탁 시간 계산 실패: washing_time={washing_time_seconds}초, course_name={course_name}")
                
                except Exception as e:
                    logger.error(f"세탁 시간 계산 실패: {str(e)}", exc_info=True)
                        
            # ===== 4단계: machine_table 상태 업데이트 =====
            try:
                if data.status in ("WASHING", "SPINNING", "FINISHED"):
                    logger.info(f"상태 업데이트 시작: {data.status}")
                    
                    if data.status == "FINISHED":
                        logger.info("✅ FINISHED 상태: last_update 갱신")
                        current_time_int = int(datetime.now(KST).timestamp())
                        logger.info(f"현재 시간 (timestamp): {current_time_int}")
                        
                        if data.battery is not None:
                            query = """
                            UPDATE machine_table
                            SET status=%s, battery=%s, timestamp=%s, last_update=%s
                            WHERE machine_id=%s
                            """
                            cursor.execute(query, (data.status, data.battery, data.timestamp, current_time_int, data.machine_id))
                        else:
                            query = """
                            UPDATE machine_table
                            SET status=%s, timestamp=%s, last_update=%s
                            WHERE machine_id=%s
                            """
                            cursor.execute(query, (data.status, data.timestamp, current_time_int, data.machine_id))
                    else:
                        if data.battery is not None:
                            query = """
                            UPDATE machine_table
                            SET status=%s, battery=%s, timestamp=%s
                            WHERE machine_id=%s
                            """
                            cursor.execute(query, (data.status, data.battery, data.timestamp, data.machine_id))
                        else:
                            query = """
                            UPDATE machine_table
                            SET status=%s, timestamp=%s
                            WHERE machine_id=%s
                            """
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
                    
                    # ✅ SELECT에서 UNIX_TIMESTAMP 사용
                    cursor.execute(
                        """
                        SELECT 
                        UNIX_TIMESTAMP(first_update) as first_timestamp,
                        last_update as last_timestamp,
                        spinning_update,
                        course_name
                        FROM machine_table 
                        WHERE machine_id=%s
                        """,
                        (data.machine_id,)
                    )
                    
                    result = cursor.fetchone()
                    
                    if result is None:
                        logger.error(f"machine_id {data.machine_id}를 찾을 수 없습니다")
                        raise HTTPException(status_code=404, detail="Machine not found")
                    
                    first_timestamp = result.get("first_timestamp")
                    spinning_update = result.get("spinning_update")
                    last_timestamp = result.get("last_timestamp")
                    course_name = result.get("course_name")
                    
                    logger.info(f"코스명: {course_name}")
                    logger.info(f"first_timestamp (세탁 시작): {first_timestamp}")
                    logger.info(f"spinning_update (탈수 시작): {spinning_update}")  # 🔥 새로 추가
                    logger.info(f"last_timestamp (종료): {last_timestamp}")
                    
                    if (spinning_update is not None and 
                        last_timestamp is not None and 
                        course_name is not None):
                        
                        spinning_time_seconds = int(last_timestamp) - int(spinning_update)
                        
                        if spinning_time_seconds > 0:
                            spinning_time_minutes = spinning_time_seconds // 60
                            logger.info(f"탈수 시간 계산: {last_timestamp} - {spinning_update} = {spinning_time_seconds}초 = {spinning_time_minutes}분")
                            update_segment_avg_time(cursor, course_name, spinning_time_minutes, "avg_spinning_time")
                            logger.info(f"✅ 탈수 시간 기록 완료")
                        else:
                            logger.warning(f"⚠️ 탈수 시간 계산 실패: spinning_time={spinning_time_seconds}초")
                    else:
                        logger.warning(f"⚠️ 탈수 시간 계산 필수 데이터 누락 (스킵)")
                        logger.warning(f"   spinning_update={spinning_update}, last_timestamp={last_timestamp}, course_name={course_name}")
                    
                    # ✅ 강화된 유효성 검사
                    if (first_timestamp is not None and 
                        last_timestamp is not None and 
                        course_name is not None and
                        isinstance(first_timestamp, (int, float)) and
                        isinstance(last_timestamp, (int, float))):
                        try:
                            # ✅ 소요 시간 계산
                            elapsed_time = int(last_timestamp) - int(first_timestamp)
                            
                            logger.info(f"elapsed_time: {int(last_timestamp)} - {int(first_timestamp)} = {elapsed_time}초")
                            
                            # ✅ 음수 체크 (가장 중요!)
                            if elapsed_time < 0:
                                logger.error(f"❌ 음수 시간 발생: {elapsed_time}초")
                                logger.error(f"   first_ts: {first_timestamp} ({datetime.fromtimestamp(first_timestamp, tz=pytz.UTC).astimezone(KST) if first_timestamp else 'N/A'})")
                                logger.error(f"   last_ts: {last_timestamp} ({datetime.fromtimestamp(last_timestamp, tz=pytz.UTC).astimezone(KST) if last_timestamp else 'N/A'})")
                                logger.warning("⚠️ 음수 시간이므로 코스 시간 기록 스킵")
                                elapsed_time = None
                            
                            elif elapsed_time == 0:
                                logger.warning("⚠️ 0초 감지, 기록하지 않음")
                                elapsed_time = None
                            
                            else:
                                logger.info(f"✅ 유효한 시간: {elapsed_time}초 ({elapsed_time // 60}분 {elapsed_time % 60}초)")
                            
                            # ✅ 유효한 시간만 기록 (함수 내에서도 체크!)
                            if elapsed_time is not None and elapsed_time > 0:
                                update_course_avg_time(cursor, course_name, elapsed_time)
                                logger.info(f"✅ {course_name} 평균 시간 업데이트 완료")
                            else:
                                logger.warning(f"⚠️ 코스 시간 기록 스킵: elapsed_time={elapsed_time}")
                        
                        except Exception as e:
                            logger.error(f"코스별 시간 계산 중 오류: {str(e)}", exc_info=True)
                    
                    else:
                        logger.warning("필수 데이터 누락 또는 타입 오류:")
                        logger.warning(f"  first_timestamp={first_timestamp}")
                        logger.warning(f"  last_timestamp={last_timestamp}")
                        logger.warning(f"  course_name={course_name}")
                    
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
                    
                    # ✅ 혼잡도 업데이트
                    if (first_timestamp is not None and 
                        last_timestamp is not None and
                        isinstance(first_timestamp, (int, float)) and
                        isinstance(last_timestamp, (int, float)) and
                        (int(last_timestamp) - int(first_timestamp)) > 0):  # ← 양수만!
                        try:
                            update_congestion_for_range(cursor, int(first_timestamp), int(last_timestamp))
                            logger.info("혼잡도 업데이트 완료")
                        except Exception as e:
                            logger.error(f"혼잡도 업데이트 실패: {str(e)}", exc_info=True)
                    else:
                        logger.warning("혼잡도 업데이트 스킵: timestamp 정보 부족 또는 음수")
                    
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
    