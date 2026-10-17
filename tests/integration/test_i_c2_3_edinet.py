"""I-C2-3: EDINET index -> latest annual report -> sections -> document store (L2 C2 section 7); HTTP is mocked."""

import datetime

import httpx
import pytest

from src.docstore import DocStore
from src.edinet import EdinetClient, fetch_annual_report, update_index
from src.throttle import RateLimiter
from tests.fixtures.edinet import csv_zip, listing, listing_doc

KEY = "SECRET-KEY"
TODAY = datetime.date(2026, 6, 27)
SECTIONS = ["BusinessRisksTextBlock", "DescriptionOfBusinessTextBlock"]
BODY = csv_zip(
    {
        "jpcrp_cor:BusinessRisksTextBlock": "<p>risk</p>",
        "jpcrp_cor:DescriptionOfBusinessTextBlock": "business",
        "jpcrp_cor:NotListed": "skip",
    }
)


class Server:
    """Mock EDINET: ``days`` maps date text to listing, ``zips`` docID to a status or ZIP bytes; records requests."""

    def __init__(self, days: dict[str, dict], zips: dict[str, int | bytes]):
        self.days, self.zips, self.requests = days, zips, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.url.params["Subscription-Key"] == KEY
        if request.url.path.endswith("documents.json"):
            day = request.url.params["date"]
            if day not in self.days:
                return httpx.Response(500)
            return httpx.Response(200, json=self.days[day])
        outcome = self.zips[request.url.path.rsplit("/", 1)[-1]]
        return httpx.Response(outcome) if isinstance(outcome, int) else httpx.Response(200, content=outcome)

    def listing_days(self) -> list[str]:
        return [r.url.params["date"] for r in self.requests if r.url.path.endswith("documents.json")]

    def downloads(self) -> list[str]:
        return [r.url.path for r in self.requests if "documents/" in r.url.path]


def make_client(server: Server) -> EdinetClient:
    http = httpx.Client(transport=httpx.MockTransport(server))
    return EdinetClient("https://edinet.test/api/v2", KEY, http, RateLimiter(1, 0))


@pytest.fixture
def store(tmp_path):
    with DocStore(tmp_path / "documents.duckdb") as s:
        yield s


def test_index_scans_the_window_then_only_new_days(store):
    days = {f"2026-06-{d}": listing() for d in (24, 26, 27)}
    server = Server(days | {"2026-06-25": listing(listing_doc("S1", "65990"), listing_doc("X", None))}, {})
    client = make_client(server)

    assert update_index(client, store, TODAY, index_days=3) == 4
    assert server.listing_days() == ["2026-06-24", "2026-06-25", "2026-06-26", "2026-06-27"]
    assert store.con.execute("SELECT doc_id, sec_code FROM edinet_index").fetchall() == [("S1", "65990")]

    server.requests.clear()
    server.days["2026-06-28"] = listing(listing_doc("S2", "13A00"))
    assert update_index(client, store, TODAY + datetime.timedelta(days=1), index_days=3) == 3
    assert server.listing_days() == ["2026-06-26", "2026-06-27", "2026-06-28"]
    assert store.index_last_date() == datetime.date(2026, 6, 28)


def test_index_failure_is_recorded_without_the_key_and_stops_the_scan(store):
    server = Server({"2026-06-26": listing(listing_doc("S1", "65990"))}, {})
    assert update_index(make_client(server), store, TODAY, index_days=2) == 0
    assert store.con.execute("SELECT ticker, source, ref, error FROM fetch_errors").fetchall() == [
        ("", "edinet", "2026-06-25", "HTTP 500")
    ]


