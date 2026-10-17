from src.verify import check_claims, normalize

DOCS = {"d1": "営業利益は ４６億円 増加した。\n値上げの効果。", "d2": "other"}


def claim(field="a", quote="営業利益は46億円", doc_id="d1"):
    return {"field": field, "claim": "c", "quote": quote, "doc_id": doc_id}


def test_normalize_unifies_width_and_drops_whitespace():
    assert normalize("４６ 億円\n増加　 ABC") == "46億円増加ABC"


def test_check_claims_keeps_verified_claims_and_ratio():
    answer = {"a": "x", "b": "y"}
    claims = [
        claim(),
        claim("b", "存在しない引用"),
        claim("b", "other", "d1"),
        claim("b", "", "d1"),
        claim("b", "x", "zz"),
    ]
    checked, verified = check_claims(answer, claims, DOCS)
    assert verified == [claims[0]]
    assert checked == {"a": "x", "b": "unknown"}


def test_check_claims_without_claims_leaves_everything_unknown():
    assert check_claims({"a": "x"}, [], DOCS) == ({"a": "unknown"}, [])


def test_check_claims_support_is_by_field_name():
    checked, verified = check_claims({"a": "x", "b": "y"}, [claim("b", "値上げの効果")], DOCS)
    assert checked == {"a": "unknown", "b": "y"}
    assert len(verified) == 1
