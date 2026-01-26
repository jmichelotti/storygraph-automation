import json
import requests
from pathlib import Path

# --- CONFIG ---
STATE_FILE = Path("kindle_state.json")
URL = (
    "https://read.amazon.com/kindle-library/search"
    "?query=&libraryType=BOOKS&sortType=recency&querySize=50"
)

# --- LOAD COOKIES FROM PLAYWRIGHT STATE ---
if not STATE_FILE.exists():
    raise FileNotFoundError("kindle_state.json not found")

with STATE_FILE.open("r", encoding="utf-8") as f:
    state = json.load(f)

cookies = {}
for c in state.get("cookies", []):
    domain = c.get("domain", "")
    name = c.get("name")
    value = c.get("value")

    if domain.endswith("amazon.com") or domain.endswith("read.amazon.com"):
        cookies[name] = value

print("Loaded cookies:")
for k in sorted(cookies.keys()):
    print("  ", k)

# --- HEADERS (CRITICAL) ---
headers = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://read.amazon.com/",
    "Origin": "https://read.amazon.com",
}

# --- REQUEST ---
print("\nRequesting Kindle library JSON...\n")

response = requests.get(
    URL,
    cookies=cookies,
    headers=headers,
    timeout=20,
)

# --- OUTPUT ---
print("Status Code:", response.status_code)
print("Final URL :", response.url)
print("Content-Type:", response.headers.get("content-type"))

print("\nResponse preview:")
print(response.text[:1000])
