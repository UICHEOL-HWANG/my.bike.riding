"""진짜 브라우저로 로그인해 세션 쿠키를 얻는다.

requests로는 서버가 연결을 끊는다(클라이언트 식별). 탐지를 회피하는 대신
실제 브라우저를 쓴다 — 위장하지 않고 있는 그대로 접속한다.

로그인만 여기서 하고, 내역 수집은 기존 requests 코드가 그대로 맡는다.
브라우저는 인증에만 필요하고 파싱까지 끌고 갈 이유가 없다.

    uv run python scripts/login_playwright.py           # 창을 띄워 눈으로 확인
    uv run python scripts/login_playwright.py --headless
"""
import os
import pathlib
import re
import sys

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
LOGIN = "https://www.bikeseoul.com/login.do"
HISTORY = "https://www.bikeseoul.com/app/mybike/getMemberUseHistory.do"


def save_session(value: str) -> None:
    """.env의 BIKESEOUL_SESSION만 갈아끼운다. 값은 출력하지 않는다."""
    env = ROOT / ".env"
    lines = [l for l in env.read_text(encoding="utf-8").splitlines()
             if not l.startswith("BIKESEOUL_SESSION=")]
    lines.append(f"BIKESEOUL_SESSION={value}")
    env.write_text("\n".join(lines) + "\n", encoding="utf-8")
    env.chmod(0o600)


def main() -> int:
    load_dotenv(ROOT / ".env")
    user = os.environ.get("BIKESEOUL_ID", "")
    pw = os.environ.get("BIKESEOUL_PW", "")
    if not user or not pw:
        print("[실패] .env에 BIKESEOUL_ID / BIKESEOUL_PW가 필요하다.")
        return 1

    headless = "--headless" in sys.argv
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, slow_mo=0 if headless else 250)
        page = browser.new_page(locale="ko-KR")
        page.goto(LOGIN, wait_until="domcontentloaded")
        print(f"[1] 로그인 페이지: {page.url}")

        page.fill("#memid", user)
        page.fill("#mempw", pw)
        print(f"[2] 입력 완료 (id {len(user)}자, pw {len(pw)}자)")

        # 폼 제출 후 이동이 끝날 때까지 기다린다.
        with page.expect_navigation(wait_until="domcontentloaded", timeout=20000):
            page.evaluate("loginSubmit()")
        print(f"[3] 제출 후 URL: {page.url}")

        # 이게 지금까지 못 본 정보다 — 사이트가 뭐라고 하는지.
        body = page.inner_text("body")
        for line in body.splitlines():
            s = line.strip()
            if re.search(r"오류|실패|일치|잠금|잠겼|확인|다시|비밀번호|아이디", s) and 2 < len(s) < 120:
                print(f"    화면 문구: {s}")

        page.goto(HISTORY, wait_until="domcontentloaded")
        print(f"[4] 내역 페이지 -> {page.url}")

        if "login.do" in page.url:
            print("[판정] ❌ 인증 실패 (내역 페이지가 로그인으로 되돌림)")
            if not headless:
                input("    창을 확인하고 Enter를 누르면 닫습니다... ")
            browser.close()
            return 1

        sid = next((c["value"] for c in page.context.cookies()
                    if c["name"] == "JSESSIONID"), None)
        if not sid:
            print("[판정] ⚠️ 인증은 됐는데 JSESSIONID를 못 찾았다.")
            browser.close()
            return 1

        save_session(sid)
        print("[판정] ✅ 로그인 성공. .env의 BIKESEOUL_SESSION 갱신됨")
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
