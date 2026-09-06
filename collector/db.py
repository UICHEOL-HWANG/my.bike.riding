"""Supabase Postgres 직접 접속.

스케줄러(pg_cron)와 확장 설치는 DDL이라 PostgREST로는 못 한다. 여기서만
직접 접속을 쓰고, 평상시 적재는 store.py의 REST 경로를 그대로 쓴다.

접속 문자열을 psycopg에 URI 그대로 넘기지 않는다. Supabase가 생성하는
DB 비밀번호에는 '/'나 '@'가 섞일 수 있는데, 그러면 URI 파서가 호스트
경계를 잘못 잡는다. 직접 쪼개 키워드 인자로 넘기면 인코딩 문제가 없다.
"""

import os
import re

import psycopg

_URI = re.compile(r"^postgres(?:ql)?://([^:]+):(.*)@([^@/]+?)(?::(\d+))?/(.+)$")


def parse_db_url(url: str) -> dict:
    m = _URI.match(url.strip())
    if not m:
        raise ValueError("SUPABASE_DB_URL이 postgresql://user:pw@host:port/db 형식이 아니다.")
    user, password, host, port, dbname = m.groups()
    return {
        "user": user,
        "password": password,
        "host": host,
        "port": int(port or 5432),
        "dbname": dbname,
    }


def connect(url: str | None = None, **kw):
    url = url or os.environ.get("SUPABASE_DB_URL", "")
    if not url:
        raise ValueError("SUPABASE_DB_URL이 비어 있다.")
    return psycopg.connect(**parse_db_url(url), connect_timeout=15, **kw)
