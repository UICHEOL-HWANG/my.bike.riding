"""최근 7일치 과거 재고를 시간 단위로 백필한다.

7일 창은 하루가 지날 때마다 하루씩 사라진다. 미루면 그만큼 영구 손실이다.

이미 채운 시각은 건너뛰므로 중단돼도 다시 돌리면 이어간다.

    uv run python scripts/backfill_history.py
    uv run python scripts/backfill_history.py --days 2
"""
import os
import pathlib
import sys
import time
from datetime import datetime, timezone

from dotenv import load_dotenv

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from collector.api import SeoulApiError  # noqa: E402
from collector.backfill import PAUSE, build_hist_rows, captured_at_of, fetch_hour, hours_back, station_dt  # noqa: E402
from collector.config import load_station_ids  # noqa: E402
from collector.db import connect  # noqa: E402
from collector.store import make_client, upsert_snapshots, upsert_stations  # noqa: E402


def already_done(days: int) -> set[str]:
    """이미 백필한 시각. 중단 후 재실행을 싸게 만든다."""
    with connect() as c, c.cursor() as cur:
        cur.execute("""select distinct captured_at from station_snapshot
                        where source = 'hist'""")
        return {station_dt(r[0]) for r in cur.fetchall()}


def main() -> int:
    load_dotenv(ROOT / ".env")
    days = int(sys.argv[sys.argv.index("--days") + 1]) if "--days" in sys.argv else 7

    station_ids = load_station_ids(ROOT / "stations.yml")
    key = os.environ["SEOUL_API_KEY"]
    client = make_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

    done = already_done(days)
    hours = [station_dt(h) for h in hours_back(datetime.now(timezone.utc), days)]
    todo = [h for h in hours if h not in done]
    print(f"[대상] {len(hours)}시각 중 {len(todo)}시각 (이미 완료 {len(done)})")

    ok = skipped = failed = rows = 0
    for i, dt_text in enumerate(todo, 1):
        try:
            raw = fetch_hour(key, dt_text)
        except SeoulApiError as exc:
            # 한 시각이 실패해도 나머지를 포기하지 않는다. 7일 창 안에서는
            # 다시 돌리면 되고, 안 채워진 시각은 다음 실행 대상으로 남는다.
            print(f"  [{i}/{len(todo)}] {dt_text} 실패: {exc}")
            failed += 1
            continue
        if not raw:
            # 7일 창을 벗어났거나 그 시각 기록이 없다.
            skipped += 1
            continue
        snaps, stations = build_hist_rows(raw, station_ids, dt_text)
        if snaps:
            rows += upsert_snapshots(client, snaps)
            upsert_stations(client, stations)
        ok += 1
        if i % 24 == 0 or i == len(todo):
            print(f"  [{i}/{len(todo)}] {dt_text}까지 — 성공 {ok}, 빈시각 {skipped}, 실패 {failed}, {rows}행")
        time.sleep(PAUSE)

    print(f"[결과] 시각 {ok}개 적재, 빈시각 {skipped}, 실패 {failed}, 총 {rows}행 전송")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
