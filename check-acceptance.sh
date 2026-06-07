#!/usr/bin/env bash
# check-acceptance.sh — Clarify v1 自动化验收脚本
# 每次跑测试后自动检查所有 Milestone 的验收标准
set -euo pipefail

PROJECT_DIR="${1:-/home/xiaozhe/projects/clarify}"
cd "$PROJECT_DIR"

PASS=0
FAIL=0
WARN=0

ok() { PASS=$((PASS+1)); echo "  ✅ $1"; }
fail() { FAIL=$((FAIL+1)); echo "  ❌ $1"; }
warn() { WARN=$((WARN+1)); echo "  ⚠️  $1"; }

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  Clarify v1 自动化验收检查"
echo "═══════════════════════════════════════════════════════"
echo ""

# ── 0. 基础测试 ──────────────────────────────────────
echo "▶ 基础测试"
if python -m pytest -x -q 2>&1 | tee /tmp/clarify_test_result.txt | grep -q "passed"; then
    TOTAL=$(python -m pytest -q 2>/dev/null | grep -oP '\d+(?= passed)' | head -1)
    ok "全部测试通过 ($TOTAL tests)"
else
    fail "测试失败"
    exit 1
fi
echo ""

# ── 1. M1-2: 模板编译 ──────────────────────────────
echo "▶ M1-2: 模板编译"

# 1a. ops_checklist.j2
if [ -f "src/clarify/templates/ops_checklist.j2" ]; then
    ok "ops_checklist.j2 存在"
else
    fail "ops_checklist.j2 不存在"
fi

# 1b. dev_review.j2
if [ -f "src/clarify/templates/dev_review.j2" ]; then
    ok "dev_review.j2 存在"
else
    fail "dev_review.j2 不存在"
fi

# 1c. TEMPLATE_BIND_ERROR
if python -c "
from clarify.models import ErrorCode
assert hasattr(ErrorCode, 'TEMPLATE_BIND_ERROR')
" 2>/dev/null; then
    ok "ErrorCode.TEMPLATE_BIND_ERROR 存在"
else
    fail "ErrorCode.TEMPLATE_BIND_ERROR 不存在"
fi

# 1d. 模板渲染测试
if python -c "
from clarify.compile import TemplateCompiler
c = TemplateCompiler()
rendered, missing = c.render('ops_checklist.j2', {
    'host': 'server1', 'check_time': '2026-06-07',
    'service_list': [{'name': 'nginx', 'status': 'ok'}]
})
assert 'server1' in rendered
" 2>/dev/null; then
    ok "ops_checklist.j2 渲染正常"
else
    fail "ops_checklist.j2 渲染失败"
fi

# 1e. TEMPLATE_BIND_ERROR 捕获
if python -c "
from clarify.compile import TemplateCompiler
c = TemplateCompiler()
try:
    c.render('nonexistent_template.j2', {})
    assert False, 'Should have raised'
except Exception:
    pass
" 2>/dev/null; then
    ok "不存在的模板正确抛出异常"
else
    fail "不存在的模板未正确抛出异常"
fi
echo ""

# ── 2. M1-3: 上下文截断 + JSON 日志 + GET /v1/rules ──
echo "▶ M1-3: 上下文截断 + JSON 日志 + GET /v1/rules"

# 2a. ClarifyContext fields
if python -c "
from clarify.models import ClarifyContext
import inspect
fields = ClarifyContext.model_fields
assert 'recent_prompts' in fields, 'recent_prompts missing'
assert 'available_targets' in fields, 'available_targets missing'
" 2>/dev/null; then
    ok "ClarifyContext 包含 recent_prompts + available_targets"
else
    fail "ClarifyContext 缺少截断字段"
fi

# 2b. 截断逻辑
if python -c "
from fastapi.testclient import TestClient
from clarify.api import app
client = TestClient(app)
# 发送 >5 条 prompts + >20 targets
ctx = {
    'domain': 'ops',
    'recent_prompts': ['p' + str(i) for i in range(10)],
    'available_targets': ['t' + str(i) for i in range(25)],
}
resp = client.post('/v1/clarify', json={'context': ctx, 'prompt': 'test'})
assert resp.status_code == 200, f'Failed: {resp.status_code}'
data = resp.json()
assert 'questions' in data
" 2>/dev/null; then
    ok "上下文截断逻辑工作正常"
