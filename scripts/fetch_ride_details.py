"""이용내역 건별 상세(이용시간·칼로리·탄소절감·추가과금)를 채운다.

목록에 없는 값이라 건마다 페이지를 열어야 한다. 168건이면 수백 번의
이동이므로, 이미 채운 건은 건너뛰어 중단돼도 이어서 돌 수 있게 한다.

    uv run python scripts/fetch_ride_details.py
    uv run python scripts/fetch_ride_details.py --limit 20   # 일부만
"""
import os
import pathlib
import sys
import time

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from collector.my_ride import fetch_detail_via_page  # noqa: E402
from collector.store import make_client  # noqa: E402

LOGIN = "https://www.bikeseoul.com/login.do"
HISTORY = "https://www.bikeseoul.com/app/mybike/getMemberUseHistory.do"

# 사이트에 부담을 주지 않도록 건마다 잠깐 쉰다.
PAUSE = 0.3


def main() -> int:
    load_dotenv(ROOT / ".env")
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    client = make_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
    # 이미 채운 건은 다시 열지 않는다 — 중단 후 재실행이 싸다.
    todo = (
        client.table("my_ride")
        .select("rent_hist_seq,rented_at")
        .is_("duration_min", "null")
        .order("rented_at", desc=True)
        .execute()
        .data
    )
    if limit:
        todo = todo[:limit]
    if not todo:
        print("[완료] 채울 건이 없다.")
        return 0
    print(f"[대상] {len(todo)}건")

    done = failed = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale="ko-KR")
        page.goto(LOGIN, wait_until="domcontentloaded")
        page.fill("#memid", os.environ["BIKESEOUL_ID"])
        page.fill("#mempw", os.environ["BIKESEOUL_PW"])
        with page.expect_navigation(wait_until="domcontentloaded", timeout=20000):
            page.evaluate("loginSubmit()")
        if "login.do" in page.url:
            print("[실패] 로그인 거부됨")
            browser.close()
            return 1
        print("[로그인] 성공")

        for i, ride in enumerate(todo, 1):
            seq = ride["rent_hist_seq"]
            try:
                detail = fetch_detail_via_page(page, HISTORY, seq)
            except Exception as exc:  # noqa: BLE001
                # 한 건이 실패해도 나머지를 포기하지 않는다. 안 채워진 건은
                # 다음 실행에서 다시 대상이 된다.
                print(f"  [{i}/{len(todo)}] {seq} 실패: {type(exc).__name__}")
                failed += 1
                continue
            if detail["duration_min"] is None:
                print(f"  [{i}/{len(todo)}] {seq} 값 없음 — 화면 구조 확인 필요")
                failed += 1
                continue
            client.table("my_ride").update(detail).eq("rent_hist_seq", seq).execute()
            done += 1
            if i % 20 == 0 or i == len(todo):
                print(f"  [{i}/{len(todo)}] 진행 중 (성공 {done}, 실패 {failed})")
            time.sleep(PAUSE)
        browser.close()

    print(f"[결과] 성공 {done}건, 실패 {failed}건")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
