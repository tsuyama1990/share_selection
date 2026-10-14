"""Builders for EDINET API test data (listing JSON, ZIP with the body CSV)."""

import io
import zipfile

CSV_PATH = "XBRL_TO_CSV/jpcrp030000-asr-001_E00000-000_2026-03-31_01_2026-06-25.csv"
CSV_HEADER = ["要素ID", "項目名", "コンテキストID", "相対年度", "連結・個別", "期間・時点", "ユニットID", "単位", "値"]


def csv_zip(values: dict[str, str], path: str = CSV_PATH) -> bytes:
    """ZIP holding a UTF-16 tab separated body CSV; ``values`` maps element id (with prefix) to its value."""
    rows = [CSV_HEADER] + [
        [element, "label", "CurrentYearInstant", "当期末", "連結", "時点", "", "", value]
        for element, value in values.items()
    ]
    text = "\n".join("\t".join(f'"{cell}"' for cell in row) for row in rows)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(path, text.encode("utf-16"))
    return buf.getvalue()


def listing_doc(doc_id: str, sec_code: str | None, doc_type: str = "120", period_end: str = "2026-03-31") -> dict:
    return {
        "docID": doc_id,
        "secCode": sec_code,
        "edinetCode": "E00001",
        "docTypeCode": doc_type,
        "periodEnd": period_end,
        "submitDateTime": "2026-06-25 09:00",
        "csvFlag": "1",
        "docDescription": "ignored",
    }


def listing(*docs: dict) -> dict:
    return {"metadata": {"status": "200"}, "results": list(docs)}
