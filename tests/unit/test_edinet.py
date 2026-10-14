"""U-edinet-1..3: sec_code, parse_index, extract_sections."""

import datetime

from src.edinet import extract_sections, parse_index, sec_code
from tests.fixtures.edinet import csv_zip, listing, listing_doc


def test_sec_code_appends_zero_and_drops_suffix():
    assert sec_code("6599.T") == "65990"
    assert sec_code("130A.T") == "130A0"
    assert sec_code("6599") == "65990"


def test_parse_index_keeps_needed_columns_and_drops_docs_without_sec_code():
    day = datetime.date(2026, 6, 25)
    rows = parse_index(listing(listing_doc("S1", "65990"), listing_doc("S2", None)), day)
    assert rows == [
        {
            "doc_id": "S1",
            "sec_code": "65990",
            "edinet_code": "E00001",
            "doc_type_code": "120",
            "period_end": "2026-03-31",
            "submit_date": day,
        }
    ]
    assert parse_index({"metadata": {}}, day) == []


def test_extract_sections_picks_listed_elements_and_strips_tags():
    zip_bytes = csv_zip(
        {
            "jpcrp_cor:BusinessRisksTextBlock": "<p>Risk &amp; <b>more</b></p><p>text</p>",
            "jpcrp_cor:Other": "skip",
            "jpcrp_cor:DescriptionOfBusinessTextBlock": "事業 の 内容",
        }
    )
    assert extract_sections(zip_bytes, ["BusinessRisksTextBlock", "DescriptionOfBusinessTextBlock"]) == {
        "BusinessRisksTextBlock": "Risk & more text",
        "DescriptionOfBusinessTextBlock": "事業 の 内容",
    }


def test_extract_sections_without_the_elements_is_empty():
    assert extract_sections(csv_zip({"jpcrp_cor:Other": "x"}), ["BusinessRisksTextBlock"]) == {}
    assert extract_sections(csv_zip({"jpcrp_cor:Other": "x"}, path="other/file.csv"), ["Other"]) == {}
