# 따릉이 수집기 최소 버전 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 서울시 공공자전거 실시간 대여정보 API를 10분마다 호출해 관심 대여소의 재고 스냅샷을 Supabase에 적재한다.

**Architecture:** 순수 함수(`transform`)를 중심에 두고 네트워크(`api`)와 DB(`store`)를 바깥으로 밀어낸다. `__main__`이 셋을 엮고 종료 코드로 성패를 알린다. 스케줄은 GitHub Actions cron이며, cron 지연은 `captured_at`을 10분 격자로 내려 흡수한다.

**Tech Stack:** Python 3.13, uv, requests, PyYAML, supabase-py, python-dotenv, pytest, responses

**Spec:** [../specs/2026-09-04-ttareungi-collector-design.md](../specs/2026-09-04-ttareungi-collector-design.md)

## Global Constraints

- Python 3.13 (시스템 기본 3.8을 쓰지 말 것). 패키지 관리는 `uv`
- `captured_at`은 항상 UTC tz-aware이며 10분 격자로 내림. 실제 응답 시각은 `fetched_at`에 따로 보존
- 격자를 건너뛴 구간은 **비워 둔다.** 어떤 방식으로도 채우지 않는다 (리크 방지)
- 서울시 API는 실패해도 HTTP 200을 반환한다. 반드시 본문 `RESULT.CODE == "INFO-000"`으로 판정할 것
- 페이징 종료는 `list_total_count`가 아니라 **"받은 행이 page_size 미만이면 끝"**으로 판정한다
- 적재 행이 0이거나 페이지를 다 못 받으면 프로세스는 종료 코드 1로 실패를 알린다 (받은 데이터는 적재한 뒤에)
- 저장소는 public이다. 키·토큰은 절대 커밋하지 않는다. `.env`는 `.gitignore`에 있다
- 커밋 메시지는 한국어로, 무엇을 왜 했는지 한 줄 요약 + 필요시 본문

---

### Task 1: 프로젝트 초기화와 실제 응답 픽스처 확보

이 태스크만 TDD를 적용하지 않는다. 목적이 "외부 API가 실제로 무엇을 주는지 관측하는 것"이라 미리 쓸 수 있는 단언이 없다. 여기서 얻은 실제 응답이 이후 모든 테스트의 근거가 된다.

**Files:**
- Create: `pyproject.toml`, `.env.example`, `stations.yml`, `scripts/fetch_sample.py`, `tests/fixtures/bikelist_sample.json`

**Interfaces:**
- Consumes: 없음
- Produces: `tests/fixtures/bikelist_sample.json` — 이후 모든 태스크의 테스트 픽스처

- [ ] **Step 1: uv 프로젝트 초기화**

```bash
uv init --python 3.13 --no-workspace
uv add requests pyyaml supabase python-dotenv
uv add --dev pytest responses
```

- [ ] **Step 2: `uv init` 잔여물 정리와 pytest 설정**

`uv init`이 만든 `main.py`(또는 `hello.py`)를 지운다. 그리고 `pyproject.toml` 끝에 아래를 추가한다.

```toml
[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

`pythonpath`가 없으면 `import collector`가 실패한다. 이어서 빈 `tests/__init__.py`를 만든다 —
Task 6이 `tests.test_store`에서 가짜 클라이언트를 가져다 쓰므로 `tests`가 패키지여야 한다.

```bash
mkdir -p tests && touch tests/__init__.py
```

- [ ] **Step 3: `.env.example` 작성**

```
SEOUL_API_KEY=여기에_열린데이터광장_인증키
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_SERVICE_KEY=여기에_service_role_키
```

- [ ] **Step 4: 로컬 `.env` 생성**

`.env.example`을 `.env`로 복사하고 실제 값을 채운다. `.env`는 이미 `.gitignore`에 있으므로 커밋되지 않는다. 커밋 전 `git status`로 확인할 것.

- [ ] **Step 5: `stations.yml` 뼈대 작성**

실제 대여소 ID는 사용자에게 받아 Task 7에서 채운다. 지금은 형식만 확정한다.

```yaml
# 관심 대여소 목록
# main: 평소 이용하는 대여소
# fallback: 자전거가 없을 때 걸어가는 대안 대여소
# 둘 다 동일하게 수집한다. 구분은 나중에 분석할 때 쓴다.
main: []
fallback: []
```

- [ ] **Step 6: 샘플 수집 스크립트 작성**

```python
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
```

- [ ] **Step 7: 실행해서 응답 구조 확인**

Run: `uv run python scripts/fetch_sample.py`

**확인할 것 (이후 태스크가 여기에 의존한다):**
1. 최상위 키가 `rentBikeStatus`인가
2. `RESULT.CODE`가 `INFO-000`인가
3. `row` 배열 원소의 필드명 — `stationId`, `stationName`, `parkingBikeTotCnt`, `rackTotCnt`, `shared`, `stationLatitude`, `stationLongitude`
4. 숫자 필드가 문자열(`"15"`)로 오는가

**필드명이 위와 다르면 Task 3의 매핑을 실제 이름으로 바꿀 것.** 나머지 설계는 그대로 유효하다.

인증키가 틀리면 HTTP 200에 `RESULT.CODE`가 `INFO-100`으로 온다. 그 경우 키를 먼저 고치고 다시 실행한다.

- [ ] **Step 8: 커밋**

```bash
git add pyproject.toml uv.lock tests/__init__.py .env.example stations.yml scripts/fetch_sample.py tests/fixtures/bikelist_sample.json
git status --short   # .env 가 목록에 없는지 반드시 확인
git commit -m "프로젝트 초기화와 실제 API 응답 픽스처 확보

