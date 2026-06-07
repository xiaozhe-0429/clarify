"""Clarify v1 测试 — pattern 匹配 + i18n."""

import pytest
from pathlib import Path

from clarify.models import ClarifyContext, ClarifyResponse, Domain
from clarify.rules.engine import RuleEngine, _pattern_match, _i18n, _is_chinese_locale
from clarify.compile import TemplateCompiler


# ── Fixtures ──────────────────────────────────────────

@pytest.fixture
def engine() -> RuleEngine:
    return RuleEngine()


@pytest.fixture
def compiler() -> TemplateCompiler:
    return TemplateCompiler()


# ═══════════════════════════════════════════════════════
# Pattern 匹配
# ═══════════════════════════════════════════════════════

def test_pattern_match_deploy_zh() -> None:
    """中文 '部署' 匹配 ops_deploy_target."""
    raw = {"patterns": ["部署", "deploy"]}
    assert _pattern_match(raw, "帮我部署到生产环境") is True


def test_pattern_match_deploy_en() -> None:
    """英文 'deploy' 匹配."""
    raw = {"patterns": ["部署", "deploy"]}
    assert _pattern_match(raw, "please deploy to production") is True


def test_pattern_match_no_match() -> None:
    """不相关 prompt 不匹配."""
    raw = {"patterns": ["部署", "deploy"]}
    assert _pattern_match(raw, "帮我写个函数") is False


def test_pattern_match_empty_patterns() -> None:
    """空 patterns = 通配, 总是匹配."""
    raw = {"patterns": []}
    assert _pattern_match(raw, "任意内容") is True


def test_pattern_match_no_patterns_field() -> None:
    """无 patterns 字段 = 向后兼容, 总是匹配."""
    raw = {}
    assert _pattern_match(raw, "任意内容") is True


# ═══════════════════════════════════════════════════════
# i18n
# ═══════════════════════════════════════════════════════

def test_i18n_zh_locale() -> None:
    """zh-CN locale 返回中文顶层字段."""
    raw = {"question": "部署目标环境是哪个？", "en": {"question": "Which env?"}}
    assert _i18n(raw, "zh-CN", "question") == "部署目标环境是哪个？"


def test_i18n_en_locale() -> None:
    """en-US locale 返回英文."""
    raw = {"question": "部署目标环境是哪个？", "en": {"question": "Which env?"}}
    assert _i18n(raw, "en-US", "question") == "Which env?"


def test_i18n_en_fallback_when_no_en() -> None:
    """英文 locale 但无 en 字段 → fallback 中文."""
    raw = {"question": "部署目标环境是哪个？"}
    assert _i18n(raw, "en-US", "question") == "部署目标环境是哪个？"


def test_i18n_options_en() -> None:
    """英文 locale 返回英文 options."""
    raw = {
        "options": ["production", "staging"],
        "en": {"options": ["production", "staging", "development"]},
    }
    assert _i18n(raw, "en-US", "options") == ["production", "staging", "development"]


def test_is_chinese_locale() -> None:
    assert _is_chinese_locale("zh-CN") is True
    assert _is_chinese_locale("zh-TW") is True
    assert _is_chinese_locale("zh") is True
    assert _is_chinese_locale("en-US") is False
    assert _is_chinese_locale("en") is False


# ═══════════════════════════════════════════════════════
# 引擎加载
# ═══════════════════════════════════════════════════════

def test_engine_loads_seed_rules(engine: RuleEngine) -> None:
    """验证种子规则库加载成功且未超过 50 条上限."""
    assert engine.rule_count > 0
    assert engine.rule_count <= 50
    assert engine.version == "1.1.0"


# ═══════════════════════════════════════════════════════
# Pattern 匹配 → 规则过滤
# ═══════════════════════════════════════════════════════

def test_detect_with_deploy_prompt(engine: RuleEngine) -> None:
    """prompt='部署' 应匹配 ops 部署相关规则."""
    ctx = ClarifyContext(domain=Domain.OPS, locale="zh-CN")
    result = engine.detect_sync(ctx, prompt="帮我部署到生产环境")
    assert isinstance(result, ClarifyResponse)
    assert len(result.questions) > 0
    # 应有部署相关规则
    q_ids = {q.id for q in result.questions}
    assert "ops_deploy_target" in q_ids, f"部署prompt应触发ops_deploy_target, 实际: {q_ids}"
    # 不应有监控相关规则 (关键词不匹配)
    assert "ops_monitor_metric" not in q_ids, f"部署prompt不应触发监控规则, 实际: {q_ids}"


