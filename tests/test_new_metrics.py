"""M2-1: Prometheus 新指标测试."""

import pytest
from fastapi.testclient import TestClient

from clarify.api import app, get_compiler


@pytest.fixture
def client():
    return TestClient(app)


# ═══════════════════════════════════════════════════════
# 验证 /v1/metrics 包含新指标
# ═══════════════════════════════════════════════════════

def test_metrics_contains_clarify_latency_seconds(client) -> None:
    """验证 /v1/metrics 返回中包含 clarify_latency_seconds 指标."""
    resp = client.get("/v1/metrics")
    assert resp.status_code == 200
    text = resp.text
    assert "clarify_latency_seconds" in text


def test_metrics_contains_rules_matched_total(client) -> None:
    """验证 /v1/metrics 返回中包含 rules_matched_total 指标."""
    resp = client.get("/v1/metrics")
    assert resp.status_code == 200
    text = resp.text
    assert "rules_matched_total" in text


# ═══════════════════════════════════════════════════════
# 验证编译成功后 compile_template_success_total 增加
# ═══════════════════════════════════════════════════════

def test_compile_success_increments_counter(client) -> None:
    """验证编译成功后 compile_template_success_total.labels(status="success") 增加."""
    get_compiler()  # warm up
    template_name = "default.j2"

    # 先获取基准值
    resp_before = client.get("/v1/metrics")
    before_lines = resp_before.text.splitlines()
    base_value = 0
    for line in before_lines:
        if line.startswith("compile_template_success_total{") and 'status="success"' in line:
            base_value = float(line.strip().split()[-1])
            break

    # 触发编译
    resp = client.post("/v1/compile", json={
        "template_name": template_name,
        "answers": {"role": "测试", "question": "What is it?", "language": "en"},
    })
    assert resp.status_code == 200
    assert resp.json()["rendered"] is not None

    # 验证计数器增加
    resp_after = client.get("/v1/metrics")
    after_lines = resp_after.text.splitlines()
    success_value = 0
    for line in after_lines:
        if line.startswith("compile_template_success_total{") and 'status="success"' in line:
            success_value = float(line.strip().split()[-1])
            break

    assert success_value > base_value, (
        f"compile_template_success_total success 计数器未增加: "
        f"基准={base_value}, 现在={success_value}"
    )


def test_compile_failure_increments_failure_counter(client) -> None:
    """验证模板不存在时 compile_template_success_total.labels(status="failure") 增加."""
    # 先获取基准值
    resp_before = client.get("/v1/metrics")
    before_lines = resp_before.text.splitlines()
    base_fail = 0
    for line in before_lines:
        if line.startswith("compile_template_success_total{") and 'status="failure"' in line:
            base_fail = float(line.strip().split()[-1])
            break

    # 触发模板不存在错误
    resp = client.post("/v1/compile", json={
        "template_name": "nonexistent_template.j2",
        "answers": {},
    })
    assert resp.status_code == 500
    assert resp.json()["error"] == "TEMPLATE_BIND_ERROR"

    # 验证 failure 计数器增加
    resp_after = client.get("/v1/metrics")
    after_lines = resp_after.text.splitlines()
    fail_value = 0
    for line in after_lines:
        if line.startswith("compile_template_success_total{") and 'status="failure"' in line:
            fail_value = float(line.strip().split()[-1])
            break

    assert fail_value > base_fail, (
        f"compile_template_success_total failure 计数器未增加: "
        f"基准={base_fail}, 现在={fail_value}"
    )


def test_missing_vars_bucket_label(client) -> None:
    """验证 compile_template_missing_vars_total 有正确的 count_bucket 标签."""
    resp = client.get("/v1/metrics")
    text = resp.text
    # 检查 count_bucket 标签存在
    assert "count_bucket" in text
    # 验证 bucket 值有效 (0, 1, 2, 3, 4, 5+)
    import re
    buckets_found = re.findall(r'count_bucket="([^"]+)"', text)
    valid_buckets = {"0", "1", "2", "3", "4", "5+"}
    if buckets_found:
        assert all(b in valid_buckets for b in buckets_found), (
            f"Invalid bucket values: {buckets_found}"
        )


def test_clarify_latency_labels(client) -> None:
    """验证 clarify_latency_seconds 指标有正确的 domain 和 scene 标签."""
    # 先触发 clarify 请求
    resp = client.post("/v1/clarify", json={
        "prompt": "部署到生产环境",
        "context": {"domain": "ops", "scene": "deploy"},
    })
    assert resp.status_code == 200

    # 验证指标包含正确标签
    resp_metrics = client.get("/v1/metrics")
    text = resp_metrics.text
    assert "domain=\"ops\"" in text
    assert 'scene="deploy"' in text
