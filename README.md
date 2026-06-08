# Clarify — 指令歧义检测与消解引擎

当你在对话中给出模糊指令，在你动手之前，Clarify 先帮你把话说清楚。

## 一句话

Clarify 是一个**纯规则引擎 + LLM 兜底**的歧义检测服务。收到一条指令，它判断是否存在歧义，返回：
- **pass** — 指令明确，直接执行
- **silent_resolve** — 有歧义但可自动填充默认值
- **must_clarify** — 需要追问用户澄清（附带具体问题和选项）

## 快速开始

```bash
# 安装
pip install -e .

# CLI 使用
clarify detect --domain dev --question "重构用户模块"

# 启动 HTTP 服务
clarify serve
curl http://localhost:8000/v1/health
```

## CLI 使用

```bash
# 检测指令歧义
clarify detect --domain dev --question "优化这个接口"

# 带场景文件
clarify detect --domain ops --question "重启服务" --scene-file scenarios/ops.yaml

# 带上一轮回答（级联消解）
clarify detect --domain dev --question "添加用户注册" \
  --previous-answers '[{"dev_api_method":"POST"}]'

# 查看规则版本
clarify version

# 规则统计
clarify stats

# 编译模板
clarify compile --template dev_review --vars '{"module":"auth"}'
```

## HTTP API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/v1/clarify` | POST | 歧义检测 |
| `/v1/compile` | POST | 模板编译 |
| `/v1/rules` | GET | 查看所有规则 |
| `/v1/health` | GET | 健康检查 |
| `/v1/metrics` | GET | Prometheus 指标 |
| `/v1/docs` | GET | Swagger UI |

### POST /v1/clarify

```json
{
  "prompt": "重构用户模块",
  "context": {
    "domain": "dev",
    "locale": "zh-CN",
    "recent_prompts": ["修复登录页BUG"],
    "available_targets": ["认证模块", "订单模块"]
  }
}
```

响应：
```json
{
  "mode": "must_clarify",
  "questions": [
    {
      "id": "dev_refactor",
      "text": "重构的目标和范围？",
      "reason": "重构需要明确目标和边界以避免引入新问题"
    }
  ],
  "rule_version": "1.3.0",
  "log_id": "a1b2c3d4-..."
}
```

## 规则系统

种子规则存放在 `src/clarify/rules/seed_rules.yaml`，每条规则包含：

```yaml
- id: dev_refactor
  domain: dev
  scene: code_review
  priority: 80
  mode: must_clarify
  patterns: ["重构", "refactor"]
  exclude_patterns: ["合并", "merge"]    # 匹配 patterns 但命中排除词 → 不触发
  question: "重构的目标和范围？"
  reason: "重构需要明确目标和边界以避免引入新问题"
  options: ["代码可读性", "性能优化", "架构调整"]
```

当前规则数：50 条种子规则 + 9 条场景规则 = 59 条。

### 场景文件

独立的场景 YAML 放在 `scenarios/` 目录下，覆盖 ops/dev/general 三个业务域。

### LLM 兜底

当种子规则和场景规则都不匹配时，自动调用 LLM（默认 `astron-code-latest`）生成澄清问题。通过环境变量配置：

- `CLARIFY_LLM_ENABLED` — 启用/禁用（默认 true）
- `CLARIFY_LLM_BASE_URL` — API 地址
- `CLARIFY_LLM_API_KEY` — API 密钥（默认用 `OPENAI_API_KEY`）
- `CLARIFY_LLM_MODEL` — 模型名（默认 `astron-code-latest`）

跳过条件：指令 ≤3 字符（"你好"、"在吗" 等问候语）。

## 项目结构

```
clarify/
├── src/clarify/
│   ├── cli.py               # Click CLI
│   ├── api.py                # FastAPI HTTP 服务
│   ├── models.py             # Pydantic 数据模型
│   ├── compile.py            # 模板编译器
│   ├── logging.py            # 结构化日志
│   ├── metrics.py            # Prometheus 指标
│   ├── llm_fallback.py       # LLM 兜底检测
│   ├── rules/
│   │   ├── engine.py         # 规则引擎
│   │   └── seed_rules.yaml   # 种子规则库
│   └── templates/            # 编译模板 (Jinja2)
├── scenarios/                # 场景配置
│   ├── ops.yaml
│   ├── dev.yaml
│   └── general.yaml
├── tests/                    # 测试
│   ├── test_clarify.py       # 引擎测试
│   ├── test_coverage.py      # 覆盖率测试
│   ├── test_dataset.yaml     # 60 条标注测试集
│   ├── test_cascade.py       # 级联消解测试
│   ├── test_scenarios.py     # 场景文件测试
│   └── ...
├── docker-compose.yml
├── Dockerfile
└── PRD.md                    # 项目需求文档
```

## 测试

```bash
# 运行全部测试
pytest

# 覆盖率和质量门禁
pytest tests/test_coverage.py
```

当前覆盖率为 100%（60 条测试用例，2026-06-09）。

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CLARIFY_LLM_ENABLED` | `true` | LLM 兜底开关 |
| `CLARIFY_LLM_BASE_URL` | 讯飞 MaaS 推理 API | LLM API 地址 |
| `CLARIFY_LLM_API_KEY` | `OPENAI_API_KEY` | LLM API 密钥 |
| `CLARIFY_LLM_MODEL` | `astron-code-latest` | LLM 模型名 |
| `CLARIFY_LLM_TIMEOUT` | `15` | LLM 请求超时（秒） |
| `CLARIFY_LLM_MAX_TOKENS` | `512` | LLM 最大输出 tokens |
| `CLARIFY_LOG_LEVEL` | `INFO` | 日志级别 |

## 部署

```bash
# Docker
docker-compose up -d

# systemd (user mode)
systemctl --user enable clarify.service
systemctl --user start clarify.service
```
