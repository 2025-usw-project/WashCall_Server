from dotenv import load_dotenv
load_dotenv()
import mysql.connector
from mysql.connector import Error, pooling
from contextlib import contextmanager
import os

# MySQL 데이터베이스 설정 (.env 기반 유지)
DB_CONFIG = {
    'host': os.getenv('DB_HOST', '127.0.0.1'),
    'port': int(os.getenv('DB_PORT', '3306')),
    'user': os.getenv('DB_USER', 'root'),
    'password': os.getenv('DB_PASSWORD', ''),
    'database': os.getenv('DB_NAME', 'washing_machine_db'),
    'charset': os.getenv('DB_CHARSET', 'utf8mb4'),
    'collation': os.getenv('DB_COLLATION', 'utf8mb4_unicode_ci'),
    'autocommit': False,
    'connection_timeout': int(os.getenv('DB_CONN_TIMEOUT', '5')),
}

# 커넥션 풀은 지연 초기화: 최초 연결 시도 때 생성, 실패 시 단일 연결로 폴백
connection_pool = None

def _init_pool_if_possible():
    global connection_pool
    if connection_pool is not None:
        return
    try:
        connection_pool = pooling.MySQLConnectionPool(
            pool_name="laundry_pool",
            pool_size=5,
            pool_reset_session=True,
            **DB_CONFIG,
        )
        print("✓ MySQL 연결 풀 생성 성공")
    except Error as e:
        # 풀 생성 실패 시 폴백: 이후 단일 연결 사용
        connection_pool = None
        print(f"✗ 연결 풀 생성 실패: {e}")
        print("   직접 연결 방식으로 fallback됩니다.")


@contextmanager
def get_db_connection():
    """데이터베이스 연결을 관리하는 context manager"""
    connection = None
    try:
        if connection_pool is None:
            _init_pool_if_possible()

        if connection_pool is not None:
            connection = connection_pool.get_connection()
        else:
            connection = mysql.connector.connect(**DB_CONFIG)

        if connection and connection.is_connected():
            try:
                # 연결이 유효한지 확인하고, 끊겼다면 재연결 시도
                connection.ping(reconnect=True, attempts=1, delay=0)
            except Exception:
                pass
            yield connection
        else:
            raise Error("Database connection is not active")
    except Error as e:
        print(f"Database connection error: {e}")
        raise
    finally:
        if connection and connection.is_connected():
            connection.close()


def execute_query(query: str, params: tuple = None, fetch: bool = False):
    """쿼리 실행 헬퍼 함수"""
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True, buffered=True)
        try:
            cursor.execute(query, params or ())

            if fetch:
                result = cursor.fetchall()
                return result
            else:
                conn.commit()
                return cursor.lastrowid
        finally:
            try:
                cursor.close()
            except Exception:
                pass
