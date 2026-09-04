import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

GRID_MINUTES = 10

# collector/config.py 기준 저장소 루트. CWD가 어디든(예: cron이 다른
# 디렉터리에서 실행) stations.yml 기본 경로가 흔들리지 않게 한다.
_REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    seoul_api_key: str
    supabase_url: str
    supabase_service_key: str
    station_ids: frozenset[str]
    grid_minutes: int


def load_station_ids(path: Path) -> frozenset[str]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    ids = frozenset(
        str(s).strip()
        for key in ("main", "fallback")
        for s in (data.get(key) or [])
        if str(s).strip()
    )
    if not ids:
        raise ValueError(f"{path}에 관심 대여소가 하나도 없다. main 또는 fallback을 채울 것.")
    return ids


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"환경변수 {name}이 비어 있다.")
    return value


def load_settings(
    stations_path: Path = _REPO_ROOT / "stations.yml", *, load_env: bool = True
) -> Settings:
    # 테스트는 load_env=False로 부른다. 로컬 .env가 테스트 환경을 오염시키지 않도록.
    if load_env:
        load_dotenv()
    return Settings(
        seoul_api_key=_require_env("SEOUL_API_KEY"),
        supabase_url=_require_env("SUPABASE_URL"),
        supabase_service_key=_require_env("SUPABASE_SERVICE_KEY"),
        station_ids=load_station_ids(stations_path),
        grid_minutes=GRID_MINUTES,
    )
