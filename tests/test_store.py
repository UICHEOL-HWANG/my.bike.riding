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
