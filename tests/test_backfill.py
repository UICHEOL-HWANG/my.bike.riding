from datetime import datetime, timedelta, timezone

from collector.backfill import (
    build_hist_rows,
    captured_at_of,
    hours_back,
    station_dt,
)

UTC = timezone.utc


def test_UTC를_KST_문자열로_바꾼다():
    assert station_dt(datetime(2026, 9, 6, 12, 0, tzinfo=UTC)) == "2026090621"


def test_날짜_경계를_넘긴다():
    # 15:00 UTC는 KST로 다음날 00시다. 여기서 틀리면 하루가 통째로 어긋난다.
    assert station_dt(datetime(2026, 9, 6, 15, 0, tzinfo=UTC)) == "2026090700"


def test_KST_문자열을_UTC로_되돌린다():
    assert captured_at_of("2026090621") == datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
    assert captured_at_of("2026090700") == datetime(2026, 9, 6, 15, 0, tzinfo=UTC)


def test_왕복이_같다():
    for h in range(0, 24, 3):
        t = datetime(2026, 9, 6, h, 0, tzinfo=UTC)
        assert captured_at_of(station_dt(t)) == t


def test_오래된_시각부터_돌려준다():
    # 7일 경계에 가장 가까운 시각이 가장 먼저 사라진다. 중간에 끊겨도
    # 사라질 것부터 건지려면 오래된 쪽부터 돌아야 한다.
    hours = list(hours_back(datetime(2026, 9, 6, 13, 5, tzinfo=UTC), days=7))
    assert hours == sorted(hours)
    assert hours[-1] == datetime(2026, 9, 6, 13, 0, tzinfo=UTC)
    assert hours[0] == datetime(2026, 8, 30, 13, 0, tzinfo=UTC)


def test_분초를_버리고_정시로_맞춘다():
    (first,) = list(hours_back(datetime(2026, 9, 6, 13, 59, 59, tzinfo=UTC), days=0))
    assert first == datetime(2026, 9, 6, 13, 0, tzinfo=UTC)


def test_시각_개수가_맞다():
    assert len(list(hours_back(datetime(2026, 9, 6, 0, 0, tzinfo=UTC), days=7))) == 7 * 24 + 1


RAW = [
    {"stationId": "ST-4", "stationName": "102. 망원역", "parkingBikeTotCnt": "7",
     "rackTotCnt": "15", "shared": "47",
     "stationLatitude": "37.5", "stationLongitude": "126.9", "stationDt": "2026090621"},
    {"stationId": "ST-999", "stationName": "관심 밖", "parkingBikeTotCnt": "1",
     "rackTotCnt": "5", "shared": "20",
     "stationLatitude": "37.1", "stationLongitude": "126.1", "stationDt": "2026090621"},
]


def test_백필행에_출처를_남긴다():
    # 시간 단위 백필과 10분 실측을 나중에 구분하지 못하면 분석이 오염된다.
    snaps, _ = build_hist_rows(RAW, frozenset({"ST-4"}), "2026090621")
    assert [s["source"] for s in snaps] == ["hist"]


def test_수신시각을_측정시각과_같게_둔다():
    # 방금 받아왔다고 now()를 넣으면 수신 지연 통계가 오염된다.
    (snap,), _ = build_hist_rows(RAW, frozenset({"ST-4"}), "2026090621")
    assert snap["fetched_at"] == snap["captured_at"]
    assert snap["captured_at"] == datetime(2026, 9, 6, 12, 0, tzinfo=UTC).isoformat()


def test_관심_대여소만_남긴다():
    snaps, stations = build_hist_rows(RAW, frozenset({"ST-4"}), "2026090621")
    assert [s["station_id"] for s in snaps] == ["ST-4"]
    assert [s["station_id"] for s in stations] == ["ST-4"]
    assert snaps[0]["parking_cnt"] == 7
