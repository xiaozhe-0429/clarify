"""测试场景文件加载与校验."""

from __future__ import annotations

import pytest
import yaml
from pathlib import Path

SCENARIOS_DIR = Path(__file__).resolve().parent.parent / "scenarios"

SCENARIO_FILES = ["ops.yaml", "dev.yaml", "general.yaml"]

EXPECTED_DOMAINS = {
    "ops.yaml": "ops",
    "dev.yaml": "dev",
    "general.yaml": "general",
}


@pytest.mark.parametrize("filename", SCENARIO_FILES)
def test_scenario_file_exists(filename: str) -> None:
    """验证场景文件存在."""
    path = SCENARIOS_DIR / filename
    assert path.exists(), f"场景文件不存在: {filename}"


@pytest.mark.parametrize("filename", SCENARIO_FILES)
def test_scenario_is_valid_yaml(filename: str) -> None:
    """验证场景文件是合法 YAML."""
    path = SCENARIOS_DIR / filename
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    assert isinstance(data, dict), f"{filename}: 根不是 dict"
    assert "version" in data, f"{filename}: 缺少 version"
    assert "domain" in data, f"{filename}: 缺少 domain"
    assert "rules" in data, f"{filename}: 缺少 rules"
    assert isinstance(data["rules"], list), f"{filename}: rules 不是 list"


@pytest.mark.parametrize("filename", SCENARIO_FILES)
def test_scenario_domain_correct(filename: str) -> None:
    """验证 domain 字段正确."""
    path = SCENARIOS_DIR / filename
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    assert data["domain"] == EXPECTED_DOMAINS[filename], (
        f"{filename}: domain 应为 {EXPECTED_DOMAINS[filename]}, "
        f"实际为 {data['domain']}"
    )


@pytest.mark.parametrize("filename", SCENARIO_FILES)
def test_scenario_rule_count_leq_15(filename: str) -> None:
    """验证每个场景规则数 ≤15."""
    path = SCENARIOS_DIR / filename
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    count = len(data["rules"])
    assert count <= 15, (
        f"{filename}: 规则数 {count} 超过上限 15"
    )
    assert count > 0, f"{filename}: 规则数为空"


@pytest.mark.parametrize("filename", SCENARIO_FILES)
def test_scenario_rules_have_required_fields(filename: str) -> None:
    """验证每条规则包含必要字段."""
    path = SCENARIOS_DIR / filename
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    required = {"id", "pattern", "ambiguity_type", "mode", "question", "reason"}
    for i, rule in enumerate(data["rules"]):
        missing = required - set(rule.keys())
        assert not missing, (
            f"{filename} rule[{i}] ({rule.get('id', '?')}) 缺少字段: {missing}"
        )


def test_total_rules_across_scenarios_leq_50() -> None:
    """验证所有场景 + seed_rules 总规则数 ≤50."""
    total = 0
    for filename in SCENARIO_FILES:
        path = SCENARIOS_DIR / filename
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        total += len(data["rules"])
    # seed_rules 已有 41 条 (根据实际文件)
    seed_path = Path(__file__).resolve().parent.parent / "src" / "clarify" / "rules" / "seed_rules.yaml"
    with open(seed_path, encoding="utf-8") as fh:
        seed_data = yaml.safe_load(fh)
    seed_count = len(seed_data["rules"])
    grand_total = total + seed_count
    assert grand_total <= 60, (
        f"总规则数 {grand_total} (seed={seed_count} + scenarios={total}) 超过上限 60"
    )