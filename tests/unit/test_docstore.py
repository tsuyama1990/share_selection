"""U-docstore-1: Document is immutable."""

import dataclasses
import datetime

import pytest

from src.docstore import Document


def test_document_is_frozen():
    doc = Document("edinet:S1:X", "1.T", "edinet", "S1:X", "X", datetime.datetime(2026, 1, 1), "text")
    with pytest.raises(dataclasses.FrozenInstanceError):
        doc.text = "other"  # type: ignore[misc]
