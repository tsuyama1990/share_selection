import io
from unittest import mock

import httpx
import pandas as pd
import pytest

from src.tickers import read_column, read_tickers, update_ticker_csv


def test_read_tickers_appends_suffix_and_keeps_alphanumeric_codes(tmp_path):
    csv = tmp_path / "t.csv"
    csv.write_text("code,name\n1301 ,A\n130A,B\n", encoding="utf-8")
    assert read_tickers(csv) == ["1301.T", "130A.T"]


def test_read_column_maps_tickers_to_the_column(tmp_path):
    csv = tmp_path / "t.csv"
    csv.write_text("code,name,sector33\n1301 ,極洋,水産・農林業\n130A,ベリタス,情報・通信業\n", encoding="utf-8")
    assert read_column(csv, "name") == {"1301.T": "極洋", "130A.T": "ベリタス"}
    assert read_column(csv, "sector33") == {"1301.T": "水産・農林業", "130A.T": "情報・通信業"}


def _workbook() -> bytes:
    buf = io.BytesIO()
    pd.DataFrame(
        {"コード": ["1301"], "銘柄名": ["極洋"], "市場・商品区分": ["M"], "33業種区分": ["S"], "規模区分": ["L"]}
    ).to_excel(buf, index=False)
    return buf.getvalue()


def _response(status: int, content: bytes = b"") -> httpx.Response:
    return httpx.Response(status, content=content, request=httpx.Request("GET", "https://jpx.test/x.xlsx"))


def test_update_downloads_and_writes_csv(tmp_path):
    out = tmp_path / "t.csv"
    with mock.patch("src.tickers.httpx.get", return_value=_response(200, _workbook())) as get:
        assert update_ticker_csv(out, "https://jpx.test/x.xlsx", ["M"], 5) == 1
    assert get.call_args.kwargs == {"timeout": 5, "follow_redirects": True}
    assert pd.read_csv(out, dtype=str)["code"].tolist() == ["1301"]


def test_update_raises_on_error_status(tmp_path):
    with (
        mock.patch("src.tickers.httpx.get", return_value=_response(503)),
        pytest.raises(httpx.HTTPStatusError),
    ):
        update_ticker_csv(tmp_path / "t.csv", "https://jpx.test/x.xlsx", ["M"], 5)
    assert not (tmp_path / "t.csv").exists()
