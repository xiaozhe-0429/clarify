"""FastAPI 路由 — /v1/clarify + /v1/compile + 指标端点."""

from __future__ import annotations

import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from clarify.compile import TemplateCompiler
from clarify.logging import get_logger, setup_logging
from clarify.metrics import (
    errors_total,
    latency_histogram,
    requests_total,
    rules_matched,
    get_metrics,
)
from clarify.models import (
    ClarifyContext,
    ClarifyRequest,
    ClarifyResponse,
    CompileRequest,
    CompileResponse,
    ErrorCode,
)
from clarify.rules.engine import RuleEngine

logger = get_logger()

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


# ── App ───────────────────────────────────────────────

app = FastAPI(
    title="Clarify v1",
    version="0.1.0",
    docs_url="/v1/docs",
    openapi_url="/v1/openapi.json",
)


@app.on_event("startup")
async def startup() -> None:
    setup_logging()
    get_engine()   # 预热加载
    get_compiler()
    logger.info("clarify_started")


# ── 错误码处理 ────────────────────────────────────────

def _error_response(code: ErrorCode, detail: str, status: int) -> JSONResponse:
    logger.warning("error_response", code=code.value, detail=detail)
    errors_total.labels(error_code=code.value).inc()
    return JSONResponse(
        status_code=status,
        content={"error": code.value, "detail": detail},
    )


def _validate_context(ctx: ClarifyContext) -> JSONResponse | None:
    """校验 domain/scene, 返回 None 表示通过."""
    if not ctx.domain:
        return _error_response(ErrorCode.DOMAIN_MISSING, "domain is required", 422)
    if ctx.domain not in VALID_DOMAINS:
        return _error_response(
            ErrorCode.DOMAIN_INVALID,
            f"domain '{ctx.domain}' not in {VALID_DOMAINS}",
            422,
        )
    if not ctx.scene:
        return _error_response(ErrorCode.SCENE_MISSING, "scene is required", 422)
    # scene 有效性由规则引擎匹配结果决定 — 无匹配时仍返回 pass (降级放行)
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

    engine = get_engine()
    result = engine.detect(ctx)

    latency = (time.perf_counter() - t0) * 1000

    # 指标
    requests_total.labels(
        domain=ctx.domain, scene=ctx.scene, mode=result.mode
    ).inc()
    latency_histogram.labels(domain=ctx.domain, scene=ctx.scene).observe(latency)
    rules_matched.observe(len(result.questions))

    # 结构化日志
    logger.info(
        "clarify_completed",
        request_id=result.log_id,
        domain=ctx.domain,
        scene=ctx.scene,
        mode=result.mode,
        latency_ms=round(latency, 2),
        rules_matched=len(result.questions),
    )

    return result


@app.post("/v1/compile", response_model=CompileResponse)
async def compile_template(req: CompileRequest) -> CompileResponse | JSONResponse:
    """模板编译 — POST /v1/compile."""
    import uuid

    compiler = get_compiler()
    try:
        rendered, missing = compiler.render(req.template_name, req.variables)
    except Exception as exc:
        return _error_response(
            ErrorCode.TEMPLATE_ERROR,
            f"Template compile failed: {exc}",
            500,
        )

    return CompileResponse(
        rendered=rendered,
        missing_vars=missing,
        log_id=str(uuid.uuid4()),
    )


@app.get("/v1/metrics")
async def metrics() -> Response:
    """Prometheus 指标端点."""
    return Response(content=get_metrics(), media_type="text/plain")


@app.get("/v1/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": get_engine().version}


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