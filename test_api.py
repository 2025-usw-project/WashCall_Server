"""
Laundry API 통합 테스트 스크립트
Arduino와 Android 서비스의 모든 엔드포인트를 테스트합니다.
"""

import requests
import json
import time
from typing import Dict, Any, Optional
from datetime import datetime

# ========================================
# 설정
# ========================================
# 서버 URL 설정 (환경에 맞게 변경)
# BASE_URL = "http://localhost:8000"
BASE_URL = "https://unconical-kyong-frolicsome.ngrok-free.dev"

# 테스트용 머신 ID
TEST_MACHINE_IDS = [1, 2, 3]

# 색상 출력을 위한 ANSI 코드
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    END = '\033[0m'
    BOLD = '\033[1m'


# ========================================
# 유틸리티 함수
# ========================================
def print_section(title: str):
    """섹션 제목 출력"""
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'='*60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.CYAN}{title:^60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'='*60}{Colors.END}\n")


def print_success(message: str):
    """성공 메시지 출력"""
    print(f"{Colors.GREEN}✓ {message}{Colors.END}")


def print_error(message: str):
    """에러 메시지 출력"""
    print(f"{Colors.RED}✗ {message}{Colors.END}")


def print_info(message: str):
    """정보 메시지 출력"""
    print(f"{Colors.BLUE}ℹ {message}{Colors.END}")


def print_warning(message: str):
    """경고 메시지 출력"""
    print(f"{Colors.YELLOW}⚠ {message}{Colors.END}")


def make_request(method: str, endpoint: str, data: Optional[Dict] = None, 
                 params: Optional[Dict] = None) -> Optional[Dict]:
    """
    HTTP 요청을 보내고 결과를 반환
    
    Args:
        method: HTTP 메소드 (GET, POST, PUT, DELETE)
        endpoint: API 엔드포인트
        data: 요청 본문 데이터
        params: 쿼리 파라미터
    
    Returns:
        응답 JSON 또는 None
    """
    url = f"{BASE_URL}{endpoint}"
    
    try:
        if method.upper() == "GET":
            response = requests.get(url, params=params)
        elif method.upper() == "POST":
            response = requests.post(url, json=data)
        elif method.upper() == "PUT":
            response = requests.put(url, json=data)
        elif method.upper() == "DELETE":
            response = requests.delete(url)
        else:
            print_error(f"지원하지 않는 HTTP 메소드: {method}")
            return None
        
        print_info(f"{method} {endpoint} - Status: {response.status_code}")
        
        if response.status_code >= 200 and response.status_code < 300:
            result = response.json()
            print_success(f"응답: {json.dumps(result, ensure_ascii=False, indent=2)}")
            return result
        else:
            print_error(f"에러 응답: {response.text}")
            return None
            
    except requests.exceptions.RequestException as e:
        print_error(f"요청 실패: {str(e)}")
        return None
    except json.JSONDecodeError:
        print_error("JSON 파싱 실패")
        return None


# ========================================
# 테스트 함수들
# ========================================

def test_health_check():
    """서버 헬스 체크"""
    print_section("1. 헬스 체크")
    result = make_request("GET", "/health")
    return result is not None


def test_register_device(machine_id: int):
    """기기 등록 테스트"""
    print_section(f"2. 기기 등록 (machine_id: {machine_id})")
    
    data = {
        "machine_id": machine_id,
        "room_id": 100 + machine_id,
        "machine_name": f"세탁기{chr(64 + machine_id)}",
        "battery_capacity": 100
    }
    
    result = make_request("POST", "/register_device", data=data)
    return result is not None


def test_send_device_data(machine_id: int):
    """기기 데이터 전송 테스트"""
    print_section(f"3. 기기 데이터 전송 (machine_id: {machine_id})")
    
    data = {
        "machine_id": machine_id,
        "machine_type": "washing",
        "status": "WASHING",
        "battery": 85,
        "last_update": int(time.time())
    }
    
    result = make_request("POST", "/devices", data=data)
    return result is not None


def test_update_with_standards(machine_id: int, washing: float, spinning: float):
    """기준값 포함 업데이트 테스트"""
    print_section(f"4. 업데이트 (machine_id: {machine_id})")
    
    data = {
        "machine_id": machine_id,
        "status": "WASHING",
        "battery": 80,
        "last_update": int(time.time()),
        "washing_standard": washing,
        "spinning_standard": spinning
    }
    
    result = make_request("POST", "/update", data=data)
    return result is not None


