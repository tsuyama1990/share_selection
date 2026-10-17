"""Quote checking: a claim counts only when its quote is in the text of the document it names."""

import unicodedata
from typing import Any

from . import fields as F


def normalize(text: str) -> str:
    """NFKC with every whitespace character removed."""
    return "".join(unicodedata.normalize("NFKC", text).split())


def check_claims(
    answer: dict[str, Any], claims: list[dict[str, str]], docs: dict[str, str]
) -> tuple[dict[str, Any], list[dict[str, str]], float]:
    """Verified claims, their share of all claims, and ``answer`` with unsupported items set to unknown.

    An item stays only when a verified claim names it in ``field``. ``docs`` maps doc_id to the text the model saw.
    """
    normalized = {doc_id: normalize(text) for doc_id, text in docs.items()}
    verified = [
        c
        for c in claims
        if (quote := normalize(c["quote"])) and c["doc_id"] in normalized and quote in normalized[c["doc_id"]]
    ]
    supported = {c["field"] for c in verified}
    checked = {item: value if item in supported else F.UNKNOWN for item, value in answer.items()}
    return checked, verified, len(verified) / len(claims) if claims else 0.0
