import requests

# Test the thumbnail endpoint
r = requests.get("http://localhost:5000/api/thumbnail/Achatocarpaceae/Achatocarpus.PNG")
print(f"Thumbnail Status: {r.status_code}")

# Test the image endpoint
r2 = requests.get("http://localhost:5000/api/image/Achatocarpaceae/Achatocarpus.PNG")
print(f"Image Status: {r2.status_code}")

# Test the files endpoint - look for Achatocarpus.PNG entry
r3 = requests.get("http://localhost:5000/api/files/Achatocarpaceae")
data = r3.json()
files = data.get("files", [])
for f in files:
    if "Achatocarpus.PNG" in f["title"]:
        print(f"File entry: {f}")
