import requests
import json
import time

# 서버 URL (로컬 테스트)
base_url = "https://unconical-kyong-frolicsome.ngrok-free.dev"

def register_device():
    """기기 등록"""
    url = f"{base_url}/register_device"
    data = {
        "machine_id": 2,
        "room_id": 102,
        "machine_name": "세탁기B",
        "battery_capacity": 100
    }
    
    response = requests.post(url, json=data)
    print(f"[등록] Status: {response.status_code}, Response: {response.json()}")


def send_update_data():
    """업데이트 데이터 전송"""
    url = f"{base_url}/update"
    data = {
        "machine_id": 2,
        "status": "WASHING",
        "battery": 85,
        "last_update": int(time.time()),
        "washing_standard": 2.7,
        "spinning_standard": 1.9
    }
    
    response = requests.post(url, json=data)
    print(f"[업데이트] Status: {response.status_code}, Response: {response.json()}")


def request_device_update():
    """평균값 조회"""
    url = f"{base_url}/device_update"
    data = {
        "machine_id": 2,
        "timestamp": int(time.time())
    }
    
    response = requests.post(url, json=data)
    print(f"[평균값 조회] Status: {response.status_code}, Response: {response.json()}")


if __name__ == "__main__":
    print("=== FastAPI 서버 테스트 시작 ===\n")
    
    # 1. 기기 등록
    register_device()
    time.sleep(1)
    
    # 2. 데이터 업데이트 (여러 번)
    for i in range(3):
        send_update_data()
        time.sleep(1)
    
    # 3. 평균값 조회
    request_device_update()
