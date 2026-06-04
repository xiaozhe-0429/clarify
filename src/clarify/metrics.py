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


def get_metrics() -> bytes:
    """返回 Prometheus 文本格式指标."""
    return generate_latest(REGISTRY)
