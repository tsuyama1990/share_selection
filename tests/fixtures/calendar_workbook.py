"""JPX earnings-calendar workbook builders shared by unit and e2e tests."""

import datetime
import io

import pandas as pd

TODAY = datetime.date(2026, 10, 14)


def workbook(rows: list[list]) -> bytes:
    titles = [
        ["９月に四半期末を迎えた決算発表予定会社の一覧"],
        ["List of companies"],
        ["2026年10月8日 現在"],
        ["As of 2026/10/8"],
    ]
    header = [
        "決算発表予定日",
        "コード",
        "会社名",
        "Issue Name",
        "決算期末",
        "業種名",
        "Industry",
        "種別",
        "Period",
        "市場",
        "Market",
    ]
    buf = io.BytesIO()
    pd.DataFrame([*titles, header, *rows]).to_excel(buf, header=False, index=False)
    return buf.getvalue()


def row(date, code, period="Second quarter", fye=datetime.datetime(2027, 3, 31)):
    return [date, code, "名", "Name", fye, "小売業", "Retail", "第２四半期", period, "プライム", "Prime"]