def test_latest_120_report_is_chosen_and_only_listed_sections_are_stored(store):
    server = Server(
        {
            "2026-06-26": listing(
                listing_doc("OLD", "65990", period_end="2025-03-31"),
                listing_doc("NEW", "65990", period_end="2026-03-31"),
                listing_doc("QUARTER", "65990", doc_type="140", period_end="2026-06-30"),
            )
        },
        {"NEW": BODY},
    )
    client = make_client(server)
    update_index(client, store, datetime.date(2026, 6, 26), index_days=0)

    ids = fetch_annual_report(client, store, "6599.T", "120", SECTIONS)

    assert ids == ["edinet:NEW:BusinessRisksTextBlock", "edinet:NEW:DescriptionOfBusinessTextBlock"]
    assert server.downloads() == ["/api/v2/documents/NEW"]
    assert store.con.execute(
        "SELECT doc_id, ticker, source, source_ref, text FROM documents ORDER BY doc_id"
    ).fetchall() == [
        ("edinet:NEW:BusinessRisksTextBlock", "6599.T", "edinet", "NEW:BusinessRisksTextBlock", "risk"),
        (
            "edinet:NEW:DescriptionOfBusinessTextBlock",
            "6599.T",
            "edinet",
            "NEW:DescriptionOfBusinessTextBlock",
            "business",
        ),
    ]


def test_same_doc_id_is_not_fetched_again(store):
    server = Server({"2026-06-26": listing(listing_doc("NEW", "65990"))}, {"NEW": BODY})
    client = make_client(server)
    update_index(client, store, datetime.date(2026, 6, 26), index_days=0)

    first = fetch_annual_report(client, store, "6599.T", "120", SECTIONS)
    second = fetch_annual_report(client, store, "6599.T", "120", SECTIONS)

    assert first == second
    assert len(server.downloads()) == 1


def test_a_stored_report_missing_a_configured_section_is_downloaded_again_for_that_section_only(store):
    server = Server({"2026-06-26": listing(listing_doc("NEW", "65990"))}, {"NEW": BODY})
    client = make_client(server)
    update_index(client, store, datetime.date(2026, 6, 26), index_days=0)
    fetch_annual_report(client, store, "6599.T", "120", SECTIONS[:1])

    ids = fetch_annual_report(client, store, "6599.T", "120", SECTIONS)

    assert ids == [f"edinet:NEW:{e}" for e in SECTIONS]
    assert len(server.downloads()) == 2
    assert store.con.execute("SELECT count(*) FROM documents").fetchall() == [(2,)]


@pytest.mark.parametrize(
    ("outcome", "error"),
    [
        pytest.param(500, "RuntimeError HTTP 500", id="http"),
        pytest.param(b"not a zip", "BadZipFile File is not a zip file", id="bad-zip"),
        pytest.param(csv_zip({"jpcrp_cor:Other": "x"}), "no listed section", id="no-section"),
    ],
)
def test_failures_are_recorded_without_the_key(store, outcome, error):
    server = Server({"2026-06-26": listing(listing_doc("S1", "65990"))}, {"S1": outcome})
    client = make_client(server)
    update_index(client, store, datetime.date(2026, 6, 26), index_days=0)

    assert fetch_annual_report(client, store, "6599.T", "120", SECTIONS) == []
    assert store.con.execute("SELECT ticker, ref, error FROM fetch_errors").fetchall() == [("6599.T", "S1", error)]
    assert KEY not in repr(store.con.execute("SELECT * FROM fetch_errors").fetchall())


def test_ticker_missing_from_the_index_is_recorded(store):
    client = make_client(Server({}, {}))
    assert fetch_annual_report(client, store, "9999.T", "120", SECTIONS) == []
    assert store.con.execute("SELECT ticker, error FROM fetch_errors").fetchall() == [("9999.T", "not in index")]


def test_transport_error_is_reported_by_class_name_only(store):
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url}")

    client = EdinetClient(
        "https://edinet.test/api/v2", KEY, httpx.Client(transport=httpx.MockTransport(boom)), RateLimiter(1, 0)
    )
    assert update_index(client, store, TODAY, index_days=0) == 0
    assert store.con.execute("SELECT error FROM fetch_errors").fetchall() == [("ConnectError",)]
