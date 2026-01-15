import requests
import time

BASE_URL = "http://localhost:8000/test-limit"

def test_rate_limit():
    print(f"--- Testing Rate Limit on {BASE_URL} ---")
    print("Limit is set to 3/minute")

    for i in range(1, 6):
        print(f"\nRequest #{i}...")
        try:
            # GET request
            response = requests.get(BASE_URL)
            
            print(f"Status: {response.status_code}")
            
            if response.status_code == 429:
                print("✅ Rate Limit Hit! (Expected)")
                print(f"Response: {response.text}")
                break
            elif response.status_code == 200:
                print("✅ Request OK")
            else:
                print(f"Response: {response.text}")
                
        except Exception as e:
            print(f"Error: {e}")
        
        # Pequeña pausa
        time.sleep(0.5)

if __name__ == "__main__":
    test_rate_limit()
