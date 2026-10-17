from src.review import ReviewSettings


def test_review_settings_from_config():
    cfg = {
        "review": {
            "max_tickers": 5,
            "min_verified_ratio": 0.6,
            "max_doc_chars": 100,
            "tasks": {"T1": ["a"], "T2": ["b", "c"]},
            "context_metrics": ["PBR"],
            "sources": ["edinet"],
        },
        "memo": {"filename": "{run_id}_{ticker}.md"},
    }
    assert ReviewSettings.from_config(cfg) == ReviewSettings(
        5, 0.6, 100, {"T1": ["a"], "T2": ["b", "c"]}, ["PBR"], ["edinet"], "{run_id}_{ticker}.md"
    )
