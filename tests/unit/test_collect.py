from src.collect import CollectSettings


def test_collect_settings_from_config():
    cfg = {
        "edinet": {"index_days": 7, "doc_type_code": "120", "sections": ["A", "B"]},
        "webfetch": {"max_bytes": 100},
        "docs": {"search_prompt": "{name} {code}", "max_sources": 3},
    }
    assert CollectSettings.from_config(cfg) == CollectSettings(7, "120", ["A", "B"], "{name} {code}", 3, 100)