def test_device_update(machine_id: int):
    """평균값 조회 및 업데이트 테스트"""
    print_section(f"5. 평균값 조회 (machine_id: {machine_id})")
    
    data = {
        "machine_id": machine_id,
        "timestamp": int(time.time())
    }
    
    result = make_request("POST", "/device_update", data=data)
    return result


def test_get_all_devices():
    """전체 기기 조회 테스트"""
    print_section("6. 전체 기기 목록 조회")
    
    result = make_request("GET", "/all_devices")
    
    if result and "devices" in result:
        print_info(f"총 {len(result['devices'])}개의 기기가 등록되어 있습니다.")
        for device in result['devices']:
            print(f"  - ID: {device.get('machine_id')}, "
                  f"UUID: {device.get('machine_uuid')}, "
                  f"이름: {device.get('machine_name')}, "
                  f"상태: {device.get('status')}, "
                  f"배터리: {device.get('battery')}%")
    
    return result


def test_get_device_by_id(machine_id: int):
    """특정 기기 조회 테스트"""
    print_section(f"7. 특정 기기 조회 (machine_id: {machine_id})")
    
    result = make_request("GET", f"/device/{machine_id}")
    return result


def test_get_standards_history(machine_id: int, limit: int = 5):
    """기준값 이력 조회 테스트"""
    print_section(f"8. 기준값 이력 조회 (machine_id: {machine_id})")
    
    result = make_request("GET", f"/standards/{machine_id}", params={"limit": limit})
    
    if result and "standards" in result:
        print_info(f"총 {result['count']}개의 기록이 있습니다.")
        for std in result['standards']:
            print(f"  - UUID: {std.get('machine_uuid')}, "
                  f"세탁: {std.get('washing_standard'):.2f}, "
                  f"탈수: {std.get('spinning_standard'):.2f}, "
                  f"시간: {std.get('created_at')}")
    
    return result


# ========================================
# 시나리오 테스트
# ========================================

def scenario_single_machine_workflow(machine_id: int):
    """단일 머신 전체 워크플로우 테스트"""
    print_section(f"📱 시나리오: 세탁기 {machine_id} 전체 워크플로우")
    
    results = []
    
    # 1. 기기 등록
    print_info("Step 1: 기기 등록")
    results.append(test_register_device(machine_id))
    time.sleep(0.5)
    
    # 2. 기기 데이터 전송
    print_info("Step 2: 기기 상태 전송")
    results.append(test_send_device_data(machine_id))
    time.sleep(0.5)
    
    # 3. 여러 번 업데이트 (기준값 축적)
    print_info("Step 3: 세탁 데이터 수집 (5회)")
    for i in range(5):
        washing_val = 2.5 + (i * 0.1)
        spinning_val = 1.8 + (i * 0.1)
        results.append(test_update_with_standards(machine_id, washing_val, spinning_val))
        time.sleep(0.3)
    
    # 4. 평균값 계산 및 조회
    print_info("Step 4: 평균값 계산")
    avg_result = test_device_update(machine_id)
    results.append(avg_result is not None)
    time.sleep(0.5)
    
    # 5. 기준값 이력 확인
    print_info("Step 5: 기준값 이력 확인")
    results.append(test_get_standards_history(machine_id, limit=10))
    time.sleep(0.5)
    
    # 6. 기기 정보 확인
    print_info("Step 6: 기기 상세 정보 확인")
    results.append(test_get_device_by_id(machine_id))
    
    # 결과 요약
    success_count = sum(1 for r in results if r)
    total_count = len(results)
    
    print(f"\n{Colors.BOLD}결과: {success_count}/{total_count} 성공{Colors.END}")
    
    return success_count == total_count


def scenario_multiple_machines():
    """여러 머신 동시 테스트"""
    print_section("🏭 시나리오: 여러 세탁기 동시 운영")
    
    # 1. 여러 기기 등록
    print_info("여러 기기 등록 중...")
    for machine_id in TEST_MACHINE_IDS:
        test_register_device(machine_id)
        time.sleep(0.3)
    
    # 2. 각 기기에 데이터 전송
    print_info("각 기기에 데이터 전송 중...")
    for machine_id in TEST_MACHINE_IDS:
        washing = 2.5 + (machine_id * 0.2)
        spinning = 1.8 + (machine_id * 0.1)
        test_update_with_standards(machine_id, washing, spinning)
        time.sleep(0.3)
    
    # 3. 전체 기기 상태 확인
    test_get_all_devices()
    
    # 4. 각 기기의 평균값 계산
    print_info("각 기기의 평균값 계산 중...")
    for machine_id in TEST_MACHINE_IDS:
        test_device_update(machine_id)
        time.sleep(0.3)
    
    # 5. 최종 상태 확인
    test_get_all_devices()