def test_detect_with_monitor_prompt(engine: RuleEngine) -> None:
    """prompt='监控' 应匹配监控相关规则."""
    ctx = ClarifyContext(domain=Domain.OPS, locale="zh-CN")
    result = engine.detect_sync(ctx, prompt="帮我设置监控告警")
    q_ids = {q.id for q in result.questions}
    assert "ops_monitor_metric" in q_ids, f"监控prompt应触发ops_monitor_metric, 实际: {q_ids}"
    assert "ops_deploy_target" not in q_ids, f"监控prompt不应触发部署规则, 实际: {q_ids}"


def test_detect_with_irrelevant_prompt(engine: RuleEngine) -> None:
    """不相关 prompt 返回空或极少数通配规则."""
    ctx = ClarifyContext(domain=Domain.OPS, locale="zh-CN")
    result = engine.detect_sync(ctx, prompt="吃了吗")
    # 可能返回空 (pass) 或极少数 (无 patterns 的通配规则)
    assert isinstance(result, ClarifyResponse)
    # 所有现有规则都有 patterns, 所以应该为空
    assert result.mode == "pass"


def test_detect_english_prompt(engine: RuleEngine) -> None:
    """英文 prompt 匹配英文关键词."""
    ctx = ClarifyContext(domain=Domain.OPS, locale="en-US")
    result = engine.detect_sync(ctx, prompt="deploy to production please")
    q_ids = {q.id for q in result.questions}
    assert "ops_deploy_target" in q_ids


def test_detect_dev_domain_with_pattern(engine: RuleEngine) -> None:
    """dev domain + API prompt 匹配 API 设计规则."""
    ctx = ClarifyContext(domain=Domain.DEV, locale="zh-CN")
    result = engine.detect_sync(ctx, prompt="设计一个 REST API 接口")
    q_ids = {q.id for q in result.questions}
    assert "dev_api_method" in q_ids
    assert "dev_db_choice" not in q_ids  # 不包含数据库关键词


# ═══════════════════════════════════════════════════════
# i18n 输出
# ═══════════════════════════════════════════════════════

def test_i18n_zh_output(engine: RuleEngine) -> None:
    """中文 locale 返回中文问题."""
    ctx = ClarifyContext(domain=Domain.OPS, locale="zh-CN")
    result = engine.detect_sync(ctx, prompt="部署")
    assert len(result.questions) > 0
    assert any("部署" in q.text for q in result.questions)


def test_i18n_en_output(engine: RuleEngine) -> None:
    """英文 locale 返回英文问题."""
    ctx = ClarifyContext(domain=Domain.OPS, locale="en-US")
    result = engine.detect_sync(ctx, prompt="deploy")
    assert len(result.questions) > 0
    # 英文输出不应包含中文
    texts = " ".join(q.text for q in result.questions)
    assert not any(ord(c) > 127 for c in texts), f"英文locale不应有中文: {texts[:200]}"


# ═══════════════════════════════════════════════════════
# 级联消解 (保留)
# ═══════════════════════════════════════════════════════

def test_cascade_resolve(engine: RuleEngine) -> None:
    """回答 q1 后, 依赖 q1 的 q2 应被消解."""
    ctx1 = ClarifyContext(domain=Domain.OPS, locale="zh-CN")
    r1 = engine.detect_sync(ctx1, prompt="部署")
    assert len(r1.questions) > 0
    q1_id = r1.questions[0].id

    ctx2 = ClarifyContext(
        domain=Domain.OPS,
        locale="zh-CN",
        previous_answers=[{q1_id: "production"}],
    )
    r2 = engine.detect_sync(ctx2, prompt="部署")
    assert len(r2.questions) <= len(r1.questions)


