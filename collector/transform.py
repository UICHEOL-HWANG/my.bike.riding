from datetime import datetime


def floor_to_grid(ts: datetime, grid_minutes: int) -> datetime:
    """수집 시각을 격자로 내린다.

    cron 지연으로 실행 시각이 흔들려도 같은 격자에 떨어지게 해서
    unique(station_id, captured_at)이 중복을 실제로 막게 한다.
    """
    return ts.replace(
        minute=(ts.minute // grid_minutes) * grid_minutes, second=0, microsecond=0
    )


def to_int(value: object) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def to_float(value: object) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def build_rows(
    raw_rows: list[dict],
    station_ids: frozenset[str],
    captured_at: datetime,
    fetched_at: datetime,
) -> tuple[list[dict], list[dict]]:
    captured = captured_at.isoformat()
    fetched = fetched_at.isoformat()

    snapshots: dict[str, dict] = {}
    stations: dict[str, dict] = {}

    for raw in raw_rows:
        station_id = str(raw.get("stationId", "")).strip()
        if not station_id or station_id not in station_ids:
            continue
        if station_id in snapshots:
            continue

        snapshots[station_id] = {
            "station_id": station_id,
            "captured_at": captured,
            "fetched_at": fetched,
            "parking_cnt": to_int(raw.get("parkingBikeTotCnt")),
            "rack_total": to_int(raw.get("rackTotCnt")),
            "shared": to_int(raw.get("shared")),
        }
        stations[station_id] = {
            "station_id": station_id,
            "name": raw.get("stationName"),
            "lat": to_float(raw.get("stationLatitude")),
            "lon": to_float(raw.get("stationLongitude")),
            "updated_at": fetched,
        }

    return list(snapshots.values()), list(stations.values())
