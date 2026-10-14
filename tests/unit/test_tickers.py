import io
import unittest

import pandas as pd

from src.tickers import build_ticker_list


class TestTickers(unittest.TestCase):
    def test_keeps_domestic_common_stocks_only(self):
        src = pd.DataFrame(
            {
                "日付": ["20260930"] * 4,
                "コード": ["1301", "1306", "130A", "8951"],
                "銘柄名": ["極洋", "TOPIX ETF", "Veritas", "REIT"],
                "市場・商品区分": [
                    "プライム（内国株式）",
                    "ETF・ETN",
                    "グロース（内国株式）",
                    "REIT・ベンチャーファンド・カントリーファンド・インフラファンド",
                ],
                "33業種区分": ["水産・農林業", "-", "情報・通信業", "-"],
                "規模区分": ["TOPIX Small 1", "-", "-", "-"],
            }
        )
        buf = io.BytesIO()
        src.to_excel(buf, index=False)

        df = build_ticker_list(buf.getvalue(), ["プライム（内国株式）", "グロース（内国株式）"])
        self.assertEqual(df["code"].tolist(), ["1301", "130A"])
        self.assertEqual(df.columns.tolist(), ["code", "name", "market", "sector33", "size"])
