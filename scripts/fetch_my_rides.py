"""본인 이용내역을 받아 Supabase에 적재한다.

재고 수집기와 달리 상시로 돌 필요가 없다. 이용내역은 계정에 남아 있어
사라지지 않으므로, 가끔 실행해 신규분만 붙이면 된다.

    uv run python scripts/fetch_my_rides.py            # 기본: 최근 2년
    uv run python scripts/fetch_my_rides.py 2023-01-01 # 시작일 지정
"""
import os
import pathlib
import sys
from datetime import date, timedelta

from dotenv import load_dotenv

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from collector.bikeseoul import LoginError, session_from_cookie  # noqa: E402
from collector.my_ride import fetch_all  # noqa: E402
from collector.store import make_client, upsert_rides  # noqa: E402


def main() -> int:
    load_dotenv(pathlib.Path(__file__).resolve().parent.parent / ".env")

    start = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date.today() - timedelta(days=730)
    end = date.today()

    try:
        session = session_from_cookie(os.environ.get("BIKESEOUL_SESSION", "").strip())
    except LoginError as exc:
        print(f"[실패] {exc}")
        return 1

    print(f"[조회] {start} ~ {end}")
    rides = fetch_all(session, start, end)
    if not rides:
        # 세션 만료와 "정말 내역이 없음"은 다르다. 조용히 0건으로 넘기면
        # 만료를 못 알아챈다.
        print("[경고] 0건이다. 세션이 만료됐을 수 있다. BIKESEOUL_SESSION을 갱신할 것.")
        return 1
    print(f"[수집] {len(rides)}건 ({rides[0]['rented_at']} ~ {rides[-1]['rented_at']})")

    client = make_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
    print(f"[적재] {upsert_rides(client, rides)}건 upsert")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