이후 모든 테스트는 이 픽스처를 근거로 네트워크 없이 돈다."
```

---

### Task 2: 설정 로더

**Files:**
- Create: `collector/__init__.py`, `collector/config.py`, `tests/test_config.py`

**Interfaces:**
- Consumes: `stations.yml` (Task 1)
- Produces:
  - `Settings` — frozen dataclass: `seoul_api_key: str`, `supabase_url: str`, `supabase_service_key: str`, `station_ids: frozenset[str]`, `grid_minutes: int`
  - `load_station_ids(path: Path) -> frozenset[str]`
  - `load_settings(stations_path: Path = Path("stations.yml"), *, load_env: bool = True) -> Settings`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_config.py
from pathlib import Path

import pytest

from collector.config import load_settings, load_station_ids


def test_main과_fallback을_하나의_집합으로_합친다(tmp_path):
    p = tmp_path / "stations.yml"
    p.write_text("main: [ST-4, ST-5]\nfallback: [ST-9]\n", encoding="utf-8")

    assert load_station_ids(p) == frozenset({"ST-4", "ST-5", "ST-9"})


def test_빈_목록이면_에러를_낸다(tmp_path):
    p = tmp_path / "stations.yml"
    p.write_text("main: []\nfallback: []\n", encoding="utf-8")

    with pytest.raises(ValueError, match="대여소"):
        load_station_ids(p)


def test_키가_없으면_에러를_낸다(tmp_path, monkeypatch):
    monkeypatch.delenv("SEOUL_API_KEY", raising=False)
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "k")
    p = tmp_path / "stations.yml"
    p.write_text("main: [ST-4]\nfallback: []\n", encoding="utf-8")

    # load_env=False가 없으면 로컬 .env가 지운 변수를 도로 채워 테스트가 환경을 탄다.
    with pytest.raises(ValueError, match="SEOUL_API_KEY"):
        load_settings(p, load_env=False)
```

빈 목록에서 에러를 내는 이유: 목록이 비면 수집기는 매 실행 0행을 적재하고, 사람이 눈치채기까지 며칠이 그냥 지나간다.

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'collector'`

- [ ] **Step 3: 구현**

```python
# collector/config.py
import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

GRID_MINUTES = 10


@dataclass(frozen=True)
class Settings:
    seoul_api_key: str
    supabase_url: str
    supabase_service_key: str
    station_ids: frozenset[str]
    grid_minutes: int


def load_station_ids(path: Path) -> frozenset[str]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    ids = frozenset(
        str(s).strip()
        for key in ("main", "fallback")
        for s in (data.get(key) or [])
        if str(s).strip()
    )
    if not ids:
        raise ValueError(f"{path}에 관심 대여소가 하나도 없다. main 또는 fallback을 채울 것.")
    return ids


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"환경변수 {name}이 비어 있다.")
    return value


def load_settings(
    stations_path: Path = Path("stations.yml"), *, load_env: bool = True
) -> Settings:
    # 테스트는 load_env=False로 부른다. 로컬 .env가 테스트 환경을 오염시키지 않도록.
    if load_env:
        load_dotenv()
    return Settings(
        seoul_api_key=_require_env("SEOUL_API_KEY"),
        supabase_url=_require_env("SUPABASE_URL"),
        supabase_service_key=_require_env("SUPABASE_SERVICE_KEY"),
        station_ids=load_station_ids(stations_path),
        grid_minutes=GRID_MINUTES,
    )
