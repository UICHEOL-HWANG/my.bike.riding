"""본인 따릉이 이용내역 수집.

이용내역은 공공 오픈데이터에 없다. 공개된 건 전부 집계본이고 개인 식별자가
없어서 "내가 그날 그 대여소에서 빌렸는가"를 되짚을 수 없다. 본인 계정에서만
얻을 수 있고, 이 기록이 곧 "주 대여소 재고 실패" 정답 레이블이 된다.

재고 스냅샷과 달리 이 데이터는 도망가지 않는다(계정에 남아 있다). 그래서
자동 로그인을 뚫는 대신 사람이 만든 세션을 재사용한다 — bikeseoul.py 참고.
"""

import re
from datetime import date, timedelta
from typing import Iterator

import requests

from collector.bikeseoul import BASE

HISTORY_URL = f"{BASE}/app/mybike/getMemberUseHistory.do"
TIMEOUT = 20

# 조회 결과에 상한이 있다(넓은 범위를 요청해도 100건에서 끊긴다). 범위를
# 6개월 창으로 잘라 여러 번 받아야 전체가 나온다.
WINDOW_DAYS = 183

# 창 하나가 상한에 걸릴 만큼 많아도 무한 루프에 빠지지 않게 한다.
MAX_PAGES = 40

_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_TAG = re.compile(r"<[^>]+>")
_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}")


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", _TAG.sub("", html)).strip()


def parse_rows(html: str) -> list[dict]:
    """내역 테이블에서 한 페이지분을 뽑는다.

    보이는 칸은 5개지만 숨은 칸 2개가 더 있다. [5]가 rentHistSeq로,
    이게 유일한 안정적 식별자다 — 대여일시는 같은 분에 두 건이 생길 수 있다.
    """
    rides = []
    for row in _ROW.findall(html):
        cells = [_text(c) for c in _CELL.findall(row)]
        if len(cells) < 7 or not _DATETIME.match(cells[1]):
            continue
        rides.append(
            {
                "rent_hist_seq": cells[5],
                "bike_no": cells[0],
                "rented_at": cells[1],
                "rent_station": cells[2],
                "returned_at": cells[3] or None,
                "return_station": cells[4] or None,
                # 숨은 칸이라 라벨이 없다. 위치와 값 범위로 보아 이용거리(km)로
                # 보이지만 확정은 아니다. 상세 페이지에서 확인할 것.
                "distance_km": _to_float(cells[6]),
            }
        )
    return rides


def _to_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def iter_windows(start: date, end: date, days: int = WINDOW_DAYS) -> Iterator[tuple[date, date]]:
    cursor = start
    while cursor <= end:
        stop = min(cursor + timedelta(days=days - 1), end)
        yield cursor, stop
        cursor = stop + timedelta(days=1)


def fetch_window(session: requests.Session, start: date, end: date) -> list[dict]:
    """창 하나를 페이지 끝까지 받는다.

    종료 조건을 페이징 마크업에서 읽지 않는다. 페이지 번호 위젯은 10개씩만
    보여줘서 마지막 페이지 판정에 쓸 수 없다. 대신 "새로 본 rentHistSeq가
    하나도 없으면 멈춘다" — 서버가 범위를 넘겨 같은 페이지를 되돌려줘도 멈춘다.
    """
    seen: dict[str, dict] = {}
    for page in range(1, MAX_PAGES + 1):
        resp = session.post(
            HISTORY_URL,
            data={
                "searchStartDate": start.isoformat(),
                "searchEndDate": end.isoformat(),
                "currentPageNo": str(page),
                "rentHistSeq": "",
                "rentDttm": "",
            },
            headers={"Referer": HISTORY_URL},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        rows = parse_rows(resp.text)
        fresh = [r for r in rows if r["rent_hist_seq"] not in seen]
        if not fresh:
            break
        for r in fresh:
            seen[r["rent_hist_seq"]] = r
    return list(seen.values())


def fetch_all(session: requests.Session, start: date, end: date) -> list[dict]:
    """전 구간을 6개월 창으로 나눠 받는다. 창 경계 중복은 seq로 걸러진다."""
    merged: dict[str, dict] = {}
    for w_start, w_end in iter_windows(start, end):
        for ride in fetch_window(session, w_start, w_end):
            merged[ride["rent_hist_seq"]] = ride
    return sorted(merged.values(), key=lambda r: r["rented_at"])


# --- 브라우저 경로 ---------------------------------------------------
# requests로는 서버가 연결을 끊는다(클라이언트 식별). 진짜 브라우저로
# 같은 폼을 조작한다. page는 Playwright Page를 기대하지만 타입으로 묶지
# 않는다 — 이 모듈이 playwright에 의존하면 파싱 테스트까지 무거워진다.


def fetch_window_via_page(page, start: date, end: date) -> list[dict]:
    """브라우저로 창 하나를 페이지 끝까지 받는다.

    폼 값을 직접 넣고 사이트가 가진 제출 함수(own.exeUpdateList)를 부른다.
    URL을 새로 만들지 않으므로 사이트가 파라미터를 바꿔도 따라간다.
    """
    seen: dict[str, dict] = {}
    for page_no in range(1, MAX_PAGES + 1):
        # 제출은 곧 페이지 이동이다. 이동을 기다리지 않고 내용을 읽으면
        # "page is navigating" 에러가 난다.
        with page.expect_navigation(wait_until="domcontentloaded", timeout=30000):
            page.evaluate(
                """([s, e, n]) => {
                    document.querySelector("[name='searchStartDate']").value = s;
                    document.querySelector("[name='searchEndDate']").value = e;
                    own.exeUpdateList(n);
                }""",
                [start.isoformat(), end.isoformat(), page_no],
            )
        fresh = [r for r in parse_rows(page.content()) if r["rent_hist_seq"] not in seen]
        if not fresh:
            break
        for ride in fresh:
            seen[ride["rent_hist_seq"]] = ride
    return list(seen.values())


def fetch_all_via_page(page, start: date, end: date) -> list[dict]:
    merged: dict[str, dict] = {}
    for w_start, w_end in iter_windows(start, end):
        for ride in fetch_window_via_page(page, w_start, w_end):
            merged[ride["rent_hist_seq"]] = ride
    return sorted(merged.values(), key=lambda r: r["rented_at"])