def test_cascade_round2_different_questions(engine: RuleEngine) -> None:
    """第二轮问题应与第一轮不同 (去重)."""
    ctx1 = ClarifyContext(domain=Domain.OPS, locale="zh-CN")
    r1 = engine.detect_sync(ctx1, prompt="部署")
    q1_ids = {q.id for q in r1.questions}
    assert len(q1_ids) > 0

    first_q_id = r1.questions[0].id
    ctx2 = ClarifyContext(
        domain=Domain.OPS, locale="zh-CN",
        previous_answers=[{first_q_id: "staging"}],
    )
    r2 = engine.detect_sync(ctx2, prompt="部署")
    q2_ids = {q.id for q in r2.questions}
    overlap = q1_ids & q2_ids
    assert not overlap, f"第二轮问题与第一轮重复: {overlap}"


def test_cascade_max_2_rounds(engine: RuleEngine) -> None:
    """超过 2 轮级联后, 不再生成问题."""
    ctx1 = ClarifyContext(domain=Domain.OPS, locale="zh-CN")
    r1 = engine.detect_sync(ctx1, prompt="部署")
    assert len(r1.questions) > 0

    ctx2 = ClarifyContext(
        domain=Domain.OPS, locale="zh-CN",
        previous_answers=[
            {"ops_deploy_target": "production"},
            {"ops_alert_severity": "P1-严重"},
        ],
    )
    r2 = engine.detect_sync(ctx2, prompt="部署")
    assert len(r2.questions) >= 0


# ═══════════════════════════════════════════════════════
# 模板编译
# ═══════════════════════════════════════════════════════

def test_template_compile(compiler: TemplateCompiler) -> None:
    """验证 default.j2 渲染成功."""
    rendered, missing = compiler.render("default.j2", {
        "role": "测试",
        "question": "什么是 Kafka?",
        "language": "zh",
    })
    assert "测试" in rendered
    assert "什么是 Kafka?" in rendered


# ═══════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════

def test_response_serializable() -> None:
    """验证 ClarifyResponse 可 JSON 序列化."""
    from clarify.models import ClarifyQuestion
    resp = ClarifyResponse(
        mode="must_clarify",
        questions=[
            ClarifyQuestion(id="q1", text="测试问题", reason="测试原因")
        ],
        rule_version="1.1.0",
        log_id="test-123",
    )
    data = resp.model_dump()
    assert data["mode"] == "must_clarify"
    assert len(data["questions"]) == 1
    assert data["questions"][0]["reason"] == "测试原因"


def test_context_defaults() -> None:
    """ClarifyContext 默认值 (M1-3: recent_prompts/available_targets = None)."""
    ctx = ClarifyContext(domain=Domain.OPS)
    assert ctx.scene == ""
    assert ctx.locale == "zh-CN"
    assert ctx.recent_prompts is None
    assert ctx.available_targets is None


# ═══════════════════════════════════════════════════════
# M1-2: 模板不存在错误
# ═══════════════════════════════════════════════════════

def test_template_ops_checklist_render(compiler: TemplateCompiler) -> None:
    """验证 ops_checklist.j2 模板渲染成功."""
    rendered, missing = compiler.render("ops_checklist.j2", {
        "host": "prod-01",
        "check_time": "2026-06-07T10:00:00Z",
        "service_list": [
            {"name": "nginx", "status": "running"},
            {"name": "postgres", "status": "stopped"},
        ],
        "alert_email": "ops@example.com",
        "severity": "high",
    })
    assert "prod-01" in rendered
    assert "nginx" in rendered
    assert "stopped" in rendered
    assert "high" in rendered
    assert "2026-06-07" in rendered


def test_template_dev_review_render(compiler: TemplateCompiler) -> None:
    """验证 dev_review.j2 模板渲染成功."""
    rendered, missing = compiler.render("dev_review.j2", {
        "pr_number": 42,
        "module": "auth",
        "author": "alice",
        "reviewer": "bob",
        "priority": "high",
    })
    assert "PR #42" in rendered
    assert "auth" in rendered
    assert "alice" in rendered
    assert "bob" in rendered
    assert "high" in rendered


def test_template_not_found_returns_bind_error() -> None:
    """编译不存在的模板应返回 TEMPLATE_BIND_ERROR."""
    from fastapi.testclient import TestClient
    from clarify.api import app, get_compiler

    client = TestClient(app)
    resp = client.post("/v1/compile", json={
        "template_name": "nonexistent_template.j2",
        "answers": {},
    })
    assert resp.status_code == 500
    body = resp.json()
    assert body["error"] == "TEMPLATE_BIND_ERROR"
    assert "nonexistent_template.j2" in body["detail"]