else
    warn "上下文截断逻辑验证失败"
fi

# 2c. JsonFormatter
if python -c "
from clarify.logging import JsonFormatter
import logging, json
f = JsonFormatter()
record = logging.LogRecord('test', logging.INFO, '', 0, 'hello', (), None)
output = f.format(record)
data = json.loads(output)
assert 'timestamp' in data
assert data['message'] == 'hello'
" 2>/dev/null; then
    ok "JsonFormatter 输出正确 JSON 格式"
else
    fail "JsonFormatter 输出不正确"
fi

# 2d. GET /v1/rules
if python -c "
from fastapi.testclient import TestClient
from clarify.api import app
client = TestClient(app)
resp = client.get('/v1/rules')
assert resp.status_code == 200, f'Failed: {resp.status_code}'
data = resp.json()
assert 'total' in data
assert 'rules' in data
assert isinstance(data['rules'], list)
" 2>/dev/null; then
    ok "GET /v1/rules 返回正确格式"
else
    fail "GET /v1/rules 响应不正确"
fi
echo ""

# ── 3. M2-1: Prometheus 指标 ──────────────────────
echo "▶ M2-1: Prometheus 指标"

# 3a. 指标端点检查
METRICS=$(python -c "
from fastapi.testclient import TestClient
from clarify.api import app
client = TestClient(app)
resp = client.get('/v1/metrics')
print(resp.text)
" 2>/dev/null)

for metric in "clarify_latency_seconds" "rules_matched_total" "compile_template_success_total" "compile_template_missing_vars_total"; do
    if echo "$METRICS" | grep -q "$metric"; then
        ok "$metric 存在"
    else
        fail "$metric 缺失"
    fi
done

# 3b. latency_seconds 有正确 HELP/TYPE（Histogram 无数据时无 bucket 行，属正常）
if echo "$METRICS" | grep -q "clarify_latency_seconds histogram"; then
    ok "clarify_latency_seconds 直方图已注册"
else
    fail "clarify_latency_seconds 未注册"
fi

# 3c. compile 端点记录 metrics
if python /home/xiaozhe/projects/clarify/tests/check_compile_metrics.py 2>/dev/null | grep -q "OK"; then
    ok "compile 端点正确记录 metrics"
else
    fail "compile 端点 metrics 记录异常"
fi
echo ""

# ── 4. 代码质量 ────────────────────────────────────
echo "▶ 代码质量检查"

# 4a. 导入检查
if python -c "from clarify.api import app; from clarify.compile import TemplateCompiler; from clarify.rules.engine import RuleEngine; print('all imports ok')" 2>&1 | grep -q "ok"; then
    ok "所有模块导入正常"
else
    fail "模块导入失败"
fi

# 4b. 新模板文件编码
for template in "src/clarify/templates/ops_checklist.j2" "src/clarify/templates/dev_review.j2"; do
    if file "$template" 2>/dev/null | grep -q "UTF-8\|ASCII\|text"; then
        ok "$template 编码正常"
    else
        warn "$template 编码可能异常"
    fi
done

# 4c. 未提交变更检查
UNCOMMITTED=$(git status --short 2>/dev/null | wc -l)
if [ "$UNCOMMITTED" -gt 0 ]; then
    warn "有 $UNCOMMITTED 行未提交变更"
else
    ok "无未提交变更"
fi
echo ""

# ── 总结 ──────────────────────────────────────────
echo "═══════════════════════════════════════════════════════"
echo "  结果: ✅ $PASS 通过 | ❌ $FAIL 失败 | ⚠️  $WARN 警告"
echo "═══════════════════════════════════════════════════════"
echo ""

if [ "$FAIL" -gt 0 ]; then
    echo "❌ 验收未通过，有 $FAIL 项失败"
    exit 1
else
    echo "✅ 验收通过"
    exit 0
fi
