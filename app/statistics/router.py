"""
통계 API: 세탁실 혼잡도 분석 (개선 버전)
- status=FINISHED일 때 busy_table 자동 업데이트 (INSERT 또는 UPDATE)
- GET /statistics/congestion: 요일별/시간대별 혼잡도 조회
"""

from fastapi import APIRouter, HTTPException
from datetime import datetime
import pytz

from app.database import get_db_connection

router = APIRouter()

# 요일 매핑
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


async def update_busy_statistics(machine_id: int, timestamp: int):
    """
    status가 FINISHED가 되었을 때 호출
    새로운 값이 들어오면 자동으로 INSERT 또는 UPDATE
    """
    try:
        day_str, hour = timestamp_to_weekday_hour(timestamp)

        with get_db_connection() as conn:
            cursor = conn.cursor()

            # ✅ INSERT ... ON DUPLICATE KEY UPDATE
            # 같은 (busy_day, busy_time)이 이미 있으면 UPDATE
            # 없으면 INSERT
            query = """
            INSERT INTO busy_table (busy_day, busy_time, busy_count)
            VALUES (%s, %s, 1)
            ON DUPLICATE KEY UPDATE
                busy_count = busy_count + 1,
                updated_at = CURRENT_TIMESTAMP
            """

            cursor.execute(query, (day_str, hour))
            conn.commit()

            return {"message": "busy_table updated", "day": day_str, "hour": hour, "affected_rows": cursor.rowcount}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Update failed: {str(e)}")


@router.get("/congestion")
async def get_congestion():
    """
    GET /statistics/congestion

    응답: 
    {
        "월": [0, 1, 2, ..., 0],  // 24개의 시간대별 count
        "화": [...],
        ...
        "일": [...]
    }
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor(dictionary=True)

            query = """
            SELECT busy_day, busy_time, busy_count
            FROM busy_table
            ORDER BY 
                FIELD(busy_day, '월', '화', '수', '목', '금', '토', '일'),
                busy_time ASC
            """
            cursor.execute(query)
            rows = cursor.fetchall()

            # 결과를 딕셔너리로 정렬
            result = {
                '월': [0] * 24,
                '화': [0] * 24,
                '수': [0] * 24,
                '목': [0] * 24,
                '금': [0] * 24,
                '토': [0] * 24,
                '일': [0] * 24,
            }

            for row in rows:
                day = row['busy_day']
                hour = row['busy_time']
                count = row['busy_count']
                result[day][hour] = count

            return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")


@router.get("/congestion_summary")
async def get_congestion_summary():
    """
    GET /statistics/congestion_summary
    혼잡도 요약 정보
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor(dictionary=True)

            query = """
            SELECT 
                busy_day,
                busy_time,
                busy_count
            FROM busy_table
            ORDER BY busy_day, busy_time
            """
            cursor.execute(query)
            rows = cursor.fetchall()

            # 요일별 분석
            days_order = ['월', '화', '수', '목', '금', '토', '일']
            result = {
                'peak_times': {},
                'peak_counts': {},
                'average_counts': {},
                'total_usage': 0
            }

            for day in days_order:
                day_data = [r['busy_count'] for r in rows if r['busy_day'] == day]
                if day_data:
                    max_count = max(day_data)
                    peak_hour = day_data.index(max_count)
                    avg_count = sum(day_data) / len(day_data)
                    day_total = sum(day_data)

                    result['peak_times'][day] = peak_hour
                    result['peak_counts'][day] = max_count
                    result['average_counts'][day] = round(avg_count, 2)
                    result['total_usage'] += day_total

            return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")


@router.get("/congestion_detail/{day}")
async def get_congestion_detail(day: str):
    """
    GET /statistics/congestion_detail/{day}
    특정 요일의 상세 혼잡도 정보
    """
    try:
        valid_days = ['월', '화', '수', '목', '금', '토', '일']
        if day not in valid_days:
            raise HTTPException(status_code=400, detail=f"Invalid day. Must be one of {valid_days}")

        with get_db_connection() as conn:
            cursor = conn.cursor(dictionary=True)

            query = """
            SELECT busy_time, busy_count
            FROM busy_table
            WHERE busy_day = %s
            ORDER BY busy_time ASC
            """
            cursor.execute(query, (day,))
            rows = cursor.fetchall()

            if not rows:
                raise HTTPException(status_code=404, detail=f"No data found for day: {day}")

            # 데이터 정리
            hourly_data = []
            counts = []

            for row in rows:
                hourly_data.append({
                    "hour": row['busy_time'],
                    "count": row['busy_count']
                })
                counts.append(row['busy_count'])

            peak_count = max(counts)
            peak_hour = counts.index(peak_count)
            avg_count = sum(counts) / len(counts)
            total_count = sum(counts)

            return {
                "day": day,
                "hourly_data": hourly_data,
                "peak_hour": peak_hour,
                "peak_count": peak_count,
                "average_count": round(avg_count, 2),
                "total_count": total_count
            }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")


@router.post("/reset_busy_table")
async def reset_busy_table():
    """
    POST /statistics/reset_busy_table
    혼잡도 데이터 초기화
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            query = "UPDATE busy_table SET busy_count = 0"
            cursor.execute(query)
            conn.commit()

            return {"message": "busy_table reset successfully", "rows_affected": cursor.rowcount}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reset failed: {str(e)}")
