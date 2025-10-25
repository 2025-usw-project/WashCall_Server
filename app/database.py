import mysql.connector
from mysql.connector import Error
from contextlib import contextmanager
from typing import Optional

# MySQL 데이터베이스 설정
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',      # MySQL 사용자명으로 변경
    'password': 'su1004',  # MySQL 비밀번호로 변경
    'database': 'washing_machine_db',
    'charset': 'utf8mb4',
    'collation': 'utf8mb4_unicode_ci'
}


@contextmanager
def get_db_connection():
    """데이터베이스 연결을 관리하는 context manager"""
    connection = None
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        yield connection
    except Error as e:
        print(f"Database connection error: {e}")
        raise
    finally:
        if connection and connection.is_connected():
            connection.close()


def execute_query(query: str, params: tuple = None, fetch: bool = False):
    """쿼리를 실행하고 결과를 반환하는 헬퍼 함수"""
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(query, params or ())
        
        if fetch:
            result = cursor.fetchall()
            return result
        else:
            conn.commit()
            return cursor.lastrowid
