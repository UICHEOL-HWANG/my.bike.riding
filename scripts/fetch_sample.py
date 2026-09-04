# scripts/fetch_sample.py
"""실제 API를 1회 호출해 응답을 픽스처로 저장한다. 최초 1회만 쓰는 스크립트."""
import json
import os
import pathlib

import requests
from dotenv import load_dotenv

load_dotenv()

key = os.environ["SEOUL_API_KEY"]
url = f"http://openapi.seoul.go.kr:8088/{key}/json/bikeList/1/5/"
resp = requests.get(url, timeout=10)
resp.raise_for_status()
body = resp.json()

out = pathlib.Path("tests/fixtures/bikelist_sample.json")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")

print(json.dumps(body, ensure_ascii=False, indent=2)[:2000])
