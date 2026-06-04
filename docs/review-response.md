# Clarify v1 — Reviewer 评审修正回应

> 针对「⚠️ 有条件通过」评审结果的逐项修正，修正后可进入开发。

---

## 一、核心修正项（4/4）

### 1. 数据流转路径（H4）

**决策：v1 采用 HTTP body 附带 context 快照**

```
调用方 → POST /v1/clarify
  Body: {
    "prompt": "...",
    "context": {           ← 完整快照，随请求携带
      "recent_prompts": [],
      "available_targets": [],
      "domain": "dev",
      "locale": "zh-CN"
    }
  }
```

**理由**：
- v1 无状态依赖，部署零耦合，调用方自行拼装 context
- 不引入共享存储，避免 v1 多一个基础设施依赖
- context 体积可控（`recent_prompts` 上限 5 条，`available_targets` 上限 20 条），body 传输无压力

**v2 升级路径**：文档标注 `context` 字段未来可替换为引用 ID（`"context_ref": "ctx-abc123"`），由共享存储解析。v1 API 契约中 `context` 字段名保留，v2 加 `context_ref` 为可选替代，两者互斥。调用方无需改动。

---

### 2. 量化指标定义（H5）

**延迟指标**：

| 指标 | 定义 | 测量条件 |
|------|------|---------|
| 检测延迟 | `/v1/clarify` 请求到返回 | P95，空载（无并发），单条 prompt |
| 编译延迟 | `/v1/compile` 请求到返回 | P95，空载，单条 prompt |
| 端到端延迟 | 用户发出指令到拿到编译结果 | P95，含一次用户交互（不计用户思考时间） |

目标：检测 <30ms P95，编译 <20ms P95，端到端 <50ms P95（不含用户交互）。

**覆盖率指标**：

"60% 覆盖" 定义为：**在标注测试集上，规则引擎能检测到歧义并生成有效问题的比例**。

- **检测率** = 检测到歧义的样本数 / 测试集中含歧义的样本数
- **准确消歧率** = 生成的问题能准确指向歧义点的样本数 / 检测到歧义的样本数
- **覆盖率** = 准确消歧的样本数 / 测试集总数

目标：检测率 ≥75%，准确消歧率 ≥80%，综合覆盖率 ≥60%。

测试集构建方法见下方遗漏项 #1。

---

### 3. 日志 schema 对齐 v2（D6）

v1 执行结果日志字段设计与 v2 回流结构一致，避免 v2 重建成本。

**统一日志 schema（`ClarifyLogEntry`）**：

```json
{
  "timestamp": "2026-06-04T10:00:00Z",
  "request_id": "req-abc123",
  "original_prompt": "帮我更新软件",
  "mode": "must_clarify",
  "ambiguities_detected": [
    {
      "type": "target",
      "span": "软件",
      "confidence": 0.9,
      "reason": "动词'更新'+名词'软件'存在多种解读"
    }
  ],
  "questions_generated": [
    {
      "id": "q1",
      "text": "你说的软件是？",
      "options": ["系统包", "Python包", "特定应用"],
      "skipped": false
    }
  ],
  "answers": {"q1": "系统包"},
  "compiled_prompt": "更新系统所有已安装软件包到最新稳定版本...",
  "compile_confidence": 0.85,
  "skipped": false,
  "downstream_result": null,        // v2 回流时填写
  "feedback_signal": null            // v2 回流时填写（positive/negative）
}
```

v1 仅写入 `request_id` → `compiled_prompt` 段，`downstream_result` 和 `feedback_signal` 留 null。v2 回流机制上线后补填，无需改 schema。

---

### 4. 错误处理规范

**错误码体系**：

