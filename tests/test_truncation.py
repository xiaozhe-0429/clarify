"""M1-3: 上下文截断 — recent_prompts 和 available_targets 截断测试."""

from clarify.models import ClarifyContext, Domain


def test_recent_prompts_truncated_to_5() -> None:
    """recent_prompts 超过 5 条时截断到 5 条."""
    prompts = [f"prompt-{i}" for i in range(10)]
    ctx = ClarifyContext(
        domain=Domain.OPS,
        recent_prompts=prompts,
    )
    assert ctx.recent_prompts is not None
    assert len(ctx.recent_prompts) == 5
    # 保留最近 5 条 (索引 5-9)
    assert ctx.recent_prompts == prompts[-5:]


def test_available_targets_truncated_to_20() -> None:
    """available_targets 超过 20 个时截断到前 20 个."""
    targets = [f"target-{i}" for i in range(30)]
    ctx = ClarifyContext(
        domain=Domain.OPS,
        available_targets=targets,
    )
    assert ctx.available_targets is not None
    assert len(ctx.available_targets) == 20
    # 保留前 20 个 (索引 0-19)
    assert ctx.available_targets == targets[:20]


def test_no_truncation_within_limit() -> None:
    """在限制范围内不截断."""
    ctx = ClarifyContext(
        domain=Domain.OPS,
        recent_prompts=["a", "b"],
        available_targets=["x", "y", "z"],
    )
    assert ctx.recent_prompts == ["a", "b"]
    assert ctx.available_targets == ["x", "y", "z"]


def test_none_fields_not_truncated() -> None:
    """None 字段不应被截断."""
    ctx = ClarifyContext(
        domain=Domain.OPS,
        recent_prompts=None,
        available_targets=None,
    )
    assert ctx.recent_prompts is None
    assert ctx.available_targets is None


def test_empty_list_no_error() -> None:
    """空列表不应报错."""
    ctx = ClarifyContext(
        domain=Domain.OPS,
        recent_prompts=[],
        available_targets=[],
    )
    assert ctx.recent_prompts == []
    assert ctx.available_targets == []
