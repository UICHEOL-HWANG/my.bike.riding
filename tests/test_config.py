from pathlib import Path

import pytest

from collector.config import load_settings, load_station_ids


def test_main과_fallback을_하나의_집합으로_합친다(tmp_path):
    p = tmp_path / "stations.yml"
    p.write_text("main: [ST-4, ST-5]\nfallback: [ST-9]\n", encoding="utf-8")

    assert load_station_ids(p) == frozenset({"ST-4", "ST-5", "ST-9"})


def test_빈_목록이면_에러를_낸다(tmp_path):
    p = tmp_path / "stations.yml"
    p.write_text("main: []\nfallback: []\n", encoding="utf-8")

    with pytest.raises(ValueError, match="대여소"):
        load_station_ids(p)


def test_키가_없으면_에러를_낸다(tmp_path, monkeypatch):
    monkeypatch.delenv("SEOUL_API_KEY", raising=False)
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "k")
    p = tmp_path / "stations.yml"
    p.write_text("main: [ST-4]\nfallback: []\n", encoding="utf-8")

    # load_env=False가 없으면 로컬 .env가 지운 변수를 도로 채워 테스트가 환경을 탄다.
    with pytest.raises(ValueError, match="SEOUL_API_KEY"):
        load_settings(p, load_env=False)


def test_비밀번호에_슬래시가_있어도_쪼갠다():
    # Supabase가 만드는 비밀번호에 '/'가 섞이면 URI 파서가 호스트 경계를
    # 잘못 잡는다. 실제로 이 프로젝트에서 겪은 경우다.
    from collector.db import parse_db_url

    got = parse_db_url("postgresql://postgres.abc:pa/ss word@db.host.com:5432/postgres")
    assert got == {
        "user": "postgres.abc",
        "password": "pa/ss word",
        "host": "db.host.com",
        "port": 5432,
        "dbname": "postgres",
    }


def test_포트가_없으면_5432다():
    from collector.db import parse_db_url

    assert parse_db_url("postgresql://u:p@h.com/postgres")["port"] == 5432


def test_형식이_아니면_거부한다():
    import pytest

    from collector.db import parse_db_url

    with pytest.raises(ValueError):
        parse_db_url("mysql://u:p@h/db")
