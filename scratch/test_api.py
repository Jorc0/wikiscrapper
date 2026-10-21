import requests
try:
    r = requests.get("http://localhost:5000/api/files/Acanthaceae")
    print(f"Status Code: {r.status_code}")
    print(r.text[:1000])
except Exception as e:
    print(f"Error: {e}")
