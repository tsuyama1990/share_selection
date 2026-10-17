from src.review import ReviewSettings


def test_review_settings_from_config():
    cfg = {
        "review": {
            "max_tickers": 5,
            "min_verified_ratio": 0.6,
            "max_doc_chars": 100,
            "prompt_version": "v9",
            "tasks": {"T1": ["a"], "T2": ["b", "c"]},
            "context_metrics": ["PBR"],
        }
    }
    assert ReviewSettings.from_config(cfg) == ReviewSettings(
        5, 0.6, 100, "v9", {"T1": ["a"], "T2": ["b", "c"]}, ["PBR"]
    )
