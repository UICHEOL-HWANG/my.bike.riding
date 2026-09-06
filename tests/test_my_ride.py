from datetime import date

import pytest

from collector.my_ride import (
    MAX_PAGES,
    fetch_window,
    iter_windows,
    parse_rows,
)

HEADER = (
    "<tr><th>자전거</th><th>대여일시</th><th>대여소</th>"
    "<th>반납일시</th><th>반납대여소</th></tr>"
)


def row(seq="296568638", bike="SPB-60434", rented="2026-09-04 23:12",
        rent_st="1741. 제일강산수산입구", returned="2026-09-04 23:27",
        return_st="1674. 서울북부고용센터앞", dist="1.50"):
    return (
        f"<tr><td>{bike}</td>"
        f'<td><a href="#" id="{seq}">{rented}</a></td>'
        f"<td>{rent_st}</td><td>{returned}</td><td>{return_st}</td>"
        f'<td style="display:none">{seq}</td>'
        f'<td style="display:none">{dist}</td></tr>'
    )


def page(*rows_html):
    return f"<table>{HEADER}{''.join(rows_html)}</table>"


class FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


class FakeSession:
    """페이지별 HTML을 순서대로 돌려준다. 요청받은 파라미터도 기록한다."""

    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def post(self, url, data=None, headers=None, timeout=None):
        self.calls.append(data)
        idx = int(data["currentPageNo"]) - 1
        return FakeResponse(self.pages[idx] if idx < len(self.pages) else page())


def test_행을_필드로_뽑는다():
    (ride,) = parse_rows(page(row()))
    assert ride == {
        "rent_hist_seq": "296568638",
        "bike_no": "SPB-60434",
        "rented_at": "2026-09-04 23:12",
        "rent_station": "1741. 제일강산수산입구",
        "returned_at": "2026-09-04 23:27",
        "return_station": "1674. 서울북부고용센터앞",
        "distance_km": 1.5,
    }


def test_헤더행은_건너뛴다():
    assert parse_rows(page()) == []


def test_반납이_비면_None이다():
    # 대여 중이라 아직 반납 안 된 건이 이 형태로 온다.
    (ride,) = parse_rows(page(row(returned="", return_st="")))
    assert ride["returned_at"] is None
    assert ride["return_station"] is None


def test_거리가_숫자가_아니면_None이다():
    (ride,) = parse_rows(page(row(dist="-")))
    assert ride["distance_km"] is None


def test_칸이_모자란_행은_무시한다():
    # 숨은 칸 없이 5칸만 오는 안내 행("내역이 없습니다" 등)을 거른다.
    assert parse_rows("<table><tr><td>a</td><td>b</td></tr></table>") == []


def test_대여일시_형식이_아니면_무시한다():
    assert parse_rows(page(row(rented="내역이 없습니다"))) == []


@pytest.mark.parametrize(
    "start,end,expected",
    [
        (date(2026, 1, 1), date(2026, 1, 1), 1),
        (date(2025, 1, 1), date(2026, 9, 6), 4),
    ],
)
def test_창이_범위를_덮는다(start, end, expected):
    windows = list(iter_windows(start, end))
    assert len(windows) == expected
    assert windows[0][0] == start
    assert windows[-1][1] == end
    # 창끼리 겹치지도, 틈이 생기지도 않는다.
    for (_, prev_end), (next_start, _) in zip(windows, windows[1:]):
        assert (next_start - prev_end).days == 1


def test_창_길이를_넘지_않는다():
    for a, b in iter_windows(date(2020, 1, 1), date(2026, 9, 6), days=183):
        assert (b - a).days < 183


def test_페이지를_끝까지_받는다():
    session = FakeSession([page(row(seq="1")), page(row(seq="2")), page()])
    rides = fetch_window(session, date(2026, 1, 1), date(2026, 6, 30))
    assert {r["rent_hist_seq"] for r in rides} == {"1", "2"}


def test_같은_페이지가_반복되면_멈춘다():
    # 서버가 범위를 넘겨도 마지막 페이지를 계속 돌려주는 경우가 있다.
    # 페이징 마크업을 못 믿기 때문에 "새 seq가 없으면 멈춘다"로 끝낸다.
    session = FakeSession([page(row(seq="1"))] * 50)
    rides = fetch_window(session, date(2026, 1, 1), date(2026, 6, 30))
    assert len(rides) == 1
    assert len(session.calls) == 2


def test_페이지가_계속_새로우면_상한에서_멈춘다():
    session = FakeSession([page(row(seq=str(i))) for i in range(MAX_PAGES + 10)])
    fetch_window(session, date(2026, 1, 1), date(2026, 6, 30))
    assert len(session.calls) == MAX_PAGES


def test_조회_파라미터를_형식대로_보낸다():
    session = FakeSession([page()])
    fetch_window(session, date(2026, 1, 2), date(2026, 7, 3))
    assert session.calls[0]["searchStartDate"] == "2026-01-02"
    assert session.calls[0]["searchEndDate"] == "2026-07-03"
    assert session.calls[0]["currentPageNo"] == "1"
