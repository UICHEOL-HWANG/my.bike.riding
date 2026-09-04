import re
import sys
import time

import requests

BASE = "http://openapi.seoul.go.kr:8088"
OK_CODE = "INFO-000"
# 요청한 범위에 대여소가 없다는 뜻이다. 실패가 아니라 빈 페이지로 본다 —
# 대여소 수가 정확히 page_size의 배수일 때 마지막 페이지가 이 코드로 온다.
NO_DATA_CODE = "INFO-200"
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
            if not isinstance(data, dict):
                raise SeoulApiError(f"응답 본문이 객체가 아니다: {data!r}")
            payload = data.get("rentBikeStatus")
            if not isinstance(payload, dict):
                raise SeoulApiError(f"rentBikeStatus가 객체가 아니다: {payload!r}")
            code = (payload.get("RESULT") or {}).get("CODE")
            if code == NO_DATA_CODE:
                return []
            if code != OK_CODE:
                message = (payload.get("RESULT") or {}).get("MESSAGE", "")
                # 인증키 오류·쿼터 초과는 재시도해도 낫지 않으므로 즉시 올린다.
                raise SeoulApiError(f"API가 {code}를 반환했다: {message}")
            row = payload.get("row")
            if isinstance(row, dict):
                # 일부 서울시 API 응답은 원소가 하나면 배열 대신 객체 하나로
                # 온다. list(dict)는 그 dict의 키 목록을 돌려주는 함정이라
                # 명시적으로 감싼다.
                return [row]
            if isinstance(row, list):
                return row
            return []
        except SeoulApiError:
            raise
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if wait is None:
                break
            # 재시도를 조용히 하면 서서히 나빠지는 API가 건강한 API와 똑같이
            # 보인다. 예외 타입 이름만 남긴다 — url에는 인증키가 들어있다.
            print(
                f"{start}~{end} 호출 실패({type(exc).__name__}), {wait}초 후 재시도",
                file=sys.stderr,
            )
            time.sleep(wait)

    # url에는 인증키가 들어있다. last_error를 그대로 문자열로 박으면
    # requests의 예외 메시지(예: raise_for_status)에 딸려온 요청 url이
    # 이 메시지를 거쳐 stderr, 나아가 공개 저장소의 Actions 로그까지 간다.
    # 예외 타입 이름만 남기고 원본 예외는 버린다.
    error_kind = type(last_error).__name__ if last_error is not None else "알 수 없음"
    raise SeoulApiError(f"{start}~{end} 호출이 재시도 후에도 실패했다: {error_kind}")


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