def scenario_stress_test(machine_id: int, iterations: int = 10):
    """스트레스 테스트 - 반복적인 데이터 전송"""
    print_section(f"⚡ 시나리오: 스트레스 테스트 ({iterations}회 반복)")
    
    start_time = time.time()
    success_count = 0
    
    for i in range(iterations):
        washing = 2.0 + (i % 5) * 0.2
        spinning = 1.5 + (i % 5) * 0.15
        
        if test_update_with_standards(machine_id, washing, spinning):
            success_count += 1
        
        time.sleep(0.1)
    
    elapsed_time = time.time() - start_time
    
    print(f"\n{Colors.BOLD}스트레스 테스트 결과:{Colors.END}")
    print(f"  - 성공: {success_count}/{iterations}")
    print(f"  - 소요 시간: {elapsed_time:.2f}초")
    print(f"  - 평균 응답 시간: {elapsed_time/iterations:.3f}초")


# ========================================
# 메인 테스트 실행
# ========================================

def run_all_tests():
    """모든 테스트 실행"""
    print(f"\n{Colors.BOLD}{Colors.MAGENTA}")
    print("╔════════════════════════════════════════════════════════════╗")
    print("║          Laundry API 통합 테스트 시작                      ║")
    print("║          서버: " + BASE_URL.ljust(41) + "║")
    print("║          시간: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S").ljust(41) + "║")
    print("╚════════════════════════════════════════════════════════════╝")
    print(f"{Colors.END}\n")
    
    # 테스트 결과 저장
    test_results = {}
    
    try:
        # 1. 헬스 체크
        test_results['health_check'] = test_health_check()
        time.sleep(1)
        
        # 2. 단일 머신 워크플로우
        test_results['single_workflow'] = scenario_single_machine_workflow(TEST_MACHINE_IDS[0])
        time.sleep(1)
        
        # 3. 여러 머신 동시 테스트
        scenario_multiple_machines()
        time.sleep(1)
        
        # 4. 스트레스 테스트
        scenario_stress_test(TEST_MACHINE_IDS[0], iterations=20)
        
    except KeyboardInterrupt:
        print_warning("\n\n테스트가 사용자에 의해 중단되었습니다.")
    except Exception as e:
        print_error(f"\n\n예상치 못한 에러 발생: {str(e)}")
    finally:
        # 최종 결과 출력
        print_section("📊 최종 테스트 결과")
        
        total_tests = len(test_results)
        passed_tests = sum(1 for result in test_results.values() if result)
        
        print(f"{Colors.BOLD}총 테스트: {total_tests}{Colors.END}")
        print(f"{Colors.GREEN}성공: {passed_tests}{Colors.END}")
        print(f"{Colors.RED}실패: {total_tests - passed_tests}{Colors.END}")
        
        if passed_tests == total_tests:
            print(f"\n{Colors.GREEN}{Colors.BOLD}✓ 모든 테스트 통과!{Colors.END}")
        else:
            print(f"\n{Colors.RED}{Colors.BOLD}✗ 일부 테스트 실패{Colors.END}")
        
        print(f"\n{Colors.MAGENTA}{'='*60}{Colors.END}\n")


# ========================================
# 개별 테스트 실행 함수
# ========================================

def run_quick_test():
    """빠른 테스트 (기본 기능만)"""
    print_section("⚡ 빠른 테스트")
    
    test_health_check()
    time.sleep(0.5)
    
    machine_id = 99
    test_register_device(machine_id)
    time.sleep(0.5)
    
    test_update_with_standards(machine_id, 2.5, 1.8)
    time.sleep(0.5)
    
    test_device_update(machine_id)
    time.sleep(0.5)
    
    test_get_device_by_id(machine_id)


if __name__ == "__main__":
    import sys
    
    # 명령줄 인자 처리
    if len(sys.argv) > 1:
        if sys.argv[1] == "quick":
            run_quick_test()
        elif sys.argv[1] == "stress":
            iterations = int(sys.argv[2]) if len(sys.argv) > 2 else 50
            scenario_stress_test(TEST_MACHINE_IDS[0], iterations)
        elif sys.argv[1] == "workflow":
            machine_id = int(sys.argv[2]) if len(sys.argv) > 2 else TEST_MACHINE_IDS[0]
            scenario_single_machine_workflow(machine_id)
        else:
            print_error(f"알 수 없는 명령: {sys.argv[1]}")
            print_info("사용법: python test_api.py [quick|stress|workflow]")
    else:
        # 기본: 전체 테스트 실행
        run_all_tests()
