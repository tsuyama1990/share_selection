"""I-C2-5: document store round trip and the no-rewrite rule (docs/architecture/L2_C2_data_acquisition.md section 7)."""

import datetime
import hashlib

import pytest

from src.docstore import DocStore, Document, DocumentRewriteError

NOW = datetime.datetime(2026, 10, 15, 9, 0)


def doc(text: str = "body") -> Document:
    return Document("edinet:S1:X", "1.T", "edinet", "S1:X", "X", NOW, text)


@pytest.fixture
def store(tmp_path):
    with DocStore(tmp_path / "documents.duckdb") as s:
        yield s


def test_put_then_has_and_survives_reopen(tmp_path):
    path = tmp_path / "documents.duckdb"
    with DocStore(path) as s:
        assert not s.has("edinet:S1:X")
        s.put(doc())
    with DocStore(path) as s:
        assert s.has("edinet:S1:X")
        assert s.con.execute("SELECT ticker, text, text_sha256 FROM documents").fetchall() == [
            ("1.T", "body", hashlib.sha256(b"body").hexdigest())
        ]


def test_same_text_is_a_no_op_and_other_text_is_refused(store):
    store.put(doc())
    store.put(doc())
    with pytest.raises(DocumentRewriteError):
        store.put(doc("changed"))
    assert store.con.execute("SELECT count(*), min(text) FROM documents").fetchone() == (1, "body")


def test_index_ignores_known_doc_ids_and_picks_latest_report(store):
    def row(doc_id, period_end, submit, doc_type="120"):
        return {
            "doc_id": doc_id,
            "sec_code": "65990",
            "edinet_code": "E1",
            "doc_type_code": doc_type,
            "period_end": period_end,
            "submit_date": submit,
        }

    assert store.index_last_date() is None
    store.add_index(
        [row("OLD", "2025-03-31", datetime.date(2025, 6, 25)), row("Q", "2026-06-30", datetime.date(2026, 8, 1), "140")]
    )
    store.add_index(
        [row("NEW", "2026-03-31", datetime.date(2026, 6, 25)), row("OLD", "2025-03-31", datetime.date(2030, 1, 1))]
    )
    assert store.index_last_date() == datetime.date(2026, 8, 1)
    assert store.latest_annual_report("65990", "120") == "NEW"
    assert store.latest_annual_report("65990", "999") is None
    assert store.latest_annual_report("11110", "120") is None


def test_record_error_keeps_the_given_fields(store):
    store.record_error("1.T", "edinet", "S1", "HTTP 500")
    assert store.con.execute("SELECT ticker, source, ref, error FROM fetch_errors").fetchall() == [
        ("1.T", "edinet", "S1", "HTTP 500")
    ]
