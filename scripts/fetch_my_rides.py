"""본인 이용내역을 브라우저로 받아 Supabase에 적재한다.

requests로는 서버가 연결을 끊는다(클라이언트 식별). 탐지를 회피하는 대신
실제 브라우저를 쓴다 — 위장하지 않고 있는 그대로 접속한다.

재고 수집기와 달리 상시로 돌 필요가 없다. 이용내역은 계정에 남아 있어
사라지지 않으므로, 가끔 실행해 신규분만 붙이면 된다.

    uv run python scripts/fetch_my_rides.py                  # 최근 2년
    uv run python scripts/fetch_my_rides.py 2023-01-01       # 시작일 지정
    uv run python scripts/fetch_my_rides.py 2023-01-01 --show # 창 띄우기
"""
import json
import os
import pathlib
import sys
from datetime import date, timedelta

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from collector.my_ride import fetch_all_via_page  # noqa: E402
from collector.store import make_client, upsert_rides  # noqa: E402

LOGIN = "https://www.bikeseoul.com/login.do"
HISTORY = "https://www.bikeseoul.com/app/mybike/getMemberUseHistory.do"


def main() -> int:
    load_dotenv(ROOT / ".env")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    start = date.fromisoformat(args[0]) if args else date.today() - timedelta(days=730)
    end = date.today()

    user, pw = os.environ.get("BIKESEOUL_ID", ""), os.environ.get("BIKESEOUL_PW", "")
    if not user or not pw:
        print("[실패] .env에 BIKESEOUL_ID / BIKESEOUL_PW가 필요하다.")
        return 1

    with sync_playwright() as p:
        browser = p.chromium.launch(headless="--show" not in sys.argv)
        page = browser.new_page(locale="ko-KR")

        page.goto(LOGIN, wait_until="domcontentloaded")

        # 로그인 폼이 없으면 우리가 아는 그 페이지가 아니다. 차단 페이지나
        # 점검 안내일 수 있는데, "요소를 못 찾았다"는 타임아웃만으로는
        # 무엇이 왔는지 알 수 없다. 실제로 받은 것을 남긴다.
        if page.query_selector("#memid") is None:
            body = page.inner_text("body")[:600].replace("\n", " | ")
            print(f"[진단] 로그인 폼 없음")
            print(f"  URL   : {page.url}")
            print(f"  제목  : {page.title()}")
            print(f"  크기  : {len(page.content())} bytes")
            print(f"  본문  : {body}")
            page.screenshot(path="login_page.png", full_page=True)
            print("  스크린샷: login_page.png")
            browser.close()
            return 1

        page.fill("#memid", user)
        page.fill("#mempw", pw)
        with page.expect_navigation(wait_until="domcontentloaded", timeout=20000):
            page.evaluate("loginSubmit()")
        if "login.do" in page.url:
            print(f"[실패] 로그인 거부됨 -> {page.url}")
            browser.close()
            return 1
        print(f"[로그인] 성공 -> {page.url}")

        page.goto(HISTORY, wait_until="domcontentloaded")
        if "login.do" in page.url:
            print("[실패] 내역 페이지 접근 불가")
            browser.close()
            return 1

        print(f"[조회] {start} ~ {end}")
        rides = fetch_all_via_page(page, start, end)
        browser.close()

    if not rides:
        # 세션 문제와 "정말 내역이 없음"은 다르다. 0건을 조용히 넘기면
        # 무엇이 잘못됐는지 알 수 없다.
        print("[경고] 0건이다. 조회 기간이나 페이지 구조를 확인할 것.")
        return 1
    print(f"[수집] {len(rides)}건 ({rides[0]['rented_at']} ~ {rides[-1]['rented_at']})")

    # 적재가 실패해도 긁은 결과를 잃지 않는다. 브라우저로 수십 페이지를
    # 도는 작업이라 다시 긁는 비용이 크다. 개인 이동기록이므로 저장소가
    # 아니라 저장소 밖에 둔다.
    dump = pathlib.Path(os.environ.get("RIDES_DUMP", "/tmp/rides_latest.json"))
    dump.write_text(json.dumps(rides, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[백업] {dump}")

    client = make_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
    print(f"[적재] {upsert_rides(client, rides)}건 upsert")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
