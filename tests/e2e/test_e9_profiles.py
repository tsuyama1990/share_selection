"""E9: `profiles` stores every ticker's EDINET sections, records failures and skips stored reports on a rerun."""

import duckdb
import httpx

from tests.fixtures.config import CFG
from tests.fixtures.docs_flow import EDINET_HOST, KEY, SECTOR, all_handler

TICKERS = ["1.T", "2.T", "3.T", "4.T"]
FAILING = "S2"
CFG_PROFILES = {
    **CFG,
    "edinet": {**CFG["edinet"], "index_days": 1, "request_interval_s": 0, "sections": ["BusinessRisksTextBlock"]},
    "docstore": {"db_file": "profiles_test.duckdb"},
}


def write_tickers(root) -> None:
    rows = "".join(f"{t.removesuffix('.T')},会社{n},{SECTOR}\n" for n, t in enumerate(TICKERS, 1))
    (root / CFG["system"]["input_csv"]).write_text("code,name,sector33\n" + rows, encoding="utf-8")


def mock_http(monkeypatch, downloads: list[str]) -> None:
    def handler(request):
        if request.url.host == EDINET_HOST and "/documents/S" in request.url.path:
            downloads.append(request.url.path.rsplit("/", 1)[-1])
        return all_handler(request)

    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))


def test_profiles_stores_reports_and_retries_only_the_failure(project, monkeypatch, capsys):
    downloads: list[str] = []
    mock_http(monkeypatch, downloads)
    monkeypatch.setenv("EDINET_API_KEY", KEY)
    write_tickers(project.root)

    project.run("profiles", cfg=CFG_PROFILES)
    assert capsys.readouterr().out.endswith("3 reports stored, 1 failed.\n")
    with duckdb.connect(str(project.root / "profiles_test.duckdb")) as con:
        docs = con.execute("SELECT ticker, doc_id, text FROM documents ORDER BY doc_id").fetchall()
        errors = con.execute("SELECT ticker, source, ref, error FROM fetch_errors").fetchall()
    assert docs == [
        ("1.T", "edinet:S1:BusinessRisksTextBlock", "risk of S1"),
        ("3.T", "edinet:S3:BusinessRisksTextBlock", "risk of S3"),
        ("4.T", "edinet:S4:BusinessRisksTextBlock", "risk of S4"),
    ]
    assert errors == [("2.T", "edinet", FAILING, "RuntimeError HTTP 500")]

    downloads.clear()
    project.run("profiles", cfg=CFG_PROFILES)
    assert capsys.readouterr().out.endswith("3 reports stored, 1 failed.\n")
    assert downloads == [FAILING]
