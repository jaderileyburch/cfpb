"""Tests for the keyword/regex classification engine."""
from patternproof.classify import compile_taxonomy, classify_text


TAXONOMY = {
    "repossession": {
        "description": "Repo events",
        "keywords": ["repossessed", "took my car"],
    },
    "notice_failure": {
        "description": "No notice",
        "keywords": ["no notice", "without warning"],
        "min_matches": 1,
    },
    "strong_signal": {
        "description": "Requires two distinct hits",
        "keywords": ["deficiency", "charge-off", "credit report"],
        "min_matches": 2,
    },
    "regex_cat": {
        "description": "Regex matching",
        "regex": [r"\brepo(ssession)?\b"],
    },
}


def test_keyword_match_is_case_insensitive():
    compiled = compile_taxonomy(TAXONOMY)
    res = classify_text("They REPOSSESSED my vehicle.", compiled)
    assert res["repossession"]["matched"] is True
    assert "repossessed" in res["repossession"]["match_terms"]


def test_whole_word_only_no_substring_false_positive():
    compiled = compile_taxonomy(TAXONOMY)
    # "deficiency" should not match inside an unrelated longer token boundary case;
    # here we confirm a word that merely contains letters does not trigger.
    res = classify_text("The repossessionist association met.", compiled)
    # "repossession" as a whole word is absent (only "repossessionist"), so the
    # regex \brepo(ssession)?\b should not match the longer token.
    assert res["regex_cat"]["matched"] is False


def test_min_matches_threshold():
    compiled = compile_taxonomy(TAXONOMY)
    one = classify_text("There was a deficiency balance.", compiled)
    assert one["strong_signal"]["matched"] is False  # only one of the keywords
    two = classify_text("A deficiency was sent to my credit report.", compiled)
    assert two["strong_signal"]["matched"] is True  # two distinct keywords


def test_empty_or_none_text_matches_nothing():
    compiled = compile_taxonomy(TAXONOMY)
    for text in (None, "", "   "):
        res = classify_text(text, compiled)
        assert all(v["matched"] is False for v in res.values())


def test_multiple_categories_can_match_same_narrative():
    compiled = compile_taxonomy(TAXONOMY)
    res = classify_text("They repossessed it with no notice at all.", compiled)
    assert res["repossession"]["matched"] is True
    assert res["notice_failure"]["matched"] is True


def test_score_counts_distinct_pattern_hits():
    compiled = compile_taxonomy(TAXONOMY)
    res = classify_text("took my car after they repossessed it", compiled)
    assert res["repossession"]["score"] == 2.0
