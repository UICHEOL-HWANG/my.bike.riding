import time

from supabase import Client, create_client

# API 호출은 10분 뒤 다시 받을 수 있지만 스냅샷 적재는 그럴 수 없다.
# fetch_page과 같은 간격으로 재시도한다 — 두 곳뿐이라 공용 재시도
# 프레임워크를 만들지 않고 그대로 베낀다.
RETRY_WAITS = (1, 2, 4)


def make_client(url: str, service_key: str) -> Client:
    # service_role 키를 쓴다. anon 키는 RLS에 막혀 적재하지 못한다.
    return create_client(url, service_key)


def upsert_snapshots(client, rows: list[dict]) -> int:
    if not rows:
        return 0

    last_error: Exception | None = None
    for wait in (*RETRY_WAITS, None):
        try:
            client.table("station_snapshot").upsert(
                rows, on_conflict="station_id,captured_at", ignore_duplicates=True
            ).execute()
            return len(rows)
        except Exception as exc:  # noqa: BLE001 - supabase 예외 타입을 특정하지 않는다.
            last_error = exc
            if wait is None:
                break
            time.sleep(wait)

    raise last_error


def upsert_stations(client, rows: list[dict]) -> int:
    if not rows:
        return 0
    client.table("station").upsert(rows, on_conflict="station_id").execute()
    return len(rows)


def upsert_rides(client, rows: list[dict]) -> int:
    """본인 이용내역. rent_hist_seq가 유일한 안정적 식별자다 —
    대여일시는 같은 분에 두 건이 생길 수 있어 키로 쓸 수 없다."""
    if not rows:
        return 0
    client.table("my_ride").upsert(rows, on_conflict="rent_hist_seq").execute()
    return len(rows)
