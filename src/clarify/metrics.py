"""Prometheus 指标 — 请求计数、延迟直方图、规则匹配."""

from prometheus_client import Counter, Histogram, generate_latest, REGISTRY

# 请求计数
requests_total = Counter(
    "clarify_requests_total",
    "Total clarify requests",
    ["domain", "scene", "mode"],
)

# 延迟 (ms)
latency_histogram = Histogram(
    "clarify_request_latency_ms",
    "Request latency in milliseconds",
    ["domain", "scene"],
    buckets=[1, 5, 10, 25, 50, 100, 250, 500, 1000],
)

# 规则命中数
rules_matched = Histogram(
    "clarify_rules_matched",
    "Number of rules matched per request",
    buckets=[0, 1, 2, 3, 5, 10, 20, 50],
)

# 错误计数
errors_total = Counter(
    "clarify_errors_total",
    "Total errors",
    ["error_code"],
)

# ── M2-1: 新增 Prometheus 指标 ────────────────────────

clarify_latency_seconds = Histogram(
    "clarify_latency_seconds",
    "Request latency in seconds",
    ["domain", "scene"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

rules_matched_total = Counter(
    "rules_matched_total",
    "Total rules matched",
    ["rule_name", "domain", "matched"],
)

compile_template_success_total = Counter(
    "compile_template_success_total",
    "Template compilation success/failure",
    ["template_name", "status"],
)

compile_template_missing_vars_total = Counter(
    "compile_template_missing_vars_total",
    "Missing variables per compilation",
    ["template_name", "count_bucket"],
)


def get_metrics() -> bytes:
    """返回 Prometheus 文本格式指标."""
    return generate_latest(REGISTRY)
