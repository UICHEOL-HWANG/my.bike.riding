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