```

`collector/__init__.py`는 빈 파일로 만든다.

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: 커밋**

```bash
git add collector/__init__.py collector/config.py tests/test_config.py
git commit -m "설정 로더 추가

대여소 목록이 비면 에러를 낸다. 조용히 0행을 쌓는 것이 이 프로젝트에서 가장 나쁜 실패다."
```

---

### Task 3: 응답 변환 (이 계획의 핵심)

**Files:**
- Create: `collector/transform.py`, `tests/test_transform.py`

**Interfaces:**
- Consumes: Task 1의 픽스처
- Produces:
  - `floor_to_grid(ts: datetime, grid_minutes: int) -> datetime`
  - `to_int(value: object) -> int | None`
  - `to_float(value: object) -> float | None`
  - `build_rows(raw_rows: list[dict], station_ids: frozenset[str], captured_at: datetime, fetched_at: datetime) -> tuple[list[dict], list[dict]]` — `(snapshot_rows, station_rows)`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_transform.py
from datetime import datetime, timezone

from collector.transform import build_rows, floor_to_grid, to_int

KST_ROW = {
    "stationId": "ST-4",
    "stationName": "102. 망원역 1번출구 앞",
    "parkingBikeTotCnt": "3",
    "rackTotCnt": "15",
    "shared": "20",
    "stationLatitude": "37.55564880",
    "stationLongitude": "126.91062927",
}


def _dt(h, m, s=0):
    return datetime(2026, 9, 4, h, m, s, tzinfo=timezone.utc)


def test_격자_경계에서_내림한다():
    assert floor_to_grid(_dt(10, 0, 0), 10) == _dt(10, 0)
    assert floor_to_grid(_dt(10, 9, 59), 10) == _dt(10, 0)
    assert floor_to_grid(_dt(10, 10, 0), 10) == _dt(10, 10)


def test_마이크로초까지_버린다():
    ts = datetime(2026, 9, 4, 10, 7, 33, 123456, tzinfo=timezone.utc)
    assert floor_to_grid(ts, 10) == _dt(10, 0)


def test_문자열_숫자를_정수로_바꾼다():
    assert to_int("15") == 15
    assert to_int(15) == 15


def test_숫자가_아니면_None을_준다():
    assert to_int("") is None
    assert to_int(None) is None
    assert to_int("없음") is None


def test_관심_대여소만_남긴다():
    rows = [KST_ROW, {**KST_ROW, "stationId": "ST-999"}]

    snapshots, _ = build_rows(rows, frozenset({"ST-4"}), _dt(10, 0), _dt(10, 3))

    assert [r["station_id"] for r in snapshots] == ["ST-4"]


def test_스냅샷_행의_모양():
    snapshots, _ = build_rows([KST_ROW], frozenset({"ST-4"}), _dt(10, 0), _dt(10, 3))

    assert snapshots[0] == {
        "station_id": "ST-4",
        "captured_at": "2026-09-04T10:00:00+00:00",
        "fetched_at": "2026-09-04T10:03:00+00:00",
        "parking_cnt": 3,
        "rack_total": 15,
        "shared": 20,
    }


def test_대여소_마스터_행의_모양():
    _, stations = build_rows([KST_ROW], frozenset({"ST-4"}), _dt(10, 0), _dt(10, 3))

    assert stations[0]["station_id"] == "ST-4"
    assert stations[0]["name"] == "102. 망원역 1번출구 앞"
    assert stations[0]["lat"] == 37.55564880
    assert stations[0]["lon"] == 126.91062927
    assert stations[0]["updated_at"] == "2026-09-04T10:03:00+00:00"


def test_같은_대여소가_두_번_와도_한_행만_남긴다():
    rows = [KST_ROW, {**KST_ROW, "parkingBikeTotCnt": "7"}]

    snapshots, stations = build_rows(rows, frozenset({"ST-4"}), _dt(10, 0), _dt(10, 3))

    assert len(snapshots) == 1
    assert len(stations) == 1


def test_필드가_없어도_터지지_않는다():
    snapshots, _ = build_rows(
        [{"stationId": "ST-4"}], frozenset({"ST-4"}), _dt(10, 0), _dt(10, 3)
    )

    assert snapshots[0]["parking_cnt"] is None
    assert snapshots[0]["rack_total"] is None
```

같은 대여소 중복 테스트가 필요한 이유: 한 배치 안에 같은 `(station_id, captured_at)`이 두 번 들어가면 Postgres가 `ON CONFLICT DO UPDATE ... affect row a second time` 에러를 낸다. 응답에 중복이 오는지는 알 수 없으니 변환 단계에서 미리 막는다.

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_transform.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'collector.transform'`

- [ ] **Step 3: 구현**

```python
# collector/transform.py
from datetime import datetime


