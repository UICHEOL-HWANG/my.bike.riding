import pytest
import responses

from collector.api import SeoulApiError, fetch_all, fetch_page

KEY = "testkey"


def url(start, end):
    return f"http://openapi.seoul.go.kr:8088/{KEY}/json/bikeList/{start}/{end}/"


def body(rows, code="INFO-000"):
    return {
        "rentBikeStatus": {
            "RESULT": {"CODE": code, "MESSAGE": "메시지"},
            "row": rows,
        }
    }


def make_rows(n, offset=0):
    return [{"stationId": f"ST-{i + offset}"} for i in range(n)]


@responses.activate
def test_한_페이지를_받는다():
    responses.add(responses.GET, url(1, 1000), json=body(make_rows(3)), status=200)

    assert len(fetch_page(KEY, 1, 1000)) == 3


@responses.activate
def test_HTTP_200이어도_에러코드면_실패로_본다():
    responses.add(
        responses.GET, url(1, 1000), json=body([], code="INFO-100"), status=200
    )

    with pytest.raises(SeoulApiError, match="INFO-100"):
        fetch_page(KEY, 1, 1000)


@responses.activate
def test_페이지가_가득_차지_않으면_거기서_멈춘다():
    responses.add(responses.GET, url(1, 1000), json=body(make_rows(1000)), status=200)
    responses.add(
        responses.GET, url(1001, 2000), json=body(make_rows(1000, 1000)), status=200
    )
    responses.add(
        responses.GET, url(2001, 3000), json=body(make_rows(847, 2000)), status=200
    )

    rows, error = fetch_all(KEY)

    assert len(rows) == 2847
    assert error is None
    assert len(responses.calls) == 3


@responses.activate
def test_대여소_수가_정확히_페이지_경계면_INFO_200을_빈_페이지로_본다():
    responses.add(responses.GET, url(1, 1000), json=body(make_rows(1000)), status=200)
    responses.add(
        responses.GET, url(1001, 2000), json=body([], code="INFO-200"), status=200
    )

    rows, error = fetch_all(KEY)

    assert len(rows) == 1000
    assert error is None


@responses.activate
def test_중간에_실패해도_받은_만큼은_돌려준다():
    responses.add(responses.GET, url(1, 1000), json=body(make_rows(1000)), status=200)
    responses.add(
        responses.GET, url(1001, 2000), json=body([], code="ERROR-500"), status=200
    )

    rows, error = fetch_all(KEY)

    assert len(rows) == 1000
    assert isinstance(error, SeoulApiError)


@responses.activate
def test_일시적_오류는_재시도한다():
    responses.add(responses.GET, url(1, 1000), status=500)
    responses.add(responses.GET, url(1, 1000), json=body(make_rows(2)), status=200)

    assert len(fetch_page(KEY, 1, 1000)) == 2


@responses.activate
def test_재시도마다_한_줄을_stderr에_알린다(monkeypatch, capsys):
    monkeypatch.setattr("collector.api.time.sleep", lambda _seconds: None)
    responses.add(responses.GET, url(1, 1000), status=500)
    responses.add(responses.GET, url(1, 1000), status=500)
    responses.add(responses.GET, url(1, 1000), json=body(make_rows(1)), status=200)

    fetch_page(KEY, 1, 1000)

    err_lines = [line for line in capsys.readouterr().err.splitlines() if line]
    assert len(err_lines) == 2, "실패한 시도 2번마다 한 줄씩 알려야 한다"


@responses.activate
def test_재시도가_모두_실패해도_키가_메시지에_남지_않는다(monkeypatch):
    monkeypatch.setattr("collector.api.time.sleep", lambda _seconds: None)
    for _ in range(4):
        responses.add(responses.GET, url(1, 1000), status=500)

    with pytest.raises(SeoulApiError) as exc_info:
        fetch_page(KEY, 1, 1000)

    assert KEY not in str(exc_info.value)


@responses.activate
def test_XML_에러_본문도_판독한다():
    responses.add(
        responses.GET,
        url(1, 1000),
        body="<RESULT><CODE>INFO-100</CODE><MESSAGE>인증키가 유효하지 않습니다</MESSAGE></RESULT>",
        status=200,
        content_type="application/xml",
    )

    with pytest.raises(SeoulApiError, match="INFO-100"):
        fetch_page(KEY, 1, 1000)

    assert len(responses.calls) == 1, "인증키 오류는 재시도하지 않는다"


@responses.activate
def test_빈_본문은_XML_에러로_보지_않고_재시도한다(monkeypatch):
    monkeypatch.setattr("collector.api.time.sleep", lambda _seconds: None)
    responses.add(responses.GET, url(1, 1000), body="", status=200, content_type="text/plain")
    responses.add(responses.GET, url(1, 1000), json=body(make_rows(1)), status=200)

    assert len(fetch_page(KEY, 1, 1000)) == 1


@responses.activate
def test_CODE_닫는_태그가_없는_XML도_재시도한다(monkeypatch):
    monkeypatch.setattr("collector.api.time.sleep", lambda _seconds: None)
    responses.add(
        responses.GET,
        url(1, 1000),
        body="<RESULT><CODE>INFO-100",
        status=200,
        content_type="application/xml",
    )
    responses.add(responses.GET, url(1, 1000), json=body(make_rows(1)), status=200)

    assert len(fetch_page(KEY, 1, 1000)) == 1


@responses.activate
def test_최상위가_객체가_아닌_JSON도_SeoulApiError로_바꾼다():
    responses.add(responses.GET, url(1, 1000), json=["예상 못 한 배열"], status=200)

    with pytest.raises(SeoulApiError):
        fetch_page(KEY, 1, 1000)


@responses.activate
def test_rentBikeStatus가_객체가_아니어도_SeoulApiError로_바꾼다():
    responses.add(responses.GET, url(1, 1000), json={"rentBikeStatus": "에러"}, status=200)

    with pytest.raises(SeoulApiError):
        fetch_page(KEY, 1, 1000)


@responses.activate
def test_row가_단일_객체로_와도_한_건으로_본다():
    responses.add(
        responses.GET, url(1, 1000), json=body({"stationId": "ST-4"}), status=200
    )

    rows = fetch_page(KEY, 1, 1000)

    assert rows == [{"stationId": "ST-4"}]


@responses.activate
def test_fetch_all은_어떤_경우에도_예외를_던지지_않는다():
    responses.add(responses.GET, url(1, 1000), json="문자열 본문", status=200)

    rows, error = fetch_all(KEY)

    assert rows == []
    assert isinstance(error, SeoulApiError)
