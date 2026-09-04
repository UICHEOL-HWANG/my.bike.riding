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
