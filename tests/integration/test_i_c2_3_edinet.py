"""Placeholder for I-C2-3 (EDINET 索引 → 最新の有価証券報告書 → 節の抽出 → 文書ストア) (no network)."""

import importlib

import pytest

PLANNED = "src.edinet"
FUNCTION = "update_index"


def planned():
    return getattr(importlib.import_module(PLANNED), FUNCTION)


@pytest.mark.xfail(strict=True, reason="I-C2-3 not implemented")
def test_index_diff_update():
    """索引の差分更新"""
    planned()
    raise AssertionError("I-C2-3: index_diff_update not implemented")


@pytest.mark.xfail(strict=True, reason="I-C2-3 not implemented")
def test_latest_annual_report():
    """120 の最新の選択"""
    planned()
    raise AssertionError("I-C2-3: latest_annual_report not implemented")


@pytest.mark.xfail(strict=True, reason="I-C2-3 not implemented")
def test_extract_sections():
    """ZIP の本文 CSV から指定節だけ保存"""
    planned()
    raise AssertionError("I-C2-3: extract_sections not implemented")


@pytest.mark.xfail(strict=True, reason="I-C2-3 not implemented")
def test_no_refetch_same_doc_id():
    """同じ docID は取り直さない"""
    planned()
    raise AssertionError("I-C2-3: no_refetch_same_doc_id not implemented")


@pytest.mark.xfail(strict=True, reason="I-C2-3 not implemented")
def test_failure_recorded():
    """失敗の記録"""
    planned()
    raise AssertionError("I-C2-3: failure_recorded not implemented")
