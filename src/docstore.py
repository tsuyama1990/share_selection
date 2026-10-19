"""Documents fetched for stage 2 research, the EDINET filing index and fetch errors (a DuckDB file)."""

import datetime
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

from .tickers import TICKER_SUFFIX
from .verify import normalize

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS documents (
        doc_id TEXT PRIMARY KEY, ticker TEXT, source TEXT, source_ref TEXT, title TEXT, fetched_at TIMESTAMP,
        text TEXT, text_sha256 TEXT)""",
    """CREATE TABLE IF NOT EXISTS edinet_index (
        doc_id TEXT PRIMARY KEY, sec_code TEXT, edinet_code TEXT, doc_type_code TEXT, period_end DATE,
        submit_date DATE)""",
    """CREATE TABLE IF NOT EXISTS fetch_errors (ticker TEXT, source TEXT, ref TEXT, error TEXT, "at" TIMESTAMP)""",
)


@dataclass(frozen=True)
class Company:
    ticker: str
    name: str  # Japanese name

    def mentioned_in(self, text: str) -> bool:
        """Whether the normalized text holds the normalized name or the code of the ticker."""
        normalized = normalize(text)
        return normalize(self.name) in normalized or normalize(self.ticker.removesuffix(TICKER_SUFFIX)) in normalized


@dataclass(frozen=True)
class Document:
    doc_id: str
    ticker: str
    source: str  # "edinet" | "web"
    source_ref: str
    title: str
    fetched_at: datetime.datetime
    text: str


class DocumentRewriteError(RuntimeError):
    """A different text was offered for a stored doc_id (citations are checked against the stored text)."""


class DocStore:
    def __init__(self, db_path: Path):
        self.con = duckdb.connect(str(db_path))
        for ddl in SCHEMA:
            self.con.execute(ddl)

    @classmethod
    def from_config(cls, cfg: dict[str, Any], root: Path) -> "DocStore":
        return cls(root / cfg["docstore"]["db_file"])

    def __enter__(self) -> "DocStore":
        return self

    def __exit__(self, *_exc) -> None:
        self.con.close()

    def put(self, doc: Document) -> None:
        sha = hashlib.sha256(doc.text.encode()).hexdigest()
        row = self.con.execute("SELECT text_sha256 FROM documents WHERE doc_id = ?", [doc.doc_id]).fetchone()
        if row is None:
            self.con.execute(
                "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [doc.doc_id, doc.ticker, doc.source, doc.source_ref, doc.title, doc.fetched_at, doc.text, sha],
            )
        elif row[0] != sha:
            raise DocumentRewriteError(doc.doc_id)

    def has(self, doc_id: str) -> bool:
        return self.con.execute("SELECT 1 FROM documents WHERE doc_id = ?", [doc_id]).fetchone() is not None

    def has_source(self, ticker: str, source: str) -> bool:
        sql = "SELECT 1 FROM documents WHERE ticker = ? AND source = ? LIMIT 1"
        return self.con.execute(sql, [ticker, source]).fetchone() is not None

    def documents(self, ticker: str) -> list[Document]:
        sql = (
            "SELECT doc_id, ticker, source, source_ref, title, fetched_at, text"
            " FROM documents WHERE ticker = ? ORDER BY doc_id"
        )
        return [Document(*row) for row in self.con.execute(sql, [ticker]).fetchall()]

    def profiles(self, sections: tuple[str, ...]) -> dict[str, str]:
        """Ticker -> text of its EDINET documents of ``sections`` (the doc_id's last part), joined by a newline."""
        sql = "SELECT ticker, doc_id, text FROM documents WHERE source = ? ORDER BY ticker, doc_id"
        texts: dict[str, list[str]] = {}
        for ticker, doc_id, text in self.con.execute(sql, ["edinet"]).fetchall():
            if doc_id.rsplit(":", 1)[-1] in sections:
                texts.setdefault(ticker, []).append(text)
        return {ticker: "\n".join(parts) for ticker, parts in texts.items()}

    def record_error(self, ticker: str, source: str, ref: str, error: str) -> None:
        self.con.execute(
            "INSERT INTO fetch_errors VALUES (?, ?, ?, ?, ?)", [ticker, source, ref, error, datetime.datetime.now()]
        )

    def add_index(self, rows: list[dict[str, Any]]) -> None:
        """Insert filings (keys: the ``edinet_index`` columns); a doc_id already indexed is ignored."""
        if not rows:
            return
        self.con.executemany(
            "INSERT OR IGNORE INTO edinet_index VALUES (?, ?, ?, ?, ?, ?)",
            [
                [r["doc_id"], r["sec_code"], r["edinet_code"], r["doc_type_code"], r["period_end"], r["submit_date"]]
                for r in rows
            ],
        )

    def index_last_date(self) -> datetime.date | None:
        return self.con.execute("SELECT max(submit_date) FROM edinet_index").fetchall()[0][0]

    def latest_annual_report(self, sec_code: str, doc_type_code: str) -> str | None:
        sql = (
            "SELECT doc_id FROM edinet_index WHERE sec_code = ? AND doc_type_code = ?"
            " ORDER BY period_end DESC NULLS LAST, submit_date DESC LIMIT 1"
        )
        row = self.con.execute(sql, [sec_code, doc_type_code]).fetchone()
        return None if row is None else row[0]
