"""본인 따릉이 이용내역 수집.

이용내역은 공공 오픈데이터에 없다. 공개된 건 전부 집계본이고 개인 식별자가
없어서 "내가 그날 그 대여소에서 빌렸는가"를 되짚을 수 없다. 본인 계정에서만
얻을 수 있고, 이 기록이 곧 "주 대여소 재고 실패" 정답 레이블이 된다.

재고 스냅샷과 달리 이 데이터는 도망가지 않는다(계정에 남아 있다). 그래서
자동 로그인을 뚫는 대신 사람이 만든 세션을 재사용한다 — bikeseoul.py 참고.
"""

import re
import sys
import time
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


# --- 상세 페이지 ------------------------------------------------------
# 목록에 없는 값(이용시간·칼로리·탄소절감·추가과금)은 건별 상세에만 있다.
# 재고 예측에는 쓰이지 않는다 — 라이딩 결과지 대여소 상태가 아니다.
# 개인 기록 보존용이다.

DETAIL_PATH = "/app/mybike/moveUseHistoryDetailView.do"

_MIN = re.compile(r"(\d+)분")
_KM = re.compile(r"([\d.]+)\s*km")
_KCAL = re.compile(r"([\d.]+)\s*kcal")
_KG = re.compile(r"([\d.]+)\s*kg")
_FEE = re.compile(r"추가과금\s*\t?\s*([\d,]+)")


def parse_detail(text: str) -> dict:
    """상세 화면 텍스트에서 값을 뽑는다.

    duration_min은 사이트가 계산한 값이라 대여/반납 타임스탬프(분 단위)
    차이보다 정확하다. carbon_kg는 거리 x 0.232의 파생값이라 정보량이
    없지만 원본 그대로 남긴다.
    """

    def num(pattern, cast=float):
        m = pattern.search(text)
        if not m:
            return None
        try:
            return cast(m.group(1).replace(",", ""))
        except ValueError:
            return None

    return {
        "duration_min": num(_MIN, int),
        "distance_km": num(_KM),
        "calories": num(_KCAL),
        "carbon_kg": num(_KG),
        "extra_fee": num(_FEE, int),
    }


def fetch_detail_via_page(page, history_url: str, seq: str) -> dict:
    """한 건의 상세를 연다. 목록 페이지의 폼을 상세로 돌려 제출한다."""
    page.goto(history_url, wait_until="domcontentloaded")
    with page.expect_navigation(wait_until="domcontentloaded", timeout=30000):
        page.evaluate(
            """([s, path]) => {
                document.querySelector("[name='rentHistSeq']").value = s;
                const f = document.querySelector("#searchFrm");
                f.action = path; f.method = "post"; f.submit();
            }""",
            [seq, DETAIL_PATH],
        )
    return parse_detail(page.inner_text("body"))


# --- 로그인 ------------------------------------------------------------
# 사이트가 산발적으로 연결을 끊는다(ERR_CONNECTION_RESET). 같은 구성이
# 곧바로 다시 하면 성공하는 것을 확인했으므로 하드 차단이 아니라 일시적이다.
#
# 주 1회만 도는 작업이라 리셋 한 번에 한 주를 통째로 날린다. 실제로
# 2026-09-13 첫 예약 실행이 이것 때문에 실패했다.

LOGIN_URL = f"{BASE}/login.do"
NAV_TIMEOUT = 30000
LOGIN_RETRY_WAITS = (5, 15, 30)


class LoginRejected(Exception):
    """자격증명이 거부됐다. 재시도해도 같고, 반복하면 계정이 잠긴다."""


class LoginPageUnavailable(Exception):
    """로그인 페이지를 받지 못했다. 일시적일 수 있어 재시도 대상이다."""


def login_with_retry(page, user_id: str, password: str, *,
                     waits=LOGIN_RETRY_WAITS, sleep=time.sleep) -> None:
    """로그인한다. 일시적 실패만 재시도하고 자격증명 거부는 즉시 올린다.

    둘을 구분하지 않으면 비밀번호가 틀렸을 때 재시도가 계정 잠금을 부른다.
    """
    if not user_id or not password:
        raise LoginRejected("BIKESEOUL_ID / BIKESEOUL_PW가 비어 있다.")

    last: Exception | None = None
    for wait in (*waits, None):
        try:
            page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
            if page.query_selector("#memid") is None:
                raise LoginPageUnavailable(
                    f"로그인 폼이 없다 (URL={page.url}, {len(page.content())}bytes)")
            # domcontentloaded는 외부 스크립트(jQuery) 로딩 전에 끝난다.
            # 그 상태에서 loginSubmit()을 부르면 "$ is not defined"로 터지고,
            # 예외 탓에 페이지 이동이 안 일어나 expect_navigation이 타임아웃한다.
            # 2026-09-13 첫 예약 실행이 정확히 이것 때문에 실패했다.
            page.wait_for_function(
                "typeof $ !== 'undefined' && typeof loginSubmit === 'function'",
                timeout=NAV_TIMEOUT)
            page.fill("#memid", user_id)
            page.fill("#mempw", password)
            with page.expect_navigation(wait_until="domcontentloaded", timeout=NAV_TIMEOUT):
                page.evaluate("loginSubmit()")
            if "login.do" in page.url:
                # 스프링 시큐리티는 실패 시 로그인 폼으로 되돌린다. 성공은
                # main.do로 간다 — 실측으로 확인했다.
                raise LoginRejected("아이디/비밀번호가 거부됐다.")
            return
        except LoginRejected:
            raise
        except Exception as exc:  # noqa: BLE001 - playwright 예외 타입을 특정하지 않는다
            last = exc
            if wait is None:
                break
            # 조용히 재시도하면 서서히 나빠지는 사이트가 건강한 사이트처럼
            # 보인다. 예외 타입만 남긴다 — 메시지에 자격증명이 섞일 수 있다.
            print(f"  로그인 실패({type(exc).__name__}), {wait}초 후 재시도",
                  file=sys.stderr)
            sleep(wait)

    kind = type(last).__name__ if last is not None else "알 수 없음"
    raise LoginPageUnavailable(f"로그인이 재시도 후에도 실패했다: {kind}")
