from __future__ import annotations

import pytest

from ostium.services.rules import (
    RuleValidationError,
    path_for,
    validate_rule_match,
    validate_rule_set_name,
)


def test_validate_rule_match_accepts_combinations() -> None:
    match = {
        "domain": ["example.com"],
        "domain_suffix": [".cn"],
        "domain_keyword": ["ads"],
        "domain_regex": ["^ad[0-9]+\\."],
        "ip_cidr": ["10.0.0.0/8", "2001:db8::/32"],
        "port": [80, 443],
        "network": ["tcp"],
        "rule_set": ["geosite-cn"],
        "process_name": ["curl"],
    }
    assert validate_rule_match(match, defined_rule_sets={"geosite-cn"})["port"] == [80, 443]


@pytest.mark.parametrize(
    "match",
    [
        {},
        {"unknown": ["x"]},
        {"domain": []},
        {"domain": [""]},
        {"domain_regex": ["["]},
        {"ip_cidr": ["999.1.1.1/33"]},
        {"port": [0]},
        {"port": ["not-a-port"]},
        {"network": ["icmp"]},
    ],
)
def test_validate_rule_match_rejects_invalid(match: dict) -> None:
    with pytest.raises(RuleValidationError):
        validate_rule_match(match)


def test_rule_set_name_and_path_traversal(settings) -> None:
    assert validate_rule_set_name("geo-site_1") == "geo-site_1"
    for name in ("", "../etc", "a/b", "..", ".hidden", "a" * 65, "bad name"):
        with pytest.raises(RuleValidationError):
            validate_rule_set_name(name)
        assert path_for(settings, name) is None


def test_undefined_rule_set_is_rejected() -> None:
    with pytest.raises(RuleValidationError, match="undefined rule_set"):
        validate_rule_match({"rule_set": ["missing"]}, defined_rule_sets={"present"})
