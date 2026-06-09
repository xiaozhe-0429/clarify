"""Clarify Engine — FastAPI application."""

from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Optional

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from jinja2.exceptions import TemplateNotFound
from pydantic import ValidationError

from clarify.models import (
    ClarifyRequest,
    ClarifyResponse,
    CompileRequest,
    CompileResponse,
    ErrorCode,
    ClarifyContext,
)
from clarify.compile import TemplateCompiler
from clarify.rules.engine import RuleEngine
from clarify.metrics import (
    clarify_latency_seconds,
    compile_template_missing_vars_total,
    compile_template_success_total,
    errors_total,
    latency_histogram,
    requests_total,
    rules_matched,
    rules_matched_total,
    get_metrics,
)

logger = logging.getLogger("clarify.api")

# ── 全局 ──────────────────────────────────────────────

_engine: RuleEngine | None = None
_compiler: TemplateCompiler | None = None

VALID_DOMAINS = {"ops", "dev", "general"}


def get_engine() -> RuleEngine:
    global _engine
    if _engine is None:
        _engine = RuleEngine()
    return _engine


def get_compiler() -> TemplateCompiler:
    global _compiler
    if _compiler is None:
        _compiler = TemplateCompiler()
    return _compiler


app = FastAPI(
    title="Clarify Engine",
    description="AI prompt 歧义检测与消解服务",
    version="0.1.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 启动加载规则 ──────────────────────────────────────

@app.on_event("startup")
async def _on_startup() -> None:
    """服务启动时预热加载规则引擎和编译器."""
    engine = get_engine()
    compiler = get_compiler()
    logger.info("rules loaded count=%d", engine.rule_count)


# ── 场景 → domain 映射 (从 seed_rules.yaml 自动构建) ──

SCENE_DOMAIN_MAP: dict[str, str] = {
    # ops
    "deploy": "ops", "monitor": "ops", "alert": "ops",
    "scale": "ops", "restart": "ops", "incident": "ops",
    "maintenance": "ops",
    # dev
    "api_design": "dev", "data_model": "dev", "performance": "dev",
    "error_handling": "dev", "tech_stack": "dev", "refactor": "dev",
    "logging": "dev", "async": "dev",
    # general
    "translation": "general", "naming": "general", "format": "general",
    "documentation": "general", "project_setup": "general",
    "planning": "general",
}


def _derive_domain(scene: str) -> str:
    """从场景名推导 domain."""
    if not scene:
        return "general"
    # 检查是否有 domain_ 前缀
    for prefix in ("ops_", "dev_", "general_"):
        if scene.startswith(prefix):
            return prefix.rstrip("_")
    # 从映射表查找
    for s, d in SCENE_DOMAIN_MAP.items():
        if scene == s or scene.startswith(s + "_"):
            return d
    return "general"


# ── 错误码处理 ────────────────────────────────────────


def _error_response(code: ErrorCode, detail: str, status: int) -> JSONResponse:
    logger.warning("error_response", code=code.value, detail=detail)
    errors_total.labels(error_code=code.value).inc()
    return JSONResponse(
        status_code=status,
        content={"error": code.value, "detail": detail},
    )


def _validate_context(ctx: ClarifyContext) -> JSONResponse | None:
    """校验 domain, 返回 None 表示通过."""
    if ctx.domain is None or ctx.domain.value == "":
        return _error_response(ErrorCode.DOMAIN_MISSING, "domain is required", 422)
    if ctx.domain.value not in VALID_DOMAINS:
        return _error_response(
            ErrorCode.DOMAIN_INVALID,
            f"domain '{ctx.domain.value}' not in {VALID_DOMAINS}",
            422,
        )
    return None


# ── Routes ────────────────────────────────────────────


@app.post("/v1/clarify", response_model=ClarifyResponse)
async def clarify(req: ClarifyRequest) -> ClarifyResponse | JSONResponse:
    """歧义检测 — POST /v1/clarify."""
    t0 = time.perf_counter()

    ctx = req.context
    err = _validate_context(ctx)
    if err:
        return err

    # ── 上下文截断 (M1-3b) ────────────────────────
    if ctx.recent_prompts is not None and len(ctx.recent_prompts) > 5:
        logger.info(
            "context_truncated",
            field="recent_prompts",
            before=len(ctx.recent_prompts),
            after=5,
        )
        ctx.recent_prompts = ctx.recent_prompts[-5:]

    if ctx.available_targets is not None and len(ctx.available_targets) > 20:
        logger.info(
            "context_truncated",
            field="available_targets",
            before=len(ctx.available_targets),
            after=20,
        )
        ctx.available_targets = ctx.available_targets[:20]

    engine = get_engine()
    result = await engine.detect(ctx, prompt=req.prompt)

    latency = (time.perf_counter() - t0) * 1000

    # 指标
    scene = ctx.scene or "unknown"
    domain = ctx.domain.value
    requests_total.labels(
        domain=domain, scene=scene, mode=result.mode
    ).inc()
    latency_histogram.labels(domain=domain, scene=scene).observe(latency)
    rules_matched.observe(len(result.questions))

    # M2-1: latency_seconds (秒级)
    clarify_latency_seconds.labels(domain=domain, scene=scene).observe(
        latency / 1000.0
    )

    # M2-1: rules_matched_total — 用 question id 作为 rule_name
    for q in result.questions:
        rule_name = q.id
        rules_matched_total.labels(
            rule_name=rule_name, domain=domain, matched="true"
        ).inc()

    # 结构化日志
    logger.info(
        "clarify_completed",
        request_id=result.log_id,
        domain=domain,
        scene=scene,
        mode=result.mode,
        latency_ms=round(latency, 2),
        rules_matched=len(result.questions),
    )

    return result


# ── Bucket helper ─────────────────────────────────────

_MISSING_BUCKET_MAP = {0, 1, 2, 3, 4}


def _missing_bucket(n: int) -> str:
    """将缺失变量数映射到 bucket 标签."""
    if n <= 4:
        return str(n)
    return "5+"


@app.post("/v1/compile", response_model=CompileResponse)
async def compile_template(req: CompileRequest) -> CompileResponse | JSONResponse:
    """模板编译 — POST /v1/compile."""
    compiler = get_compiler()

    # 如果 template_name 为空, 从 context.domain + context.scene 推导
    template_name = req.template_name
    if not template_name and req.context:
        domain_val = (
            req.context.domain.value
            if hasattr(req.context.domain, "value")
            else str(req.context.domain)
        )
        scene = req.context.scene or "general"
        template_name = f"{domain_val}.{scene}"
    if not template_name:
        return _error_response(
            ErrorCode.TEMPLATE_ERROR,
            "template_name is required and could not be derived from context",
            422,
        )

    try:
        rendered, missing = compiler.render(template_name, req.answers or {})
    except TemplateNotFound:
        compile_template_success_total.labels(
            template_name=template_name, status="failure"
        ).inc()
        return _error_response(
            ErrorCode.TEMPLATE_BIND_ERROR,
            f"Template '{template_name}' not found",
            500,
        )
    except Exception as exc:
        compile_template_success_total.labels(
            template_name=template_name, status="failure"
        ).inc()
        return _error_response(
            ErrorCode.TEMPLATE_ERROR,
            f"Template compile failed: {exc}",
            500,
        )

    # 成功路径
    compile_template_success_total.labels(
        template_name=template_name, status="success"
    ).inc()

    # 缺失变量桶
    bucket = _missing_bucket(len(missing))
    compile_template_missing_vars_total.labels(
        template_name=template_name, count_bucket=bucket
    ).inc()

    return CompileResponse(
        rendered=rendered,
        missing_vars=missing,
        original=req.original,
        log_id=str(uuid.uuid4()),
    )


@app.get("/metrics")
async def metrics() -> Response:
    """Prometheus 指标端点."""
    return Response(content=get_metrics(), media_type="text/plain")


@app.get("/v1/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": get_engine().version}


# ── Rules (M1-3d) ─────────────────────────────────


@app.get("/v1/rules")
async def list_rules() -> dict:
    """返回所有规则列表 — GET /v1/rules."""
    engine = get_engine()
    rules = engine.list_rules()
    return {"total": len(rules), "rules": rules}


# ── 全局异常处理 ──────────────────────────────────────


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("unhandled_error", error=str(exc))
    return _error_response(ErrorCode.INTERNAL_ERROR, str(exc), 500)


@app.exception_handler(ValidationError)
async def validation_exception_handler(
    request: Request, exc: ValidationError
) -> JSONResponse:
    return _error_response(ErrorCode.DOMAIN_MISSING, str(exc), 422)
