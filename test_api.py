import requests
import json
import time

BASEURL = "https://unconical-kyong-frolicsome.ngrok-free.dev"

def print_section(title):
    print(f"\n{'='*60}\n{title}\n{'='*60}")

def print_success(msg):
    print(f"\033[92m{msg}\033[0m")

def print_error(msg):
    print(f"\033[91m{msg}\033[0m")

def print_info(msg):
    print(f"\033[94m{msg}\033[0m")

def make_request(method, endpoint, data=None):
    url = f"{BASEURL}/{endpoint}"
    try:
        if method.upper() == "GET":
            response = requests.get(url, params=data)
        elif method.upper() == "POST":
            response = requests.post(url, json=data)
        else:
            print_error(f"HTTP method {method} not supported")
            return None

        print_info(f"{method} {endpoint} - Status {response.status_code}")
        if 200 <= response.status_code < 300:
            result = response.json()
            print_success(json.dumps(result, ensure_ascii=False, indent=2))
            return result
        else:
            print_error(response.text)
            return None
    except Exception as e:
        print_error(str(e))
        return None

def test_register_device(machine_id: int):
    print_section(f"2. 기기 등록: machine_id={machine_id}")
    # machine_name, room_id 없이 등록 (서버 스키마/모델에 맞춤)
    data = {
        "machine_id": machine_id,
        "battery_capacity": 100
    }
    return make_request("POST", "register_device", data=data)

if __name__ == "__main__":
    # 원하는 기기 번호로 테스트
    test_register_device(2)
