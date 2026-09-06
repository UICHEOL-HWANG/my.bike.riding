"""과거 재고 백필 (bikeListHist, OA-20447).

실시간 API(bikeList)는 호출 시점만 준다. 반면 이 API는 **최근 7일치를
시간 단위로** 준다 — "재고는 스냅샷으로만 얻는다"는 원칙의 유일한 예외이고,
수집이 끊겼을 때의 유일한 복구 수단이다.

7일 창은 하루가 지날 때마다 하루씩 사라진다. 미루면 그만큼 영구 손실이다.

시간 단위라 10분 격자를 복원하지는 못한다. 정시 지점만 메운다.
"""

import time
from datetime import datetime, timedelta, timezone
from typing import Iterator

from collector.api import fetch_page
from collector.transform import build_rows

# stationDt는 KST다. 우리 실측 스냅샷과 대조해 확인했다 — 21시로 요청한
# 값이 12:00 UTC 실측과 14개 중 13개 일치(총 차이 1대), UTC로 가정하면
# 1개만 일치했다.
KST = timezone(timedelta(hours=9))

ENVELOPE = "getStationListHist"
PAGE_SIZE = 1000
WINDOW_DAYS = 7

# 시간당 3페이지, 7일이면 500회가 넘는다. 사이에 잠깐씩 쉰다.
PAUSE = 0.2


def station_dt(when: datetime) -> str:
    """UTC 시각을 API가 받는 KST 'yyyyMMddHH'로 바꾼다."""
    return when.astimezone(KST).strftime("%Y%m%d%H")


def captured_at_of(dt_text: str) -> datetime:
    """'yyyyMMddHH'(KST)를 UTC 시각으로 되돌린다."""
    naive = datetime.strptime(dt_text, "%Y%m%d%H")
    return naive.replace(tzinfo=KST).astimezone(timezone.utc)


def hours_back(now: datetime, days: int = WINDOW_DAYS) -> Iterator[datetime]:
    """지금부터 days일 전까지의 매 정시를, 오래된 것부터 돌려준다.

    오래된 쪽부터 도는 이유: 7일 경계에 가장 가까운 시각이 가장 먼저
    사라진다. 중간에 끊겨도 사라질 것부터 건진다.
    """
    top = now.replace(minute=0, second=0, microsecond=0)
    for i in range(days * 24, -1, -1):
        yield top - timedelta(hours=i)


def fetch_hour(api_key: str, dt_text: str) -> list[dict]:
    """한 시각의 전 대여소를 페이징으로 받는다.

    종료 조건은 실시간 경로와 같다 — 받은 행이 page_size보다 적으면 멈춘다.
    list_total_count는 신뢰하지 않는다.
    """
    rows: list[dict] = []
    start = 1
    while start <= 10_000:
        page = fetch_page(api_key, start, start + PAGE_SIZE - 1,
                          service="bikeListHist", envelope=ENVELOPE, suffix=dt_text)
        rows += page
        if len(page) < PAGE_SIZE:
            break
        start += PAGE_SIZE
    return rows


def build_hist_rows(raw_rows: list[dict], station_ids: frozenset[str], dt_text: str):
    """실시간 경로와 같은 변환을 쓴다. 필드명이 동일하다.

    fetched_at을 captured_at과 같게 둔다. 이 값은 우리가 방금 받아온
    시각이 아니라 API가 그 시각에 기록한 값이라, now()를 넣으면 수신
    지연 통계가 오염된다. 출처는 source='hist'로 구분한다.
    """
    cap = captured_at_of(dt_text)
    snapshots, stations = build_rows(raw_rows, station_ids, cap, cap)
    for s in snapshots:
        s["source"] = "hist"
    return snapshots, stations
