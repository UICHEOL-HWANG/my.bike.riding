from datetime import datetime, timezone

from collector.api import SeoulApiError
from collector.config import Settings
from collector.__main__ import run
from tests.test_store import FakeClient

SETTINGS = Settings(
    seoul_api_key="k",
    supabase_url="https://x.supabase.co",
    supabase_service_key="s",
    station_ids=frozenset({"ST-4"}),
    grid_minutes=10,
)
NOW = datetime(2026, 9, 4, 10, 7, 33, tzinfo=timezone.utc)
ROW = {
    "stationId": "ST-4",
    "stationName": "망원역",
    "parkingBikeTotCnt": "3",
    "rackTotCnt": "15",
    "shared": "20",
    "stationLatitude": "37.5",
    "stationLongitude": "126.9",
}


def test_정상이면_0으로_끝난다():
    client = FakeClient()

    code = run(SETTINGS, now=NOW, fetch=lambda key: ([ROW], None), client=client)

    assert code == 0
    snapshot = client.calls[0]["rows"][0]
    assert snapshot["captured_at"] == "2026-09-04T10:00:00+00:00"
    assert snapshot["fetched_at"] == "2026-09-04T10:07:33+00:00"


def test_관심_대여소가_하나도_없으면_실패로_끝난다():
    client = FakeClient()

    code = run(
        SETTINGS,
        now=NOW,
        fetch=lambda key: ([{"stationId": "ST-999"}], None),
        client=client,
    )

    assert code == 1


def test_부분_성공은_적재하되_실패로_끝난다():
    client = FakeClient()

    code = run(
        SETTINGS,
        now=NOW,
        fetch=lambda key: ([ROW], SeoulApiError("2페이지 실패")),
        client=client,
    )

    assert code == 1
    assert client.calls, "받은 데이터는 적재해야 한다"
