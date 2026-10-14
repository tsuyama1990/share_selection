"""Placeholder for I-C2-4 (Web 取得 → 文書ストア) (no network)."""

import importlib

import pytest

PLANNED = "src.webfetch"
FUNCTION = "fetch_document"


def planned():
    return getattr(importlib.import_module(PLANNED), FUNCTION)


@pytest.mark.xfail(strict=True, reason="I-C2-4 not implemented")
def test_follows_redirects():
    """リダイレクト追従"""
    planned()
    raise AssertionError("I-C2-4: follows_redirects not implemented")


@pytest.mark.xfail(strict=True, reason="I-C2-4 not implemented")
def test_extracts_html_and_pdf():
    """HTML・PDF の本文抽出"""
    planned()
    raise AssertionError("I-C2-4: extracts_html_and_pdf not implemented")


@pytest.mark.xfail(strict=True, reason="I-C2-4 not implemented")
def test_size_limit():
    """サイズ上限"""
    planned()
    raise AssertionError("I-C2-4: size_limit not implemented")


@pytest.mark.xfail(strict=True, reason="I-C2-4 not implemented")
def test_failure_recorded():
    """失敗の記録"""
    planned()
    raise AssertionError("I-C2-4: failure_recorded not implemented")
