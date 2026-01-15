import requests
import time
import secrets

BASE_URL = "http://localhost:8000/api/v1"

def test_auth_flow():
    email = f"test_{secrets.token_hex(4)}@example.com"
    password = "testpassword123"
    
    print(f"--- Testing with user: {email} ---")
    
    # 1. Register
    print("\n1. Registering user...")
    register_payload = {
        "email": email,
        "password": password
    }
    resp = requests.post(f"{BASE_URL}/auth/register", json=register_payload)
    print(f"Status: {resp.status_code}")
    if resp.status_code != 200:
        print(f"Error: {resp.text}")
        return
    print("Success!")
    
    # 2. Login
    print("\n2. Logging in...")
    login_data = {
        "username": email,
        "password": password
    }
    resp = requests.post(f"{BASE_URL}/auth/login", data=login_data)
    print(f"Status: {resp.status_code}")
    if resp.status_code != 200:
        print(f"Error: {resp.text}")
        return
    token = resp.json()["access_token"]
    print(f"Token acquired: {token[:20]}...")
    
    # 3. Access secured endpoint without token
    print("\n3. Accessing secured chat without token...")
    chat_payload = {
        "session_id": "test_session",
        "prompt": "Hello",
        "model": "gemini-2.5-flash"
    }
    resp = requests.post(f"{BASE_URL}/chat/", json=chat_payload)
    print(f"Status: {resp.status_code} (Expected 401)")
    
    # 4. Access secured endpoint with token
    print("\n4. Accessing secured chat with token...")
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.post(f"{BASE_URL}/chat/", json=chat_payload, headers=headers)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        print(f"Reply: {resp.json()['reply'][:50]}...")
    else:
        print(f"Error: {resp.text}")

if __name__ == "__main__":
    try:
        test_auth_flow()
    except Exception as e:
        print(f"Failed to connect to server: {e}")
        print("Make sure the server is running on http://localhost:8000")
