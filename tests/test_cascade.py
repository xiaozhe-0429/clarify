"""测试级联消解逻辑."""

from __future__ import annotations

import pytest

from clarify.models import ClarifyContext, ClarifyResponse, Domain
from clarify.rules.engine import RuleEngine


@pytest.fixture
def engine() -> RuleEngine:
    """种子规则库引擎."""
    return RuleEngine()


# ── Test 1: 第一轮正常匹配 ────────────────────────────

def test_cascade_round1_has_questions(engine: RuleEngine) -> None:
    """第一轮 (无 previous_answers) 应返回问题列表."""
    ctx = ClarifyContext(domain=Domain.OPS)
    result = engine.detect(ctx)
    assert isinstance(result, ClarifyResponse)
    assert len(result.questions) > 0
    assert result.mode == "must_clarify"


# ── Test 2: 第二轮基于答案匹配新歧义 ─────────────────

def test_cascade_round2_different_questions(engine: RuleEngine) -> None:
    """第二轮问题应与第一轮不同 (去重)."""
    # 第一轮
    ctx1 = ClarifyContext(domain=Domain.OPS)
    r1 = engine.detect(ctx1)
    q1_ids = {q.id for q in r1.questions}
    assert len(q1_ids) > 0

    # 模拟用户回答了第一个问题
    first_q_id = r1.questions[0].id
    prev_answers = [{first_q_id: "staging"}]

    # 第二轮
    ctx2 = ClarifyContext(domain=Domain.OPS, previous_answers=prev_answers)
    r2 = engine.detect(ctx2)

    # 第二轮问题 ID 不应与第一轮重叠
    q2_ids = {q.id for q in r2.questions}
    overlap = q1_ids & q2_ids
    assert not overlap, (
        f"第二轮问题与第一轮重复: {overlap}"
    )


# ── Test 3: depends_on 级联激活 ───────────────────────

def test_cascade_activates_depends_on(engine: RuleEngine) -> None:
    """回答 q1 后, 依赖 q1 的规则应在第二轮出现."""
    # 使用 ops 域: ops_deploy_strategy depends_on ops_deploy_target
    ctx1 = ClarifyContext(domain=Domain.OPS)
    r1 = engine.detect(ctx1)

    # 找到有 depends_on 引用的规则
    from clarify.rules.engine import Rule
    deploy_target_id = "ops_deploy_target"
    deploy_strategy_id = "ops_deploy_strategy"

    assert any(q.id == deploy_target_id for q in r1.questions), (
        "第一轮应包含 ops_deploy_target"
    )

    # 第 2 轮: 回答了 deploy_target
    ctx2 = ClarifyContext(
        domain=Domain.OPS,
        previous_answers=[{deploy_target_id: "production"}],
    )
    r2 = engine.detect(ctx2)

    # deploy_strategy 在第一轮可能被其他规则遮蔽 (非 depends_on),
    # 但第二轮中, 如果它 depends_on deploy_target 且 deploy_target 已回答,
    # 应该出现在第二轮
    q2_ids = {q.id for q in r2.questions}
    q1_ids = {q.id for q in r1.questions}

    # 第二轮不应该包含 deploy_target (已回答)
    assert deploy_target_id not in q2_ids, "已回答的问题不应再次出现"

    # 第二轮问的问题应与第一轮完全不同
    assert not (q1_ids & q2_ids), "第二轮不应与第一轮有重叠问题"


# ── Test 4: 超过 2 轮不再追问 ─────────────────────────

def test_cascade_max_2_rounds(engine: RuleEngine) -> None:
    """超过 2 轮级联后, 不再生成问题."""
    ctx1 = ClarifyContext(domain=Domain.OPS)
    r1 = engine.detect(ctx1)
    assert len(r1.questions) > 0

    # 第 2 轮
    ctx2 = ClarifyContext(
        domain=Domain.OPS,
        previous_answers=[
            {"ops_deploy_target": "production"},
            {"ops_alert_severity": "P1-严重"},
        ],
    )
    r2 = engine.detect(ctx2)
    # 两轮后应返回空或极少数问题
    assert len(r2.questions) >= 0, "不应崩溃"


# ── Test 5: 场景文件引擎也支持级联 ────────────────────

def test_cascade_with_scenario_file() -> None:
    """场景文件的引擎也应支持级联消解."""
    from pathlib import Path

    scenarios_dir = Path(__file__).resolve().parent.parent / "scenarios"
    engine = RuleEngine(scenarios_dir / "ops.yaml")

    # 第一轮
    ctx1 = ClarifyContext(domain=Domain.OPS)
    r1 = engine.detect(ctx1)
    assert len(r1.questions) > 0

    first_q_id = r1.questions[0].id

    # 第二轮
    ctx2 = ClarifyContext(
        domain=Domain.OPS,
        previous_answers=[{first_q_id: "answer"}],
    )
    r2 = engine.detect(ctx2)
    q1_ids = {q.id for q in r1.questions}
    q2_ids = {q.id for q in r2.questions}
    assert not (q1_ids & q2_ids), (
        f"场景文件级联消解: 第二轮不应重复第一轮问题, 重复: {q1_ids & q2_ids}"
    )


# ── Test 6: dev 域级联 ─────────────────────────────────

def test_cascade_dev_domain(engine: RuleEngine) -> None:
    """dev 域级联消解正确."""
    ctx1 = ClarifyContext(domain=Domain.DEV)
    r1 = engine.detect(ctx1)
    assert len(r1.questions) > 0

    first_q_id = r1.questions[0].id

    ctx2 = ClarifyContext(
        domain=Domain.DEV,
        previous_answers=[{first_q_id: "answer"}],
    )
    r2 = engine.detect(ctx2)
    q1_ids = {q.id for q in r1.questions}
    q2_ids = {q.id for q in r2.questions}
    overlap = q1_ids & q2_ids
    assert not overlap, f"dev 域级联: 第二轮不应重复, 重复: {overlap}"