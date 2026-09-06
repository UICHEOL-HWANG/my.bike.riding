"""따릉이 회원 페이지 로그인 세션.

이용내역은 공공 오픈데이터에 없다(집계본만 있고 개인 식별자가 없다).
본인 계정에 로그인해야만 얻을 수 있어서 여기서 세션을 만든다.

주의: 이 모듈의 어떤 에러 메시지에도 비밀번호가 들어가면 안 된다.
requests 예외를 그대로 문자열로 만들면 요청 본문이 딸려 나올 수 있으므로
예외 타입 이름만 남긴다 — api.py의 인증키 처리와 같은 이유다.
"""

import requests

BASE = "https://www.bikeseoul.com"
LOGIN_FORM = f"{BASE}/login.do"
LOGIN_POST = f"{BASE}/j_spring_security_check"
TIMEOUT = 15

# 기본 python-requests UA로는 응답이 달라질 수 있어 브라우저 UA를 쓴다.
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
)


class LoginError(Exception):
    pass


def session_from_cookie(jsessionid: str) -> requests.Session:
    """브라우저에서 사람이 로그인한 세션을 그대로 물려받는다.

    로그인 자동화를 하지 않는 이유: 이 스크립트는 한 달에 한 번 돌리면
    되는 물건이라, CSRF·봇판별·계정잠금을 뚫는 비용이 얻는 것보다 크다.
    사람이 로그인하면 사이트가 로그인 방식을 바꿔도 안 깨진다.
    """
    if not jsessionid:
        raise LoginError("BIKESEOUL_SESSION이 비어 있다. 브라우저에서 JSESSIONID를 복사해 .env에 넣을 것.")
    session = make_session()
    session.cookies.set("JSESSIONID", jsessionid, domain="www.bikeseoul.com", path="/")
    return session


def check_logged_in(session: requests.Session, url: str) -> None:
    """세션이 살아 있는지 확인한다. 만료되면 login.do로 튕긴다."""
    resp = session.get(url, timeout=TIMEOUT)
    if "login.do" in resp.url:
        raise LoginError(
            "세션이 만료됐다. 브라우저에서 다시 로그인하고 JSESSIONID를 .env에 갱신할 것."
        )
    resp.raise_for_status()


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": UA})
    return session


def login(session: requests.Session, user_id: str, password: str) -> requests.Session:
    """로그인해서 세션에 인증 쿠키를 심는다.

    로그인 POST 전에 폼 페이지를 먼저 받아야 한다. 서버가 그 시점에
    JSESSIONID를 발급하고, 그 세션에 인증이 붙는 구조다.
    """
    if not user_id or not password:
        raise LoginError("BIKESEOUL_ID / BIKESEOUL_PW가 비어 있다.")

    try:
        session.get(LOGIN_FORM, timeout=TIMEOUT).raise_for_status()
    except requests.RequestException as exc:
        raise LoginError(f"로그인 폼을 받지 못했다({type(exc).__name__})") from None

    try:
        # allow_redirects=False가 핵심이다. 리다이렉트를 따라가면 성공/실패가
        # 둘 다 200 HTML로 끝나 구분이 안 된다. Location 헤더로 판정한다.
        resp = session.post(
            LOGIN_POST,
            data={
                "j_username": user_id,
                "j_password": password,
                "appOsType": "web",
                "usrDeviceId": "",
                "hyLink": "",
                "orgType": "",
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": BASE,
                "Referer": LOGIN_FORM,
            },
            allow_redirects=False,
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        # exc를 그대로 넣으면 요청 본문(비밀번호 포함)이 딸려올 수 있다.
        raise LoginError(f"로그인 요청이 실패했다({type(exc).__name__})") from None

    location = resp.headers.get("Location", "")
    if resp.status_code not in (301, 302, 303, 307, 308):
        raise LoginError(
            f"로그인 응답이 리다이렉트가 아니다(status={resp.status_code}). "
            "폼 구조가 바뀌었을 수 있다."
        )
    if "login.do" in location:
        # 스프링 시큐리티는 실패 시 로그인 폼으로 되돌린다.
        raise LoginError(f"로그인이 거부됐다. 아이디/비밀번호를 확인할 것. (→ {location})")

    return session
