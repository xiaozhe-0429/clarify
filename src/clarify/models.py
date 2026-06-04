"""Clarify v1 数据模型 — 遵循 PRD 定义的请求/响应结构."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ── 错误码 ──────────────────────────────────────────────

class ErrorCode(str, Enum):
    """6 种标准错误码."""

    DOMAIN_MISSING = "DOMAIN_MISSING"        # 422 — domain 缺失
    DOMAIN_INVALID = "DOMAIN_INVALID"        # 422 — domain 不在规则库中
    SCENE_MISSING = "SCENE_MISSING"          # 422 — scene 缺失
    SCENE_INVALID = "SCENE_INVALID"          # 422 — scene 不在规则库中
    TEMPLATE_ERROR = "TEMPLATE_ERROR"        # 500 — 模板编译失败
    INTERNAL_ERROR = "INTERNAL_ERROR"        # 500 — 内部异常


# ── 领域模型 ────────────────────────────────────────────

class ClarifyContext(BaseModel):
    """用户输入上下文.

    PRD 要求: domain + scene 决定规则命中范围;
    previous_answers 支撑级联消解.
    """

    domain: str = Field(
        ..., min_length=1, description="业务域: ops / dev / general"
    )
    scene: str = Field(
        ..., min_length=1, description="场景: 如 deploy, alert, api_design 等"
    )
    language: str = Field(
        default="zh", min_length=2, max_length=5, description="提问语言代码"
    )
    question: str = Field(
        ..., min_length=1, description="待消歧的原始问题"
    )
    user_context: Optional[str] = Field(
        default=None, description="可选的用户环境/角色信息"
    )
    previous_answers: Optional[list[dict[str, str]]] = Field(
        default=None,
        description="先前已回答的澄清 [{question_id: answer}, ...]",
    )


class PromptOption(BaseModel):
    """编译 prompt 模板时的选项."""

    mode: str = Field(default="standard", description="输出风格")
    max_length: Optional[int] = Field(default=None, ge=1, le=8000)
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)


class ClarifyRequest(BaseModel):
    """/v1/clarify 请求体."""

    context: ClarifyContext
    prompt: Optional[str] = Field(default=None, description="可选 prompt 模板名")
    options: Optional[PromptOption] = None


# ── 响应模型 ────────────────────────────────────────────

class ClarifyQuestion(BaseModel):
    """单个消歧问题."""

    id: str = Field(..., description="问题唯一 ID, 如 q1")
    text: str = Field(..., description="澄清问题文本")
    reason: str = Field(
        ..., description="为什么需要澄清 (PRD 要求附带)"
    )
    options: Optional[list[str]] = Field(
        default=None, description="可选答案列表"
    )


class ClarifyResponse(BaseModel):
    """/v1/clarify 响应体."""

    mode: str = Field(
        ...,
        description="pass | silent_resolve | must_clarify",
    )
    questions: list[ClarifyQuestion] = Field(
        default_factory=list, description="需要澄清的问题列表"
    )
    rule_version: str = Field(
        ..., description="规则库版本号 (semver)"
    )
    log_id: str = Field(
        ..., description="请求追踪 ID"
    )


# ── 日志 ────────────────────────────────────────────────

class ClarifyLogEntry(BaseModel):
    """结构化日志条目."""

    timestamp: str = Field(..., description="ISO 8601 时间戳")
    request_id: str
    domain: str
    scene: str
    mode: str
    latency_ms: float
    rules_matched: int = Field(default=0)


# ── 编译 ────────────────────────────────────────────────

class CompileRequest(BaseModel):
    """/v1/compile 请求体."""

    template_name: str = Field(..., min_length=1)
    variables: dict[str, str] = Field(default_factory=dict)
    options: Optional[PromptOption] = None


class CompileResponse(BaseModel):
    """/v1/compile 响应体."""

    rendered: str = Field(..., description="渲染后的 prompt")
    missing_vars: list[str] = Field(default_factory=list)
    log_id: str