def floor_to_grid(ts: datetime, grid_minutes: int) -> datetime:
    """수집 시각을 격자로 내린다.

    cron 지연으로 실행 시각이 흔들려도 같은 격자에 떨어지게 해서
    unique(station_id, captured_at)이 중복을 실제로 막게 한다.
    """
    return ts.replace(
        minute=(ts.minute // grid_minutes) * grid_minutes, second=0, microsecond=0
    )


def to_int(value: object) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def to_float(value: object) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def build_rows(
    raw_rows: list[dict],
    station_ids: frozenset[str],
    captured_at: datetime,
    fetched_at: datetime,
) -> tuple[list[dict], list[dict]]:
    captured = captured_at.isoformat()
    fetched = fetched_at.isoformat()

    snapshots: dict[str, dict] = {}
    stations: dict[str, dict] = {}

    for raw in raw_rows:
        station_id = str(raw.get("stationId", "")).strip()
        if not station_id or station_id not in station_ids:
            continue
        if station_id in snapshots:
            continue

        snapshots[station_id] = {
            "station_id": station_id,
            "captured_at": captured,
            "fetched_at": fetched,
            "parking_cnt": to_int(raw.get("parkingBikeTotCnt")),
            "rack_total": to_int(raw.get("rackTotCnt")),
            "shared": to_int(raw.get("shared")),
        }
        stations[station_id] = {
            "station_id": station_id,
            "name": raw.get("stationName"),
            "lat": to_float(raw.get("stationLatitude")),
            "lon": to_float(raw.get("stationLongitude")),
            "updated_at": fetched,
        }

    return list(snapshots.values()), list(stations.values())
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_transform.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: 커밋**

```bash
git add collector/transform.py tests/test_transform.py
git commit -m "응답 변환 추가

captured_at을 10분 격자로 내려 cron 지연을 흡수하고,
한 배치 안의 중복 대여소를 미리 제거해 upsert 충돌을 막는다."
```

---

### Task 4: API 호출과 페이징

**Files:**
- Create: `collector/api.py`, `tests/test_api.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `SeoulApiError(Exception)`
  - `fetch_page(api_key: str, start: int, end: int, *, session: requests.Session | None = None) -> list[dict]` — 실패 시 `SeoulApiError`
  - `fetch_all(api_key: str, *, page_size: int = 1000, max_pages: int = 10) -> tuple[list[dict], SeoulApiError | None]` — 받은 행과, 중간에 멈췄다면 그 원인

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_api.py
import pytest
import responses

from collector.api import SeoulApiError, fetch_all, fetch_page

KEY = "testkey"


def url(start, end):
    return f"http://openapi.seoul.go.kr:8088/{KEY}/json/bikeList/{start}/{end}/"


def body(rows, code="INFO-000"):
    return {
        "rentBikeStatus": {
            "RESULT": {"CODE": code, "MESSAGE": "메시지"},
            "row": rows,
        }
    }


def make_rows(n, offset=0):
    return [{"stationId": f"ST-{i + offset}"} for i in range(n)]


@responses.activate
def test_한_페이지를_받는다():
    responses.add(responses.GET, url(1, 1000), json=body(make_rows(3)), status=200)

    assert len(fetch_page(KEY, 1, 1000)) == 3


@responses.activate
def test_HTTP_200이어도_에러코드면_실패로_본다():
    responses.add(
        responses.GET, url(1, 1000), json=body([], code="INFO-100"), status=200
    )

    with pytest.raises(SeoulApiError, match="INFO-100"):
        fetch_page(KEY, 1, 1000)


@responses.activate
def test_페이지가_가득_차지_않으면_거기서_멈춘다():
    responses.add(responses.GET, url(1, 1000), json=body(make_rows(1000)), status=200)
    responses.add(
        responses.GET, url(1001, 2000), json=body(make_rows(1000, 1000)), status=200
    )
    responses.add(
        responses.GET, url(2001, 3000), json=body(make_rows(847, 2000)), status=200
    )

    rows, error = fetch_all(KEY)

    assert len(rows) == 2847
    assert error is None
    assert len(responses.calls) == 3


@responses.activate
def test_중간에_실패해도_받은_만큼은_돌려준다():
    responses.add(responses.GET, url(1, 1000), json=body(make_rows(1000)), status=200)
    responses.add(
        responses.GET, url(1001, 2000), json=body([], code="ERROR-500"), status=200
    )

    rows, error = fetch_all(KEY)

    assert len(rows) == 1000
    assert isinstance(error, SeoulApiError)


@responses.activate
def test_일시적_오류는_재시도한다():
    responses.add(responses.GET, url(1, 1000), status=500)
    responses.add(responses.GET, url(1, 1000), json=body(make_rows(2)), status=200)

    assert len(fetch_page(KEY, 1, 1000)) == 2
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'collector.api'`

- [ ] **Step 3: 구현**

```python
# collector/api.py
import time

import requests

BASE = "http://openapi.seoul.go.kr:8088"
OK_CODE = "INFO-000"
TIMEOUT = 10
RETRY_WAITS = (1, 2, 4)


class SeoulApiError(Exception):
    pass


def fetch_page(
    api_key: str, start: int, end: int, *, session: requests.Session | None = None
) -> list[dict]:
    get = (session or requests).get
    url = f"{BASE}/{api_key}/json/bikeList/{start}/{end}/"

    last_error: Exception | None = None
    for wait in (*RETRY_WAITS, None):
        try:
            resp = get(url, timeout=TIMEOUT)
            resp.raise_for_status()
            payload = resp.json().get("rentBikeStatus") or {}
            code = (payload.get("RESULT") or {}).get("CODE")
            if code != OK_CODE:
                message = (payload.get("RESULT") or {}).get("MESSAGE", "")
                # 인증키 오류·쿼터 초과는 재시도해도 낫지 않으므로 즉시 올린다.
                raise SeoulApiError(f"API가 {code}를 반환했다: {message}")
            return list(payload.get("row") or [])
        except SeoulApiError:
            raise
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if wait is None:
                break
            time.sleep(wait)

    raise SeoulApiError(f"{start}~{end} 호출이 재시도 후에도 실패했다: {last_error}")


def fetch_all(
    api_key: str, *, page_size: int = 1000, max_pages: int = 10
) -> tuple[list[dict], SeoulApiError | None]:
    """받은 행과, 중간에 멈췄다면 그 원인을 함께 돌려준다.

    부분 성공도 적재할 수 있게 예외를 던지지 않는다. 실패를 알리는 일은 호출자 몫.
    """
    rows: list[dict] = []
    with requests.Session() as session:
        for page in range(max_pages):
            start = page * page_size + 1
            end = start + page_size - 1
            try:
                page_rows = fetch_page(api_key, start, end, session=session)
            except SeoulApiError as exc:
                return rows, exc

            rows.extend(page_rows)
            # list_total_count는 API마다 의미가 달라 신뢰하지 않는다.
            if len(page_rows) < page_size:
                return rows, None

    return rows, SeoulApiError(f"{max_pages}페이지를 넘겼다. 대여소가 예상보다 많다.")
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_api.py -v`
Expected: PASS (5 passed)

재시도 테스트가 실제로 1초 이상 걸린다. 정상이다.

- [ ] **Step 5: 커밋**

```bash
git add collector/api.py tests/test_api.py
git commit -m "API 호출과 페이징 추가

서울시 API는 실패해도 HTTP 200을 주므로 본문 RESULT.CODE로 판정한다.
페이징 종료는 list_total_count가 아니라 '가득 차지 않은 페이지'로 본다."
```

---

### Task 5: Supabase 적재

**Files:**
- Create: `collector/store.py`, `tests/test_store.py`

**Interfaces:**
- Consumes: `build_rows`의 출력 (Task 3)
- Produces:
  - `make_client(url: str, service_key: str) -> Client`
  - `upsert_snapshots(client, rows: list[dict]) -> int`
  - `upsert_stations(client, rows: list[dict]) -> int`

- [ ] **Step 1: 실패하는 테스트 작성**

실제 DB에 붙지 않는다. 가짜 클라이언트로 "어떤 테이블에 어떤 충돌 옵션으로 무엇을 보내는가"만 검증한다.

```python
# tests/test_store.py
from collector.store import upsert_snapshots, upsert_stations


class FakeTable:
    def __init__(self, recorder, name):
        self.recorder = recorder
        self.name = name

    def upsert(self, rows, **kwargs):
        self.recorder.append({"table": self.name, "rows": rows, "kwargs": kwargs})
        return self

    def execute(self):
        return None


class FakeClient:
    def __init__(self):
        self.calls = []

    def table(self, name):
        return FakeTable(self.calls, name)


def test_스냅샷은_충돌하면_무시한다():
    client = FakeClient()

    count = upsert_snapshots(client, [{"station_id": "ST-4"}])

    assert count == 1
    assert client.calls[0]["table"] == "station_snapshot"
    assert client.calls[0]["kwargs"]["on_conflict"] == "station_id,captured_at"
    assert client.calls[0]["kwargs"]["ignore_duplicates"] is True


def test_대여소_마스터는_덮어쓴다():
    client = FakeClient()

    count = upsert_stations(client, [{"station_id": "ST-4"}])

    assert count == 1
    assert client.calls[0]["table"] == "station"
    assert client.calls[0]["kwargs"]["on_conflict"] == "station_id"
    assert client.calls[0]["kwargs"].get("ignore_duplicates") is not True


def test_빈_목록이면_호출하지_않는다():
    client = FakeClient()

    assert upsert_snapshots(client, []) == 0
    assert client.calls == []
```

스냅샷은 `ignore_duplicates=True`(충돌 시 아무것도 안 함)이고 대여소 마스터는 덮어쓴다. 이미 관측한 재고를 나중 실행이 덮어쓰면 그 시점의 진실이 사라지지만, 대여소 이름과 좌표는 최신이 맞다.

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'collector.store'`

- [ ] **Step 3: 구현**

```python
# collector/store.py
from supabase import Client, create_client


def make_client(url: str, service_key: str) -> Client:
    # service_role 키를 쓴다. anon 키는 RLS에 막혀 적재하지 못한다.
    return create_client(url, service_key)


def upsert_snapshots(client, rows: list[dict]) -> int:
    if not rows:
        return 0
    client.table("station_snapshot").upsert(
        rows, on_conflict="station_id,captured_at", ignore_duplicates=True
    ).execute()
    return len(rows)


def upsert_stations(client, rows: list[dict]) -> int:
    if not rows:
        return 0
    client.table("station").upsert(rows, on_conflict="station_id").execute()
    return len(rows)
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_store.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: 커밋**

```bash
git add collector/store.py tests/test_store.py
git commit -m "Supabase 적재 추가

스냅샷은 충돌 시 무시해 재실행이 과거 관측을 덮어쓰지 못하게 한다."
```

---

### Task 6: 엔트리포인트와 종료 코드

**Files:**
- Create: `collector/__main__.py`, `tests/test_main.py`

**Interfaces:**
- Consumes: Task 2~5 전부
- Produces: `run(settings, *, now=None, fetch=None, client=None) -> int` (종료 코드), `main() -> int`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_main.py
from datetime import datetime, timezone

from collector.api import SeoulApiError
from collector.config import Settings
from collector.__main__ import run
from tests.test_store import FakeClient

SETTINGS = Settings(
    seoul_api_key="k",
    supabase_url="https://x.supabase.co",
    supabase_service_key="s",
    station_ids=frozenset({"ST-4"}),
    grid_minutes=10,
)
NOW = datetime(2026, 9, 4, 10, 7, 33, tzinfo=timezone.utc)
ROW = {
    "stationId": "ST-4",
    "stationName": "망원역",
    "parkingBikeTotCnt": "3",
    "rackTotCnt": "15",
    "shared": "20",
    "stationLatitude": "37.5",
    "stationLongitude": "126.9",
}


def test_정상이면_0으로_끝난다():
    client = FakeClient()

    code = run(SETTINGS, now=NOW, fetch=lambda key: ([ROW], None), client=client)

    assert code == 0
    snapshot = client.calls[0]["rows"][0]
    assert snapshot["captured_at"] == "2026-09-04T10:00:00+00:00"
    assert snapshot["fetched_at"] == "2026-09-04T10:07:33+00:00"


def test_관심_대여소가_하나도_없으면_실패로_끝난다():
    client = FakeClient()

    code = run(
        SETTINGS,
        now=NOW,
        fetch=lambda key: ([{"stationId": "ST-999"}], None),
        client=client,
    )

    assert code == 1


def test_부분_성공은_적재하되_실패로_끝난다():
    client = FakeClient()

    code = run(
        SETTINGS,
        now=NOW,
        fetch=lambda key: ([ROW], SeoulApiError("2페이지 실패")),
        client=client,
    )

    assert code == 1
    assert client.calls, "받은 데이터는 적재해야 한다"
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_main.py -v`
Expected: FAIL — `ImportError: cannot import name 'run'`

- [ ] **Step 3: 구현**

```python
# collector/__main__.py
import sys
from datetime import datetime, timezone

from collector.api import fetch_all
from collector.config import Settings, load_settings
from collector.store import make_client, upsert_snapshots, upsert_stations
from collector.transform import build_rows, floor_to_grid


def run(settings: Settings, *, now=None, fetch=None, client=None) -> int:
    fetched_at = now or datetime.now(timezone.utc)
    captured_at = floor_to_grid(fetched_at, settings.grid_minutes)
    fetch = fetch or fetch_all
    client = client or make_client(settings.supabase_url, settings.supabase_service_key)

    raw_rows, error = fetch(settings.seoul_api_key)
    snapshots, stations = build_rows(
        raw_rows, settings.station_ids, captured_at, fetched_at
    )

    # 부분 성공이라도 받은 데이터는 먼저 남긴다.
    upsert_stations(client, stations)
    count = upsert_snapshots(client, snapshots)

    print(f"captured_at={captured_at.isoformat()} 적재 {count}행 (응답 {len(raw_rows)}건)")

    if error is not None:
        print(f"실패: {error}", file=sys.stderr)
        return 1
    if count == 0:
        print(
            "실패: 관심 대여소가 응답에 하나도 없다. "
            "stations.yml의 ID나 API 응답 형식을 확인할 것.",
            file=sys.stderr,
        )
        return 1
    return 0


def main() -> int:
    return run(load_settings())


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 전체 테스트 통과 확인**

Run: `uv run pytest -v`
Expected: PASS (23 passed — config 3, transform 9, api 5, store 3, main 3)

- [ ] **Step 5: 커밋**

```bash
git add collector/__main__.py tests/test_main.py
git commit -m "엔트리포인트 추가

부분 성공은 적재하되 종료 코드 1로 알린다. 0행 적재도 실패로 본다."
```

---

### Task 7: 스키마 적용과 실제 1회 수집

여기서 처음으로 진짜 데이터가 쌓인다. 사용자 입력이 필요하다.

**Files:**
- Create: `sql/0001_init.sql`
- Modify: `stations.yml`

**Interfaces:**
- Consumes: Task 6까지 전부
- Produces: Supabase에 실제 스냅샷 행

- [ ] **Step 1: 스키마 파일 작성**

```sql
-- sql/0001_init.sql
create table if not exists station_snapshot (
  id            bigserial primary key,
  captured_at   timestamptz not null,   -- 10분 격자로 내린 값
  fetched_at    timestamptz not null,   -- 실제 응답 수신 시각
  station_id    text        not null,
  parking_cnt   int,
  rack_total    int,
  shared        int,
  created_at    timestamptz default now(),
  unique (station_id, captured_at)
);

create index if not exists station_snapshot_station_time_idx
  on station_snapshot (station_id, captured_at desc);

create table if not exists station (
  station_id  text primary key,
  name        text,
  lat         double precision,
  lon         double precision,
  updated_at  timestamptz
);

-- 수집이 살아있는지 사람이 확인하는 창구.
create or replace view collector_health as
select
  max(captured_at)                                as last_captured_at,
  now() - max(captured_at)                        as staleness,
  count(*) filter (where captured_at > now() - interval '1 day') as rows_last_day
from station_snapshot;
```

- [ ] **Step 2: Supabase에 적용**

Supabase 대시보드의 SQL Editor에 `sql/0001_init.sql` 내용을 붙여 실행한다. Table Editor에서 `station_snapshot`, `station`이 생겼는지 확인한다.

- [ ] **Step 3: 관심 대여소 ID를 `stations.yml`에 채운다**

사용자에게 받은 대여소 ID를 넣는다. 형식 예시:

```yaml
main:
  - ST-4
fallback:
  - ST-9
  - ST-12
```

ID를 모르면 대여소 이름으로 찾는다:

```bash
uv run python -c "
import json, pathlib
rows = json.loads(pathlib.Path('tests/fixtures/bikelist_sample.json').read_text())['rentBikeStatus']['row']
for r in rows: print(r['stationId'], r['stationName'])
"
```

픽스처에는 5건뿐이므로, 전체에서 찾으려면 `scripts/fetch_sample.py`의 `/1/5/`를 `/1/1000/`으로 잠시 바꿔 실행하고 이름으로 grep 한다. **이 변경은 커밋하지 않는다.**

- [ ] **Step 4: 실제로 1회 돌린다**

Run: `uv run python -m collector`
Expected: `captured_at=... 적재 N행 (응답 3000건 내외)` 출력, 종료 코드 0

Run: `echo $?` → `0`

- [ ] **Step 5: DB에서 눈으로 확인한다**

Supabase SQL Editor에서:

```sql
select * from station_snapshot order by captured_at desc limit 20;
select * from collector_health;
```

`stations.yml`에 넣은 대여소 수만큼 행이 있고 `parking_cnt`가 그럴듯한 값인지 본다.

- [ ] **Step 6: 같은 격자에서 한 번 더 돌려 중복이 안 생기는지 확인한다**

10분 격자가 넘어가기 전에 다시 `uv run python -m collector`를 실행한 뒤:

```sql
select count(*) from station_snapshot where captured_at = (select max(captured_at) from station_snapshot);
```

행 수가 늘지 않아야 한다. **늘었다면 `unique` 제약이나 `on_conflict` 설정이 잘못된 것이므로 Task 5로 돌아간다.**

- [ ] **Step 7: 커밋**

```bash
git add sql/0001_init.sql stations.yml
git status --short   # scripts/fetch_sample.py 가 수정된 채로 섞이지 않았는지 확인
git commit -m "스키마와 관심 대여소 목록 추가

실제 1회 수집으로 적재와 중복 방지를 확인했다."
```

---

### Task 8: 스케줄 등록

**Files:**
- Create: `.github/workflows/collect.yml`
- Modify: `README.md` (생성)

**Interfaces:**
- Consumes: Task 7까지 전부
- Produces: 10분마다 도는 수집

- [ ] **Step 1: 워크플로 작성**

```yaml
# .github/workflows/collect.yml
name: collect

on:
  schedule:
    - cron: "*/10 * * * *"
  workflow_dispatch:

# 앞 실행이 늦어져 겹치면 새 실행을 버린다. 격자가 같으면 어차피 중복이다.
concurrency:
  group: collect
  cancel-in-progress: false

jobs:
  collect:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@v4

      - uses: astral-sh/setup-uv@v5
        with:
          python-version: "3.13"
          enable-cache: true

      - run: uv sync --frozen

      - run: uv run python -m collector
        env:
          SEOUL_API_KEY: ${{ secrets.SEOUL_API_KEY }}
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}
```

- [ ] **Step 2: GitHub Secrets 등록**

저장소 Settings → Secrets and variables → Actions → New repository secret 에서 `SEOUL_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` 세 개를 등록한다.

**이 저장소는 public이다.** 키를 워크플로 파일이나 코드에 직접 쓰면 즉시 공개된다.

- [ ] **Step 3: README 작성**

````markdown
# 따릉이 수집기

서울시 공공자전거 실시간 대여정보를 10분마다 수집해 Supabase에 적재한다.

- 설계: [docs/superpowers/specs/2026-09-04-ttareungi-collector-design.md](docs/superpowers/specs/2026-09-04-ttareungi-collector-design.md)
- 배경: [ttareungi-handoff.md](ttareungi-handoff.md)

## 로컬 실행

```bash
cp .env.example .env   # 값을 채운다
uv sync
uv run python -m collector
```

## 테스트

```bash
uv run pytest
```

## 수집이 살아있는지 확인

```sql
select * from collector_health;
```

`staleness`가 30분을 넘으면 수집이 멈춘 것이다.

## 알아둘 것

GitHub은 public 저장소에서 60일간 활동이 없으면 스케줄 워크플로를 자동 비활성화한다.
수집기는 커밋할 일이 없는 코드라 여기에 걸린다. `collector_health`를 가끔 볼 것.
````

- [ ] **Step 4: 커밋하고 푸시**

```bash
git add .github/workflows/collect.yml README.md
git commit -m "10분 간격 스케줄 등록

public 저장소라 Actions 실행 시간은 무료다.
60일 무활동 시 자동 비활성화되는 점은 README에 남겼다."
git push -u origin main
```

- [ ] **Step 5: 손으로 한 번 실행해 확인**

Actions 탭 → collect → Run workflow 로 수동 실행한다. 로그에 `적재 N행`이 찍히고 job이 초록색인지 본다.

실패하면 대개 Secrets 오타이거나 `uv.lock`이 커밋 안 된 경우다.

- [ ] **Step 6: 20분쯤 뒤 cron이 실제로 돌았는지 확인**

```sql
select captured_at, count(*) from station_snapshot
group by 1 order by 1 desc limit 10;
```

10분 간격으로 격자가 채워지고 있으면 성공이다. 격자가 자주 비면 cron 지연이 10분을 넘긴다는 뜻이므로, 그때 간격을 15분으로 늘릴지 판단한다. **판단 근거가 생길 때까지는 바꾸지 않는다.**

---

## 완료 조건

- `uv run pytest`가 전부 통과한다
- Supabase `station_snapshot`에 10분 격자로 행이 쌓인다
- 같은 격자에서 두 번 실행해도 행이 늘지 않는다
- `collector_health`의 `staleness`가 20분 이내를 유지한다

## 이 계획에 없는 것

원본 JSON 아카이브(인계서 작업 3번), 날씨 조인, 공공 파일데이터, 대시보드, `my_ride` 적재, 외부 헬스체크.
