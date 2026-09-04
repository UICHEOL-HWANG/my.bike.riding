from dataclasses import replace
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
    # 스냅샷을 먼저 적재하고 대여소 마스터를 나중에 적재한다는 순서는
    # 의도된 결정이다 — 재수집 불가능한 데이터를 먼저 안전하게 남긴다.
    assert client.calls[0]["table"] == "station_snapshot"
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


def test_parking_cnt가_전부_None이면_실패로_끝나고_적재하지_않는다():
    client = FakeClient()
    broken_row = {**ROW, "parkingBikeTotCnt": "필드명이_바뀜"}

    code = run(SETTINGS, now=NOW, fetch=lambda key: ([broken_row], None), client=client)

    assert code == 1
    assert client.calls == [], "전부 None인 스냅샷은 적재하면 안 된다"


def test_일부_대여소만_parking_cnt가_None이면_성공으로_끝난다():
    client = FakeClient()
    settings = replace(SETTINGS, station_ids=frozenset({"ST-4", "ST-5"}))
    row_missing = {**ROW, "stationId": "ST-5", "parkingBikeTotCnt": "없음"}

    code = run(
        settings, now=NOW, fetch=lambda key: ([ROW, row_missing], None), client=client
    )

    assert code == 0


class StationFailingClient(FakeClient):
    """station 테이블 적재만 실패하는 가짜 클라이언트.

    대여소 마스터(이름·좌표)는 언제든 다시 채울 수 있는 정보라 여기서
    실패해도 재수집 불가능한 스냅샷 적재나 종료 코드 판단을 막으면 안 된다.
    """

    def table(self, name):
        table = super().table(name)
        if name == "station":

            def boom(*args, **kwargs):
                raise RuntimeError("station upsert 실패")

            table.upsert = boom
        return table


def test_대여소_마스터_적재_실패는_전체_실행을_막지_않는다():
    client = StationFailingClient()

    code = run(SETTINGS, now=NOW, fetch=lambda key: ([ROW], None), client=client)

    assert code == 0
    assert client.calls[0]["table"] == "station_snapshot"
