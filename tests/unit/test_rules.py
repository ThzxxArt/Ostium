from __future__ import annotations

from ostium.services.rules import evaluate, matches


def test_domain_suffix_and_keyword() -> None:
    assert matches({"domain_suffix": [".cn"]}, {"domain": "www.example.cn"})
    assert not matches({"domain_suffix": [".cn"]}, {"domain": "example.com"})
    assert matches({"domain_keyword": ["example"]}, {"domain": "my.example.com"})
    assert matches({"domain_regex": [r"^ads\."]}, {"domain": "ads.example.com"})


def test_ip_and_port() -> None:
    assert matches({"ip_cidr": ["10.0.0.0/8"]}, {"ip": "10.1.2.3"})
    assert not matches({"ip_cidr": ["10.0.0.0/8"]}, {"ip": "192.168.1.1"})
    assert matches({"port": [443, 8443]}, {"port": 443})
    assert not matches({"port": [443]}, {"port": 80})


def test_first_match_wins() -> None:
    rules = [
        {"enabled": True, "action": "block", "match": {"domain_suffix": ["ads.example.com"]}},
        {"enabled": True, "action": "direct", "match": {"domain_suffix": [".cn"]}},
    ]
    result = evaluate(rules, {"domain": "ads.example.com"})
    assert result["matched"]
    assert result["rule"]["action"] == "block"
    result = evaluate(rules, {"domain": "www.example.cn"})
    assert result["rule"]["action"] == "direct"
    result = evaluate(rules, {"domain": "example.org"})
    assert not result["matched"]


def test_disabled_rule_is_skipped() -> None:
    rules = [{"enabled": False, "action": "block", "match": {"domain": ["x.com"]}}]
    assert not evaluate(rules, {"domain": "x.com"})["matched"]
