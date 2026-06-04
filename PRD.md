# Clarify v1 — 项目需求文档 (PRD)

> 面向 Codex CLI 的开发需求摘要，基于三方共识与 Reviewer 评审修正。

---

## 项目概述

**Clarify v1** 是一个纯规则引擎的指令歧义检测与消解服务——在用户模糊指令进入下游执行前，先检测歧义、必要时提问澄清、最终编译出精确指令。零 LLM 依赖，延迟 <50ms P95，行为完全可解释。

---

## 核心修正（4 项，必须实现）

1. **数据流转路径**：v1 采用 HTTP body 附带 `context` 快照，不引入共享存储。调用方自行拼装 context（`recent_prompts`、`available_targets`、`domain`、`locale`），v2 可切为引用 ID。
2. **量化指标定义**：<30ms 检测延迟 P95，<20ms 编译延迟 P95，<50ms 端到端 P95（空载单条）；覆盖率 = 检测率（≥75%）× 准确消歧率（≥80%），综合 ≥60%。
3. **日志 schema 对齐 v2**：v1 输出 `ClarifyLogEntry` schema 与 v2 一致，`downstream_result` 和 `feedback_signal` 字段 v1 留 null，v2 直接补填无需改 schema。
4. **错误处理规范**：6 个错误码（`RULE_MISS` 200 / `CONTEXT_MISSING` 422 / `CONTEXT_INVALID` 422 / `TEMPLATE_BIND_ERROR` 500 / `RULE_EXEC_ERROR` 500 / `COMPILE_NO_ANSWERS` 422），所有可恢复错误降级放行不阻塞指令。

---

## 建议采纳（3 项）

- **问题采纳率 & 级联消解命中率**：辅助指标，衡量问题质量和级联消解设计有效性。
- **compile 模板语法**：`{{var}}` 标记，必选变量缺失 → `TEMPLATE_BIND_ERROR`，可选变量缺失 → 空字符串，绑定优先级 answers > context > 默认值。
- **里程碑拆分**：M1 核心通路（规则引擎+歧义检测+模板+API+错误处理），M2 体验完善（场景配置+级联消解+可解释性+CLI插件+日志+指标）。

---

## 遗漏补全（4 项）

- **测试集构建**：三方各贡献 20 条模糊指令，交叉标注校验，合并 60 条初版，迭代至 100 条。
- **规则冷启动**：Codex 提取高频动词+名词组合，Hermes 提取对话 Top 50 模糊指令，OpenClaw 提取 SRE 危险模糊指令，合并去重 30-50 条种子规则。
- **规则版本管理**：语义化版本（`rule_version: "1.0.0"`），YAML 头部声明，API 返回附带版本号。
- **API 版本策略**：URL path versioning（`/v1/clarify`、`/v1/compile`），v1 兼容 ≥6 个月。

---

## 技术栈建议

| 层 | 选型 | 理由 |
|----|------|------|
| Web 框架 | FastAPI (Python 3.11+) | 异步原生，性能优异，Pydantic 集成 |
| 规则引擎 | 自研 YAML 规则库 + Python 匹配器 | 纯规则无依赖，延迟可控 |
| 模板引擎 | Jinja2 | `{{var}}` 兼容，成熟稳定 |
| 配置管理 | YAML 场景文件 | 每场景独立文件，<100 行 |
| 日志/指标 | structlog + Prometheus metrics | 结构化日志 + 指标暴露 |
| 测试 | pytest + 标注测试集 | 交叉校验覆盖率报告 |
| CLI 插件 | Python Click | 轻量命令行封装 |
| 容器化 | Docker + docker-compose | 单容器部署，零外部依赖 |

---

## v1 范围清单

### 纳入（M1 核心通路）
- 歧义分类法（5 类：指代/目标/范围/格式/前提）
- 三种模式（pass / silent_resolve / must_clarify）
- 规则引擎 + YAML 规则库（30-50 条种子规则）
- 模板系统（Jinja2，必选/可选变量绑定）
- context schema（`ClarifyContext`：recent_prompts、available_targets、domain、locale）
- `POST /v1/clarify` + `POST /v1/compile`
- 6 个错误码 + 降级放行策略
- 歧义优先级 + 最多 2 问 + 级联消解
- 可解释性（每个问题附带 reason）
- 日志写入（`ClarifyLogEntry` schema）

### 纳入（M2 体验完善）
- 场景配置文件（ops/dev/general，每场景 ≤15 条规则，总规则 ≤50 条硬上限）
- CLI 插件（Click）
- 指标采集（检测延迟、编译延迟、覆盖率、问题采纳率、级联命中率）
- 规则版本号 API 返回

### 不纳入（v2）
- 小模型生成问题
- 中间件模式 / SDK
- 自动回流调优
- Gateway 前置集成
- 共享存储 context_ref

---

## 风险缓解

| 风险 | 等级 | 措施 |
|------|------|------|
| 规则膨胀 | 🔴 高 | 硬上限 50 条，超出淘汰旧规则（拒绝率数据驱动） |
| 中文指代消解天花板 | 🟡 中 | 无 recent_prompts 时指代歧义标记低置信度，不生成问题 |
| 配置组合爆炸 | 🟡 中 | 仅 3 场景 × 5 歧义类型 = 15 个阈值位，无交叉矩阵 |

---

## 验收标准

### M1 验收
- [ ] `POST /v1/clarify` 对 60 条测试集 detect 延迟 P95 < 30ms
- [ ] `POST /v1/compile` 编译延迟 P95 < 20ms
- [ ] 三种模式均返回正确（pass/silent_resolve/must_clarify）
- [ ] 所有 6 种错误码触发正确 HTTP status + fallback 行为
- [ ] context 缺少 `domain` → 422，非法值 → 422
- [ ] 模板变量缺失 → 500 + fallback: pass
- [ ] 规则库无匹配 → 200 + mode: pass（不阻塞）
- [ ] 日志输出符合 `ClarifyLogEntry` schema

### M2 验收
- [ ] 检测率 ≥75%，准确消歧率 ≥80%，综合覆盖率 ≥60%
- [ ] 3 个场景配置文件各自独立，行数 <100
- [ ] 级联消解：回答 q1 后 q2 自动消解生效
- [ ] 每个 question 附带 `reason` 字段
- [ ] CLI 插件可独立运行 `/clarify` 流程
- [ ] 规则版本号在 API 响应中返回

### 非功能验收
- [ ] 端到端延迟 <50ms P95（空载，单条 prompt）
- [ ] 规则库硬上限 50 条，物理阻止膨胀
- [ ] API 响应中 `rule_version` 字段存在且符合 semver
- [ ] v1/v2 URL path 隔离，v1 接口不受 v2 上线影响