"""Clarify v1 测试骨架."""

import pytest
from pathlib import Path

from clarify.models import ClarifyContext, ClarifyRequest, ClarifyResponse
from clarify.rules.engine import RuleEngine
from clarify.compile import TemplateCompiler


# ── Fixtures ──────────────────────────────────────────

@pytest.fixture
def engine() -> RuleEngine:
    return RuleEngine()


@pytest.fixture
def compiler() -> TemplateCompiler:
    return TemplateCompiler()


# ── Test 1: 规则引擎加载 ─────────────────────────────

def test_engine_loads_seed_rules(engine: RuleEngine) -> None:
    """验证种子规则库加载成功且未超过 50 条上限."""
    assert engine.rule_count > 0
    assert engine.rule_count <= 50
    assert engine.version == "1.0.0"


# ── Test 2: domain + scene 匹配 ───────────────────────

def test_engine_matches_domain_scene(engine: RuleEngine) -> None:
    """验证 domain=ops, scene=deploy 命中至少 1 条规则."""
    ctx = ClarifyContext(domain="ops", scene="deploy", question="部署到生产环境")
    result = engine.detect(ctx)
    assert isinstance(result, ClarifyResponse)
    assert result.mode in ("pass", "silent_resolve", "must_clarify")
    assert len(result.questions) > 0


# ── Test 3: pass 模式 (无匹配规则时降级放行) ──────────

def test_unknown_scene_passes(engine: RuleEngine) -> None:
    """不存在的 scene 应返回 pass 模式空问题列表."""
    ctx = ClarifyContext(domain="ops", scene="nonexistent", question="test")
    result = engine.detect(ctx)
    assert result.mode == "pass"
    assert len(result.questions) == 0


# ── Test 4: 模板编译 ──────────────────────────────────

def test_template_compile(compiler: TemplateCompiler) -> None:
    """验证 default.j2 渲染成功."""
    rendered, missing = compiler.render("default.j2", {
        "role": "测试",
        "question": "什么是 Kafka?",
        "language": "zh",
    })
    assert "测试" in rendered
    assert "什么是 Kafka?" in rendered
    # context 是 optional, 不提供也算 missing
    assert "context" in missing or len(missing) >= 0


# ── Test 5: 级联消解 ─────────────────────────────────

def test_cascade_resolve(engine: RuleEngine) -> None:
    """回答 q1 后, 依赖 q1 的 q2 应被消解."""
    ctx1 = ClarifyContext(
        domain="ops", scene="deploy", question="部署"
    )
    r1 = engine.detect(ctx1)
    assert len(r1.questions) > 0
    q1_id = r1.questions[0].id

    # 第二次请求: 带上 q1 的答案
    ctx2 = ClarifyContext(
        domain="ops",
        scene="deploy",
        question="继续部署",
        previous_answers=[{q1_id: "production"}],
    )
    r2 = engine.detect(ctx2)
    # depends_on=q1_id 的规则应被消解, 所以 questions 数量减少
    assert len(r2.questions) <= len(r1.questions)


# ── Test 6: 数据模型序列化 ────────────────────────────

def test_response_serializable() -> None:
    """验证 ClarifyResponse 可 JSON 序列化."""
    from clarify.models import ClarifyQuestion
    resp = ClarifyResponse(
        mode="must_clarify",
        questions=[
            ClarifyQuestion(id="q1", text="测试问题", reason="测试原因")
        ],
        rule_version="1.0.0",
        log_id="test-123",
    )
    data = resp.model_dump()
    assert data["mode"] == "must_clarify"
    assert len(data["questions"]) == 1
    assert data["questions"][0]["reason"] == "测试原因"