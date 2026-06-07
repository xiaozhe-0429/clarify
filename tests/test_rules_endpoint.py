"""M1-3: GET /v1/rules 端点测试."""

import pytest
from fastapi.testclient import TestClient
from clarify.api import app, get_engine


@pytest.fixture(autouse=True)
def _reset_engine():
    """在每次测试后重置 engine 确保可重复."""
    yield
    # 不清理全局状态，因为 get_engine 使用了单例


def test_get_rules_returns_correct_structure() -> None:
    """GET /v1/rules 返回 {total: N, rules: [...]}."""
    client = TestClient(app)
    resp = client.get("/v1/rules")
    assert resp.status_code == 200
    body = resp.json()
    assert "total" in body
    assert "rules" in body
    assert isinstance(body["total"], int)
    assert isinstance(body["rules"], list)


def test_get_rules_total_matches_actual_count() -> None:
    """total 与实际规则数一致."""
    client = TestClient(app)
    resp = client.get("/v1/rules")
    body = resp.json()
    engine = get_engine()
    assert body["total"] == engine.rule_count


def test_get_rules_each_entry_has_required_fields() -> None:
    """每条规则都有 id, name, domain, enabled."""
    client = TestClient(app)
    resp = client.get("/v1/rules")
    body = resp.json()
    for rule in body["rules"]:
        assert "id" in rule, f"Missing 'id' in rule: {rule}"
        assert "name" in rule, f"Missing 'name' in rule: {rule}"
        assert "domain" in rule, f"Missing 'domain' in rule: {rule}"
        assert "enabled" in rule, f"Missing 'enabled' in rule: {rule}"
        assert isinstance(rule["enabled"], bool)
        assert isinstance(rule["id"], str)
        assert isinstance(rule["name"], str)
        assert isinstance(rule["domain"], str)


def test_get_rules_has_content() -> None:
    """规则库应至少有一些规则."""
    client = TestClient(app)
    resp = client.get("/v1/rules")
    body = resp.json()
    assert body["total"] > 0
    assert len(body["rules"]) > 0
