"""로그인해서 이용내역 페이지를 받아 구조만 훑는다. 파서 설계용 1회성 스크립트.

내역 HTML에는 본인 이동 기록이 들어 있다. 저장소에 커밋되지 않도록
스크래치패드에 저장하고, 화면에는 구조 요약만 찍는다.
"""
import os
import pathlib
import re
import sys
from html.parser import HTMLParser

from dotenv import load_dotenv

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from collector.bikeseoul import BASE, LoginError, login, make_session, session_from_cookie  # noqa: E402

HISTORY = f"{BASE}/app/mybike/getMemberUseHistory.do"
OUT_DIR = pathlib.Path(
    os.environ.get("DUMP_DIR", "/private/tmp/claude-501/-Users-uicheol-hwang-my-bike-riding/1c66dd67-a264-48fd-a0dd-f703ad29f8f9/scratchpad")
)


class Outline(HTMLParser):
    """폼/입력/테이블 뼈대만 뽑는다. 값(개인정보)은 담지 않는다."""

    def __init__(self):
        super().__init__()
        self.forms, self.inputs, self.selects = [], [], []
        self.tables, self.th, self.tr_count = 0, [], 0
        self._in_th = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            self.forms.append((a.get("name"), a.get("id"), a.get("action"), a.get("method")))
        elif tag in ("input", "select"):
            target = self.inputs if tag == "input" else self.selects
            target.append((tag, a.get("type"), a.get("name"), a.get("id")))
        elif tag == "table":
            self.tables += 1
        elif tag == "tr":
            self.tr_count += 1
        elif tag == "th":
            self._in_th = True

    def handle_endtag(self, tag):
        if tag == "th":
            self._in_th = False

    def handle_data(self, data):
        if self._in_th and data.strip():
            self.th.append(data.strip())


def main() -> int:
    load_dotenv()
    # 세션 쿠키가 있으면 그걸 쓴다. 로그인 자동화는 시도하지 않는다.
    sid = os.environ.get("BIKESEOUL_SESSION", "").strip()
    try:
        if sid:
            session = session_from_cookie(sid)
            print("[세션] 브라우저 세션 재사용")
        else:
            session = make_session()
            login(session, os.environ.get("BIKESEOUL_ID", ""), os.environ.get("BIKESEOUL_PW", ""))
            print("[세션] 자동 로그인 성공")
    except LoginError as exc:
        print(f"[실패] {exc}")
        return 1

    resp = session.get(HISTORY, timeout=15)
    print(f"[조회] status={resp.status_code} final_url={resp.url} bytes={len(resp.content)}")
    if "login.do" in resp.url:
        print("[실패] 내역 페이지가 로그인으로 되돌렸다. 세션이 안 붙었다.")
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "my_history.html"
    out.write_text(resp.text, encoding="utf-8")
    print(f"[저장] {out}")

    o = Outline()
    o.feed(resp.text)
    print("\n--- form ---")
    for f in o.forms:
        print(f"  name={f[0]} id={f[1]} action={f[2]} method={f[3]}")
    print("--- input / select (name만) ---")
    for i in o.inputs + o.selects:
        print(f"  <{i[0]}> type={i[1]} name={i[2]} id={i[3]}")
    print(f"--- table: {o.tables}개, tr: {o.tr_count}행 ---")
    print(f"  th: {o.th}")

    js = set(re.findall(r"function\s+(\w*(?:[Ss]earch|[Pp]age|[Ll]ist|[Ee]xcel)\w*)\s*\(", resp.text))
    print(f"--- 조회/페이징 관련 함수 후보: {sorted(js)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
