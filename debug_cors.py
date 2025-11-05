#!/usr/bin/env python3
"""
CORS 헤더 디버깅 스크립트
서버가 실제로 어떤 헤더를 보내는지 확인합니다.
"""

import requests

def check_cors_headers(url):
    """서버의 CORS 헤더 확인"""
    print(f"🔍 서버 CORS 헤더 확인: {url}")
    print("=" * 60)
    
    try:
        # OPTIONS 요청 (CORS Preflight)
        print("\n1️⃣ OPTIONS 요청 (Preflight):")
        response = requests.options(
            url,
            headers={
                'Origin': 'https://washcall.space',
                'Access-Control-Request-Method': 'POST',
                'Access-Control-Request-Headers': 'Content-Type,Authorization'
            }
        )
        
        print(f"   상태 코드: {response.status_code}")
        cors_headers = {k: v for k, v in response.headers.items() 
                       if 'access-control' in k.lower()}
        
        if cors_headers:
            for key, value in cors_headers.items():
                print(f"   {key}: {value}")
                # 중복 확인
                if ', ' in value or value.count('*') > 1:
                    print(f"   ⚠️ 경고: '{key}' 헤더에 중복된 값이 있습니다!")
        else:
            print("   ❌ CORS 헤더 없음")
        
        # POST 요청
        print("\n2️⃣ POST 요청:")
        response = requests.post(
            url,
            json={"test": "data"},
            headers={
                'Origin': 'https://washcall.space',
                'Content-Type': 'application/json'
            }
        )
        
        print(f"   상태 코드: {response.status_code}")
        cors_headers = {k: v for k, v in response.headers.items() 
                       if 'access-control' in k.lower()}
        
        if cors_headers:
            for key, value in cors_headers.items():
                print(f"   {key}: {value}")
                # 중복 확인
                if ', ' in value or value.count('*') > 1:
                    print(f"   ⚠️ 경고: '{key}' 헤더에 중복된 값이 있습니다!")
        else:
            print("   ❌ CORS 헤더 없음")
            
    except Exception as e:
        print(f"   ❌ 오류 발생: {e}")
    
    print("\n" + "=" * 60)


if __name__ == "__main__":
    # 테스트할 서버 URL
    servers = [
        "https://server.washcall.space/login",
        "https://server.washcall.space/health"
    ]
    
    for server_url in servers:
        check_cors_headers(server_url)
        print()

