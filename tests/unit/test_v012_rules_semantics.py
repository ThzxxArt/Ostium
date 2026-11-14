"""Rule tester semantics must match sing-box, not Python's regex engine."""

from __future__ import annotations

import pytest

from ostium.services.rules import (
    RuleValidationError,
    evaluate,
    matches,
    validate_rule_match,
)


def test_rule_set_only_rules_are_unknown_not_matches() -> None:
    rule = {"match": {"rule_set": ["geosite-cn"]}, "action": "block"}
    result = evaluate([rule], {"domain": "example.com"})
    assert result["matched"] is False
    assert result["unknown"] is True
    assert matches({"rule_set": ["geosite-cn"]}, {"domain": "example.com"}) is False


def test_rule_set_with_other_conditions_is_still_unknown() -> None:
    # sing-box combines conditions with AND; the offline tester cannot prove
    # the rule-set half, so it must not claim a match from the domain half.
    assert (
        matches(
            {"rule_set": ["geosite-cn"], "domain": ["example.com"]},
            {"domain": "example.com"},
        )
        is False
    )


@pytest.mark.parametrize(
    "pattern",
    [
        "(?=example)",
        "(?!example)",
        "(?<=example)",
        "(?<!example)",
        "(?>example)",
        "(?P<name>example)",
        r"(example)\1",
        r"\k<name>",
    ],
)
def test_python_only_regex_is_rejected_before_sing_box_sees_it(pattern: str) -> None:
    with pytest.raises(RuleValidationError, match="sing-box"):
        validate_rule_match({"domain_regex": [pattern]})


def test_plain_re2_compatible_regex_is_accepted() -> None:
    assert validate_rule_match({"domain_regex": ["^ads?[0-9]+\\.example\\.com$"]})


def test_domain_suffix_respects_label_boundaries() -> None:
    assert matches({"domain_suffix": [".cn"]}, {"domain": "www.example.cn"})
    assert matches({"domain_suffix": ["example.cn"]}, {"domain": "example.cn"})
    assert not matches({"domain_suffix": ["example.cn"]}, {"domain": "notexample.cn"})
