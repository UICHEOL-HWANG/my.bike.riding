import re
import time

import requests

BASE = "http://openapi.seoul.go.kr:8088"
OK_CODE = "INFO-000"
TIMEOUT = 10
RETRY_WAITS = (1, 2, 4)

# 인증키 오류 등 API가 XML로 돌려주는 실패 응답에서 CODE/MESSAGE를 뽑아낸다.
# JSON 파싱에 실패했을 때만 시도하는 보조 경로이므로 정규식으로 충분하다.
_XML_CODE_RE = re.compile(r"<CODE>(.*?)</CODE>", re.IGNORECASE | re.DOTALL)
_XML_MESSAGE_RE = re.compile(r"<MESSAGE>(.*?)</MESSAGE>", re.IGNORECASE | re.DOTALL)


class SeoulApiError(Exception):
    pass


def _xml_error(text: str) -> tuple[str, str] | None:
    """본문이 `<RESULT><CODE>...` 형태의 XML 에러면 (code, message)를 돌려준다.

    본문이 비어있거나 형식이 안 맞으면 조용히 None을 돌려준다 — 새 예외를 만들지 않는다.
    """
    if not text:
        return None
    match = _XML_CODE_RE.search(text)
    if not match:
        return None
    message_match = _XML_MESSAGE_RE.search(text)
    message = message_match.group(1).strip() if message_match else ""
    return match.group(1).strip(), message


def fetch_page(
    api_key: str, start: int, end: int, *, session: requests.Session | None = None
) -> list[dict]:
    get = (session or requests).get
    url = f"{BASE}/{api_key}/json/bikeList/{start}/{end}/"

    last_error: Exception | None = None
    for wait in (*RETRY_WAITS, None):
        try:
            resp = get(url, timeout=TIMEOUT)
            resp.raise_for_status()
            try:
                data = resp.json()
            except ValueError:
                xml_error = _xml_error(resp.text)
                if xml_error is not None:
                    code, message = xml_error
                    # 인증키 오류·쿼터 초과는 재시도해도 낫지 않으므로 즉시 올린다.
                    raise SeoulApiError(f"API가 {code}를 반환했다: {message}")
                raise
            payload = data.get("rentBikeStatus") or {}
            code = (payload.get("RESULT") or {}).get("CODE")
            if code != OK_CODE:
                message = (payload.get("RESULT") or {}).get("MESSAGE", "")
                # 인증키 오류·쿼터 초과는 재시도해도 낫지 않으므로 즉시 올린다.
                raise SeoulApiError(f"API가 {code}를 반환했다: {message}")
            return list(payload.get("row") or [])
        except SeoulApiError:
            raise
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if wait is None:
                break
            time.sleep(wait)

    raise SeoulApiError(f"{start}~{end} 호출이 재시도 후에도 실패했다: {last_error}")


def fetch_all(
    api_key: str, *, page_size: int = 1000, max_pages: int = 10
) -> tuple[list[dict], SeoulApiError | None]:
    """받은 행과, 중간에 멈췄다면 그 원인을 함께 돌려준다.

    부분 성공도 적재할 수 있게 예외를 던지지 않는다. 실패를 알리는 일은 호출자 몫.
    """
    rows: list[dict] = []
    with requests.Session() as session:
        for page in range(max_pages):
            start = page * page_size + 1
            end = start + page_size - 1
            try:
                page_rows = fetch_page(api_key, start, end, session=session)
            except SeoulApiError as exc:
                return rows, exc

            rows.extend(page_rows)
            # list_total_count는 API마다 의미가 달라 신뢰하지 않는다.
            if len(page_rows) < page_size:
                return rows, None

    return rows, SeoulApiError(f"{max_pages}페이지를 넘겼다. 대여소가 예상보다 많다.")
