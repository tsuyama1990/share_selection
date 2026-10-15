import pytest

from src.webfetch import extract_text, web_doc_id
from tests.fixtures.web import html_page, pdf_bytes


def test_web_doc_id_ignores_case_of_scheme_and_host_and_fragment():
    a = web_doc_id("HTTPS://Example.COM/ir/a.html#top")
    assert a == web_doc_id("https://example.com/ir/a.html")
    assert a.startswith("web:") and len(a) == len("web:") + 16
    assert a != web_doc_id("https://example.com/ir/A.html")
    assert a != web_doc_id("https://example.com/ir/a.html?x=1")


def test_extract_text_html_title_and_body_without_script_and_navigation():
    body = html_page(
        " Results  2026 ",
        "<nav>menu</nav><header>head</header><script>var x = 1;</script>"
        "<noscript>no js</noscript><p>Profit  rose\n by 20%.</p><footer>foot</footer>",
    ).encode()
    assert extract_text(body, "text/html; charset=utf-8") == ("Results 2026", "Profit rose by 20%.")


def test_extract_text_decodes_shift_jis_declared_in_meta():
    page = html_page("決算短信", "<p>経常利益が増加</p>", meta='<meta charset="Shift_JIS">')
    assert extract_text(page.encode("shift_jis"), "text/html") == ("決算短信", "経常利益が増加")


def test_extract_text_uses_the_content_type_charset_first():
    page = html_page("決算", "<p>増益</p>").encode("euc_jp")
    assert extract_text(page, "text/html; charset=EUC-JP") == ("決算", "増益")


def test_extract_text_pdf_by_content_type_or_signature():
    pdf = pdf_bytes("Operating profit up")
    assert extract_text(pdf, "application/pdf")[1] == "Operating profit up"
    assert extract_text(pdf, "application/octet-stream")[1] == "Operating profit up"


def test_extract_text_rejects_other_types():
    with pytest.raises(ValueError, match="unsupported content type"):
        extract_text(b"{}", "application/json")
