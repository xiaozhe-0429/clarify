#!/usr/bin/env bash
# run-verify-and-commit.sh — 跑验收 + 准备 git commit
# 使用方法: bash run-verify-and-commit.sh
set -euo pipefail

PROJECT_DIR="${1:-/home/xiaozhe/projects/clarify}"
cd "$PROJECT_DIR"

echo ""
echo "═══ 第一步: 跑验收检查 ═══"
bash check-acceptance.sh
echo ""

echo "═══ 第二步: 准备提交 ═══"
echo ""
echo "以下变更准备提交，请确认后手动执行 git commit:"
echo ""
echo "  # Commit 1: M1-2 模板编译"
echo "  git add src/clarify/templates/ops_checklist.j2 src/clarify/templates/dev_review.j2"
echo '  git commit -m "feat(M1-2): add ops_checklist & dev_review templates, TEMPLATE_BIND_ERROR"'
echo ""
echo "  # Commit 2: M1-3 截断 + JSON 日志 + GET /v1/rules"
echo "  git add src/clarify/models.py src/clarify/api.py src/clarify/logging.py src/clarify/rules/engine.py tests/test_truncation.py tests/test_json_logging.py tests/test_rules_endpoint.py tests/test_clarify.py"
echo '  git commit -m "feat(M1-3): context truncation, JSON logging, GET /v1/rules"'
echo ""
echo "  # Commit 3: M2-1 Prometheus 新指标"
echo "  git add src/clarify/metrics.py tests/test_new_metrics.py"
echo '  git commit -m "feat(M2-1): add 4 new Prometheus metrics (latency_seconds, rules_matched_total, compile_success/failure, missing_vars)"'
echo ""
echo "  # Commit 4: 验收脚本 + 其他"
echo "  git add check-acceptance.sh tests/check_compile_metrics.py"
echo '  git commit -m "chore: add acceptance test script (check-acceptance.sh) and compile metrics checker"'
echo ""
echo "  # 可选: 之前的未提交变更 (OpenClaw 生成的)"
echo "  git add src/clarify/api.py src/clarify/cli.py src/clarify/rules/seed_rules.yaml tests/test_cascade.py src/clarify/llm_fallback.py _check_import.py"
echo ""
echo "全部完成后执行: git log --oneline -5"
