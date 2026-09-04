import pytest

from collector.store import upsert_snapshots, upsert_stations


class FakeTable:
    def __init__(self, recorder, name):
        self.recorder = recorder
        self.name = name

    def upsert(self, rows, **kwargs):
        self.recorder.append({"table": self.name, "rows": rows, "kwargs": kwargs})
        return self

    def execute(self):
        return None


class FakeClient:
    def __init__(self):
        self.calls = []

    def table(self, name):
        return FakeTable(self.calls, name)


def test_스냅샷은_충돌하면_무시한다():
    client = FakeClient()

    count = upsert_snapshots(client, [{"station_id": "ST-4"}])

    assert count == 1
    assert client.calls[0]["table"] == "station_snapshot"
    assert client.calls[0]["kwargs"]["on_conflict"] == "station_id,captured_at"
    assert client.calls[0]["kwargs"]["ignore_duplicates"] is True


def test_대여소_마스터는_덮어쓴다():
    client = FakeClient()

    count = upsert_stations(client, [{"station_id": "ST-4"}])

    assert count == 1
    assert client.calls[0]["table"] == "station"
    assert client.calls[0]["kwargs"]["on_conflict"] == "station_id"
    assert client.calls[0]["kwargs"].get("ignore_duplicates") is not True


def test_빈_목록이면_호출하지_않는다():
    client = FakeClient()

    assert upsert_snapshots(client, []) == 0
    assert client.calls == []


class FlakyClient:
    """execute()가 fail_times번 실패한 뒤 성공하는 가짜 클라이언트.

    재수집이 불가능한 스냅샷 적재가 재시도 없이 한 번 삐끗해서 영영
    유실되는 것을 막는 로직을 검증하는 데 쓴다.
    """

    def __init__(self, fail_times):
        self.calls = []
        self.fail_times = fail_times
        self.attempts = 0

    def table(self, name):
        return _FlakyTable(self, name)


class _FlakyTable:
    def __init__(self, client, name):
        self.client = client
        self.name = name

    def upsert(self, rows, **kwargs):
        self.rows = rows
        self.kwargs = kwargs
        return self

    def execute(self):
        self.client.attempts += 1
        self.client.calls.append(
            {"table": self.name, "rows": self.rows, "kwargs": self.kwargs}
        )
        if self.client.attempts <= self.client.fail_times:
            raise RuntimeError("일시적인 저장 실패")
        return None


def test_스냅샷_저장이_일시적으로_실패하면_재시도한다(monkeypatch):
    monkeypatch.setattr("collector.store.time.sleep", lambda _seconds: None)
    client = FlakyClient(fail_times=2)

    count = upsert_snapshots(client, [{"station_id": "ST-4"}])

    assert count == 1
    assert client.attempts == 3


def test_스냅샷_저장이_재시도_후에도_실패하면_예외를_올린다(monkeypatch):
    monkeypatch.setattr("collector.store.time.sleep", lambda _seconds: None)
    client = FlakyClient(fail_times=99)

    with pytest.raises(Exception):
        upsert_snapshots(client, [{"station_id": "ST-4"}])
