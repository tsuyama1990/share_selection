"""U-docstore-1: Document is immutable. U-docstore-2: Company.mentioned_in."""

import dataclasses
import datetime

import pytest

from src.docstore import Company, Document


def test_document_is_frozen():
    doc = Document("edinet:S1:X", "1.T", "edinet", "S1:X", "X", datetime.datetime(2026, 1, 1), "text")
    with pytest.raises(dataclasses.FrozenInstanceError):
        doc.text = "other"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("company", "text", "expected"),
    [
        pytest.param(Company("6599.T", "エブレン"), "株式会社 エブ レン の決算", True, id="name-with-spaces"),
        pytest.param(Company("6599.T", "エブレン"), "ｴﾌﾞﾚﾝ", True, id="name-halfwidth"),
        pytest.param(Company("6599.T", "エブレン"), "証券コード６５９９", True, id="code-fullwidth"),
        pytest.param(Company("130A.T", "ベリタス"), "(130A)", True, id="alphanumeric-code"),
        pytest.param(Company("6599.T", "エブレン"), "荏原製作所 7013", False, id="other-company"),
    ],
)
def test_company_mentioned_in(company, text, expected):
    assert company.mentioned_in(text) is expected
