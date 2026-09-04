# scripts/fetch_sample.py
"""실제 API를 1회 호출해 응답을 픽스처로 저장한다. 최초 1회만 쓰는 스크립트.

기본 범위는 1~5. 대여소 이름으로 ID를 찾는 등 더 넓은 범위가 필요하면
소스를 고쳐 커밋에 섞일 위험 없이 인자로 넘긴다:
    uv run python scripts/fetch_sample.py 1 1000
"""
import json
import os
import pathlib
import sys

import requests
from dotenv import load_dotenv

load_dotenv()

start = int(sys.argv[1]) if len(sys.argv) > 1 else 1
end = int(sys.argv[2]) if len(sys.argv) > 2 else 5

key = os.environ["SEOUL_API_KEY"]
url = f"http://openapi.seoul.go.kr:8088/{key}/json/bikeList/{start}/{end}/"
resp = requests.get(url, timeout=10)
resp.raise_for_status()
body = resp.json()

out = pathlib.Path("tests/fixtures/bikelist_sample.json")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")

print(json.dumps(body, ensure_ascii=False, indent=2)[:2000])