| 错误码 | HTTP Status | 触发条件 | 返回内容 | 下游行为 |
|--------|------------|---------|---------|---------|
| `RULE_MISS` | 200 | 规则库无匹配，无歧义可检测 | `{"mode": "pass", "ambiguities": [], "questions": []}` | 原样放行 |
| `CONTEXT_MISSING` | 422 | context 缺少必要字段（`domain`） | `{"error": "CONTEXT_MISSING", "detail": "field 'domain' is required"}` | 调用方补全 |
| `CONTEXT_INVALID` | 422 | context 字段值非法（如 `domain` 不在枚举内） | `{"error": "CONTEXT_INVALID", "detail": "..."}` | 调用方修正 |
| `TEMPLATE_BIND_ERROR` | 500 | 模板变量未绑定（规则命中但模板渲染失败） | `{"error": "TEMPLATE_BIND_ERROR", "detail": "...", "fallback": "pass"}` | 降级放行 |
| `RULE_EXEC_ERROR` | 500 | 规则引擎内部异常 | `{"error": "RULE_EXEC_ERROR", "detail": "...", "fallback": "pass"}` | 降级放行 |
| `COMPILE_NO_ANSWERS` | 422 | compile 调用未提供任何 answers | `{"error": "COMPILE_NO_ANSWERS", "detail": "..."}` | 调用方提供答案 |

**核心原则**：所有可恢复错误降级为放行（pass），不阻塞用户指令。不可恢复错误返回 422 让调用方修正。5xx 错误附带 `fallback: "pass"` 告知调用方可安全放行。

---

## 二、建议项回应（3项，不阻塞但采纳）

### C7：拒绝率指标补充

采纳。新增两个辅助指标：

| 指标 | 定义 | 用途 |
|------|------|------|
| 问题采纳率 | 用户选择选项（非跳过）的比例 | 衡量问题质量 |
| 级联消解命中率 | 回答 q1 后 q2 被自动消解的比例 | 验证级联消解设计有效性 |

### O2：compile 模板语法变量绑定规则

采纳。明确如下：

- 变量用 `{{var}}` 标记，与 Jinja2 / Mustache 兼容
- 必选变量（`{{original}}`, `{{answer_qN}}`）缺失时 → `TEMPLATE_BIND_ERROR`
- 可选变量（`{{context.domain}}` 等）缺失时 → 回退为空字符串
- 绑定优先级：answers > context > 规则默认值

### 里程碑拆分

采纳。v1 内部按 M1/M2 拆分：

- **M1**（核心通路）：规则引擎 + 歧义检测 + 模板系统 + `/v1/clarify` + `/v1/compile` + context schema + 错误处理
- **M2**（体验完善）：场景配置 + 级联消解 + 可解释性 + CLI 插件 + 日志写入 + 指标采集

M1 完成即可内部联调，M2 补齐生产就绪能力。

---

## 三、遗漏项补全

### 1. 测试集构建方法

**来源**：三方各自贡献 20 条模糊指令 → 标注歧义类型 + 期望问题 → 合并为 60 条初版测试集。

**标注规范**：
- 每条标注：`prompt`, `ambiguity_types[]`, `expected_question_text`, `expected_options[]`
- 交叉校验：每条至少两人确认标注一致
- 迭代：v1 开发中持续补充，目标 100 条

**覆盖率证明**：运行测试集，统计检测率/准确消歧率/覆盖率，输出报告。

### 2. 规则冷启动来源

"已知高频模糊指令"由三方共同定义：
- **Codex**：从开发/运维场景提取高频动词+名词组合（更新/部署/清理/优化+软件/服务/日志/性能）
- **Hermes**：从对话日志分析提取用户实际发出的模糊指令 Top 50
- **OpenClaw**：从 ops 场景 SRE playbook 提取危险模糊指令

合并去重后作为 v1 规则库种子，约 30-50 条规则。

### 3. 规则版本管理

- 规则库采用 **语义化版本**（`rule_version: "1.0.0"`）
- YAML 文件头部声明版本号
- 每次规则变更（新增/修改/删除）递增 patch 版本
- 新增歧义类型或变更 schema 递增 minor
- API 返回中附带 `rule_version` 字段，支持按版本查询规则快照
- 场景配置独立版本号，与规则库版本解耦

### 4. API 版本策略

**决策：URL path versioning**

