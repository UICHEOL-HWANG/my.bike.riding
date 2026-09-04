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
    # 재수집이 불가능한 스냅샷을 먼저 적재하고, 언제든 다시 채울 수 있는
    # 대여소 마스터 정보를 그 다음에 적재한다.
    count = upsert_snapshots(client, snapshots)
    upsert_stations(client, stations)

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
