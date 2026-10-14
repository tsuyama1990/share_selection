"""Placeholder for I-C2-5 (文書ストア) (no network)."""

import importlib

import pytest

PLANNED = "src.docstore"
FUNCTION = "DocStore"


def planned():
    return getattr(importlib.import_module(PLANNED), FUNCTION)


@pytest.mark.xfail(strict=True, reason="I-C2-5 not implemented")
def test_save_and_get():
    """保存・取得"""
    planned()
    raise AssertionError("I-C2-5: save_and_get not implemented")


@pytest.mark.xfail(strict=True, reason="I-C2-5 not implemented")
def test_rejects_overwrite():
    """本文を書き換えない（同じ doc_id への上書きを拒否）"""
    planned()
    raise AssertionError("I-C2-5: rejects_overwrite not implemented")
