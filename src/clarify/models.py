"""Clarify v1 数据模型 — 与 PRD 严格对齐."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


# ── 错误码 (PRD § 错误处理规范) ────────────────────────

class ErrorCode(str, Enum):
    """6 种标准错误码 — 与 PRD 严格对齐."""

    RULE_MISS = "RULE_MISS"                    # 200 — 规则库无匹配, 降级放行
    CONTEXT_MISSING = "CONTEXT_MISSING"         # 422 — context 必填字段缺失
    CONTEXT_INVALID = "CONTEXT_INVALID"         # 422 — context 字段值非法
    TEMPLATE_BIND_ERROR = "TEMPLATE_BIND_ERROR" # 500 — 必选变量缺失
    RULE_EXEC_ERROR = "RULE_EXEC_ERROR"         # 500 — 规则执行异常
    COMPILE_NO_ANSWERS = "COMPILE_NO_ANSWERS"   # 422 — compile 缺少 answers


# ── Context (PRD § 数据流转路径) ──────────────────────


class Domain(str, Enum):
    """业务域枚举 — 自动校验."""

    OPS = "ops"
    DEV = "dev"
    GENERAL = "general"


class ClarifyContext(BaseModel):
    """调用方拼装的 context 快照.

    PRD 要求:
    - recent_prompts: 最近 N 条用户指令 (用于指代消解)
    - available_targets: 可操作目标列表 (如 K8s 集群、数据库实例)
    - domain: 业务域 (ops / dev / general)
    - locale: 语言区域 (zh-CN / en-US)
    """

    recent_prompts: list[str] = Field(
        default_factory=list,
        description="最近 N 条用户指令, 用于指代消解",
    )
    available_targets: list[str] = Field(
        default_factory=list,
        description="可操作目标列表",
    )
    domain: Domain = Field(
        ..., description="业务域: ops / dev / general"
    )
    locale: str = Field(
        default="zh-CN", min_length=2, max_length=10, description="语言区域"
    )
    previous_answers: Optional[list[dict[str, str]]] = Field(
        default=None,
        description="先前已回答的澄清 [{question_id: answer}, ...]",
    )

    @model_validator(mode="after")
    def _truncate_fields(self) -> "ClarifyContext":
        """截断字段至硬上限."""
        self.recent_prompts = self.recent_prompts[-5:]
        self.available_targets = self.available_targets[:20]
        return self


# ── 请求 ───────────────────────────────────────────────

class ClarifyRequest(BaseModel):
    """/v1/clarify 请求体."""

    prompt: str = Field(..., min_length=1, description="待消歧的用户指令")
    context: ClarifyContext


# ── 响应 ───────────────────────────────────────────────

class ClarifyQuestion(BaseModel):
    """单个消歧问题."""

    id: str = Field(..., description="问题唯一 ID")
    text: str = Field(..., description="澄清问题文本")
    reason: str = Field(..., description="为什么需要澄清 (PRD 要求附带)")
    options: Optional[list[str]] = Field(
        default=None, description="可选答案列表"
    )


class ClarifyResponse(BaseModel):
    """/v1/clarify 响应体."""

    mode: str = Field(
        ..., description="pass | silent_resolve | must_clarify"
    )
    questions: list[ClarifyQuestion] = Field(
        default_factory=list, description="需要澄清的问题列表"
    )
    rule_version: str = Field(..., description="规则库版本号 (semver)")
    log_id: str = Field(..., description="请求追踪 ID")


# ── 日志 (PRD § 日志 schema 对齐 v2) ──────────────────

class ClarifyLogEntry(BaseModel):
    """结构化日志条目 — schema 与 v2 一致.

    downstream_result 和 feedback_signal 在 v1 留 null,
    v2 直接补填无需改 schema.
    """

    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 时间戳",
    )
    request_id: str = ""
    domain: str = ""
    locale: str = ""
    mode: str = ""
    latency_ms: float = 0.0
    rules_matched: int = 0
    questions_generated: int = 0
    downstream_result: Optional[str] = Field(
        default=None, description="v1 留 null, v2 补填"
    )
    feedback_signal: Optional[str] = Field(
        default=None, description="v1 留 null, v2 补填"
    )


# ── 编译 ───────────────────────────────────────────────

class CompileRequest(BaseModel):
    """/v1/compile 请求体.

    PRD: answers 绑定优先级 answers > context > 默认值.
    """

    template_name: str = Field(..., min_length=1)
    answers: dict[str, str] = Field(
        default_factory=dict,
        description="用户对澄清问题的回答",
    )
    context: Optional[ClarifyContext] = Field(
        default=None, description="可选的上下文快照, 作为变量 fallback"
    )


class CompileResponse(BaseModel):
    """/v1/compile 响应体."""

    rendered: str = Field(..., description="渲染后的精确指令")
    missing_vars: list[str] = Field(default_factory=list)
    log_id: str = ""
