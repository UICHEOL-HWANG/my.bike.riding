from datetime import datetime, timezone

from collector.transform import build_rows, floor_to_grid, to_float, to_int

KST_ROW = {
    "stationId": "ST-4",
    "stationName": "102. 망원역 1번출구 앞",
    "parkingBikeTotCnt": "3",
    "rackTotCnt": "15",
    "shared": "20",
    "stationLatitude": "37.55564880",
    "stationLongitude": "126.91062927",
}


def _dt(h, m, s=0):
    return datetime(2026, 9, 4, h, m, s, tzinfo=timezone.utc)


def test_격자_경계에서_내림한다():
    assert floor_to_grid(_dt(10, 0, 0), 10) == _dt(10, 0)
    assert floor_to_grid(_dt(10, 9, 59), 10) == _dt(10, 0)
    assert floor_to_grid(_dt(10, 10, 0), 10) == _dt(10, 10)


def test_마이크로초까지_버린다():
    ts = datetime(2026, 9, 4, 10, 7, 33, 123456, tzinfo=timezone.utc)
    assert floor_to_grid(ts, 10) == _dt(10, 0)


def test_문자열_숫자를_정수로_바꾼다():
    assert to_int("15") == 15
    assert to_int(15) == 15


def test_숫자가_아니면_None을_준다():
    assert to_int("") is None
    assert to_int(None) is None
    assert to_int("없음") is None


def test_to_float_문자열_숫자를_실수로_바꾼다():
    assert to_float("37.5") == 37.5
    assert to_float(37.5) == 37.5


def test_to_float_숫자가_아니면_None을_준다():
    assert to_float("") is None
    assert to_float(None) is None
    assert to_float("없음") is None


def test_to_float_유한하지_않은_값은_None을_준다():
    assert to_float("nan") is None
    assert to_float("inf") is None
    assert to_float("-inf") is None


def test_관심_대여소만_남긴다():
    rows = [KST_ROW, {**KST_ROW, "stationId": "ST-999"}]

    snapshots, _ = build_rows(rows, frozenset({"ST-4"}), _dt(10, 0), _dt(10, 3))

    assert [r["station_id"] for r in snapshots] == ["ST-4"]


def test_스냅샷_행의_모양():
    snapshots, _ = build_rows([KST_ROW], frozenset({"ST-4"}), _dt(10, 0), _dt(10, 3))

    assert snapshots[0] == {
        "station_id": "ST-4",
        "captured_at": "2026-09-04T10:00:00+00:00",
        "fetched_at": "2026-09-04T10:03:00+00:00",
        "parking_cnt": 3,
        "rack_total": 15,
        "shared": 20,
    }


def test_대여소_마스터_행의_모양():
    _, stations = build_rows([KST_ROW], frozenset({"ST-4"}), _dt(10, 0), _dt(10, 3))

    assert stations[0]["station_id"] == "ST-4"
    assert stations[0]["name"] == "102. 망원역 1번출구 앞"
    assert stations[0]["lat"] == 37.55564880
    assert stations[0]["lon"] == 126.91062927
    assert stations[0]["updated_at"] == "2026-09-04T10:03:00+00:00"


def test_같은_대여소가_두_번_와도_한_행만_남긴다():
    rows = [KST_ROW, {**KST_ROW, "parkingBikeTotCnt": "7"}]

    snapshots, stations = build_rows(rows, frozenset({"ST-4"}), _dt(10, 0), _dt(10, 3))

    assert len(snapshots) == 1
    assert len(stations) == 1


def test_필드가_없어도_터지지_않는다():
    snapshots, _ = build_rows(
        [{"stationId": "ST-4"}], frozenset({"ST-4"}), _dt(10, 0), _dt(10, 3)
    )

    assert snapshots[0]["parking_cnt"] is None
    assert snapshots[0]["rack_total"] is None