- `/v1/clarify`，`/v1/compile`
- 不用 header versioning（v1 无需协商，简单直接）
- v2 上线时新增 `/v2/clarify`，v1 保持兼容至少 6 个月
- 重大 breaking change 递增 major 版本，minor/patch 在同一 major 内保持兼容

---

## 四、风险缓解

| 风险 | 等级 | 缓解措施 |
|------|------|---------|
| 规则膨胀 | 🔴 高 | v1 严格限制：每场景 ≤15 条规则，总规则 ≤50 条。超出时必须淘汰旧规则（拒绝率数据驱动）。规则库设硬上限，物理阻止膨胀 |
| 中文指代消解天花板 | 🟡 中 | v1 明确降级策略：无 `recent_prompts` 时指代类歧义标记为低置信度，不生成问题。v2 引入小模型时再突破 |
| 配置组合爆炸 | 🟡 中 | v1 只设 3 场景 × 5 歧义类型 = 15 个阈值位，不设交叉矩阵。场景配置模板化，每个场景一个 YAML 文件，相互独立 |

---

## 五、修订后 API 契约

### POST /v1/clarify

```json
// Request
{
  "prompt": "帮我更新软件",
  "context": {
    "recent_prompts": ["上个指令"],
    "available_targets": ["nginx", "python", "system"],
    "domain": "dev",
    "locale": "zh-CN"
  }
}

// Response — 有歧义
{
  "mode": "must_clarify",
  "ambiguities": [
    {
      "type": "target",
      "span": "软件",
      "confidence": 0.9,
      "reason": "动词'更新'+名词'软件'存在多种解读"
    }
  ],
  "questions": [
    {
      "id": "q1",
      "text": "你说的软件是？",
      "options": ["系统包", "Python包", "特定应用"],
      "allow_skip": true,
      "reason": "检测到目标歧义：'软件'指代不明"
    }
  ],
  "rule_version": "1.0.0"
}

// Response — 无歧义
{
  "mode": "pass",
  "ambiguities": [],
  "questions": [],
  "rule_version": "1.0.0"
}

// Response — 可静默消歧
{
  "mode": "silent_resolve",
  "ambiguities": [
    {"type": "format", "span": "分析数据", "confidence": 0.6, "reason": "..."}
  ],
  "resolution": {"format": "table"},
  "questions": [],
  "rule_version": "1.0.0"
}
```

### POST /v1/compile

```json
// Request
{
  "original": "帮我更新软件",
  "answers": {"q1": "系统包"},
  "context": { ... }
}

// Response
{
  "compiled_prompt": "更新系统所有已安装软件包到最新稳定版本...",
  "confidence": 0.85,
  "unresolved": [],
  "rule_version": "1.0.0"
}
```

### 错误响应

```json
{
  "error": "CONTEXT_MISSING",
  "detail": "field 'domain' is required in context",
  "fallback": null
}
```

```json
{
  "error": "TEMPLATE_BIND_ERROR",
  "detail": "variable 'answer_q1' not bound in template 'compile_target'",
  "fallback": "pass"
}
```

---

## 六、总结

| 修正项 | 状态 | 关键决策 |
|--------|------|---------|
| 数据流转路径 | ✅ 已决 | v1 HTTP body 快照，v2 可切共享存储 |
| 量化指标定义 | ✅ 已决 | P95/空载测延迟；检测率×准确消歧率=覆盖率 |
| 日志 schema 对齐 | ✅ 已决 | v1 即用 v2 schema，留空字段后填 |
| 错误处理规范 | ✅ 已决 | 6 个错误码，可恢复降级放行 |
| 测试集构建 | ✅ 已补 | 三方各 20 条，交叉校验，目标 100 条 |
| 规则冷启动 | ✅ 已补 | 三方各贡献来源，合并 30-50 条 |
| 规则版本管理 | ✅ 已补 | 语义化版本，API 附带 rule_version |
| API 版本策略 | ✅ 已补 | URL path versioning，v1/v2 并行 |

**4 项核心修正全部完成，请求进入开发阶段。**
