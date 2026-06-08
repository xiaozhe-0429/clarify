"""Clarify v1 覆盖率测试 — 读取 test_dataset.yaml 自动评分.

检测率   = 合理 mode 比例 (目标 ≥75%)
准确消歧率 = 问题数吻合比例 (目标 ≥80%)
综合覆盖率 = 检测率 × 准确消歧率 (目标 ≥60%)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

# 确保 src 在 PYTHONPATH 中
_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from clarify.models import ClarifyContext, Domain
from clarify.rules.engine import RuleEngine


# ── helpers ────────────────────────────────────────────


def _validate_entry(case: dict, idx: int) -> None:
    """校验数据集条目完整性."""
    assert "prompt" in case, f"case #{idx}: missing 'prompt'"
    assert case["domain"] in ("ops", "dev", "general"), (
        f"case #{idx}: invalid domain '{case.get('domain')}'"
    )
    assert case["expected_mode"] in ("pass", "silent_resolve", "must_clarify"), (
        f"case #{idx}: invalid expected_mode '{case.get('expected_mode')}'"
    )
    assert isinstance(case.get("expected_question_count"), int), (
        f"case #{idx}: expected_question_count must be int"
    )


def _mode_ok(actual: str, expected: str) -> bool:
    """模式比对 — pass/must_clarify 必须精确; silent_resolve 可视为非 pass 即可."""
    if expected == "pass":
        return actual == "pass"
    if expected == "silent_resolve":
        return actual != "pass"
    return actual == "must_clarify"


def _q_ok(actual: int, expected: int) -> bool:
    """问题数比对 — 允许 ±1 偏差."""
    return abs(actual - expected) <= 1


# ── fixture ────────────────────────────────────────────


@pytest.fixture(scope="module")
def engine() -> RuleEngine:
    return RuleEngine()


@pytest.fixture(scope="module")
def dataset() -> list[dict]:
    ds_path = Path(__file__).resolve().parent / "test_dataset.yaml"
    with open(ds_path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    cases = data.get("cases", [])
    assert len(cases) == 72, f"Expected 72 cases, got {len(cases)}"
    for i, c in enumerate(cases):
        _validate_entry(c, i)
    return cases


# ── global accumulators ────────────────────────────────

_mode_pass = 0
_q_pass = 0
_false_positive = 0
_false_negative = 0


def _run_one(engine: RuleEngine, case: dict, idx: int) -> None:
    global _mode_pass, _q_pass, _false_positive, _false_negative

    domain = Domain(case["domain"])
    ctx = ClarifyContext(domain=domain, locale="zh-CN")
    result = engine.detect_sync(ctx, prompt=case["prompt"])

    actual_mode = result.mode
    actual_q = len(result.questions)

    expected_mode = case["expected_mode"]
    if _mode_ok(actual_mode, expected_mode):
        _mode_pass += 1
    else:
        if expected_mode == "pass" and actual_mode != "pass":
            _false_positive += 1
        elif expected_mode == "must_clarify" and actual_mode == "pass":
            _false_negative += 1

    expected_q = case["expected_question_count"]
    if _q_ok(actual_q, expected_q):
        _q_pass += 1

    assert _mode_ok(actual_mode, expected_mode), (
        f"[case #{idx}] mode mismatch: expected={expected_mode}, actual={actual_mode} "
        f"| prompt='{case['prompt']}'"
    )
    assert _q_ok(actual_q, expected_q), (
        f"[case #{idx}] question count mismatch: expected={expected_q}, actual={actual_q} "
        f"| prompt='{case['prompt']}'"
    )


# ═══════════════════════════════════════════════════════
# 逐条测试
# ═══════════════════════════════════════════════════════


def test_case_001_to_020(engine: RuleEngine, dataset: list[dict]) -> None:
    for i in range(0, 20):
        _run_one(engine, dataset[i], i)


def test_case_021_to_040(engine: RuleEngine, dataset: list[dict]) -> None:
    for i in range(20, 40):
        _run_one(engine, dataset[i], i)


def test_case_041_to_060(engine: RuleEngine, dataset: list[dict]) -> None:
    for i in range(40, 60):
        _run_one(engine, dataset[i], i)


# ── 汇总 ──────────────────────────────────────────────


def test_summary_report() -> None:
    """打印覆盖率汇总."""
    total = 60
    detect_rate = _mode_pass / total * 100
    disambig_rate = _q_pass / total * 100
    composite = detect_rate * disambig_rate / 100

    detect_ok = "✅" if detect_rate >= 75 else "❌"
    disambig_ok = "✅" if disambig_rate >= 80 else "❌"
    composite_ok = "✅" if composite >= 60 else "❌"

    report_lines = [
        "",
        "=" * 56,
        "   Clarify v1 覆盖率测试汇总",
        "=" * 56,
        f"   检测率: {_mode_pass}/60 ({detect_rate:.1f}%) [目标≥75%] {detect_ok}",
        f"   准确消歧率: {_q_pass}/60 ({disambig_rate:.1f}%) [目标≥80%] {disambig_ok}",
        f"   综合覆盖率: {composite:.1f}% [目标≥60%] {composite_ok}",
        f"   误报数: {_false_positive} / 漏报数: {_false_negative}",
        "=" * 56,
    ]
    print("\n".join(report_lines))

    if composite < 60 or detect_rate < 75 or disambig_rate < 80:
        pytest.fail(
            f"Coverage below target: detect={detect_rate:.1f}% (<75%) "
            f"| disambig={disambig_rate:.1f}% (<80%) "
            f"| composite={composite:.1f}% (<60%)"
        )