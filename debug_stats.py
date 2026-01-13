import requests
import json

BASE_URL = "http://127.0.0.1:5000"
LOGIN_URL = f"{BASE_URL}/login"
STATS_URL = f"{BASE_URL}/api/admin/stats"

# 1. Login
session = requests.Session()
# First get CSRF token if needed? No, standard form login.
# Check what login needs.
# Viewing login.html... it sends POST with 'password'.
# Check app.py for login route
pass

# I'll just try with default password (likely '1234' or '0000' or whatever I set previously. Or I can check config)
# app.py L150~
# It checks against 'admin_password' setting. Default '1234'.

admin_pw = 'admin123!' # Default from app.py

response = session.post(LOGIN_URL, data={'password': admin_pw})
print(f"Login Status: {response.status_code}")

# Check if logged in (session cookie should be set)
# Try accessing stats
stats_res = session.get(STATS_URL)
print(f"Stats Status: {stats_res.status_code}")

if stats_res.status_code == 200:
    try:
        data = stats_res.json()
        print("Stats Data JSON:")
        print(json.dumps(data, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"JSON Parse Error: {e}")
        print(stats_res.text)
else:
    print("Failed to access stats")
