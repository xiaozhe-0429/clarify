"""LLM Fallback — 规则引擎无匹配时，调 LLM 生成澄清问题."""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

from clarify.models import ClarifyContext, ClarifyQuestion

# ── 配置 (环境变量) ────────────────────────────────────

LLM_ENABLED = os.getenv("CLARIFY_LLM_ENABLED", "true").lower() in ("1", "true", "yes")
LLM_BASE_URL = os.getenv("CLARIFY_LLM_BASE_URL", "https://maas-coding-api.cn-huabei-1.xf-yun.com/v2")
LLM_API_KEY = os.getenv("CLARIFY_LLM_API_KEY", os.getenv("OPENAI_API_KEY", ""))
LLM_MODEL = os.getenv("CLARIFY_LLM_MODEL", "astron-code-latest")
LLM_TIMEOUT = float(os.getenv("CLARIFY_LLM_TIMEOUT", "15"))
LLM_MAX_TOKENS = int(os.getenv("CLARIFY_LLM_MAX_TOKENS", "512"))

# ── System Prompt ──────────────────────────────────────

SYSTEM_PROMPT = """You are an ambiguity detector for AI instructions. Your job: given a user's prompt, identify what's ambiguous or underspecified, and generate structured clarification questions.

Rules:
1. Only flag REAL ambiguities — things that would lead to wrong or unsafe actions if guessed.
2. Be concise. Each question must be answerable with a short choice.
3. Provide 2-5 options per question (when applicable).
4. If the prompt is already clear and complete, return an empty list.
5. Output ONLY valid JSON, no markdown, no explanation.

Output schema:
{
  "questions": [
    {
      "id": "llm_001",
      "text": "Which environment?",
      "reason": "Deploying to wrong environment is irreversible",
      "options": ["production", "staging", "development"]
    }
  ]
}

For each question:
- id: unique string, prefixed with "llm_"
- text: the clarification question (in the user's language)
- reason: why this needs clarification (one sentence)
- options: array of possible answers, or empty array if open-ended

Respond in the SAME LANGUAGE as the user's prompt."""


@dataclass
class LLMFallbackResult:
    """LLM 生成的澄清结果."""

    questions: list[ClarifyQuestion] = field(default_factory=list)
    model: str = ""
    latency_ms: float = 0.0
    error: Optional[str] = None


def _build_user_prompt(prompt: str, ctx: ClarifyContext) -> str:
    """构造发给 LLM 的 user message."""
    domain = ctx.domain.value if hasattr(ctx.domain, "value") else str(ctx.domain)
    parts = [
        f"Domain: {domain}",
        f"User prompt: {prompt}",
    ]
    if ctx.recent_prompts:
        parts.append(f"Recent prompts: {', '.join(ctx.recent_prompts[-3:])}")
    if ctx.available_targets:
        parts.append(f"Available targets: {', '.join(ctx.available_targets[:10])}")
    return "\n".join(parts)


def _parse_llm_response(text: str) -> list[ClarifyQuestion]:
    """从 LLM 返回的文本中提取 JSON 并解析为 ClarifyQuestion 列表."""
    # 尝试直接解析
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # 尝试提取 JSON 块 (```json ... ``` 或 { ... })
        match = re.search(r'\{[\s\S]*"questions"[\s\S]*\}', text)
        if not match:
            return []
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return []

    raw_questions = data.get("questions", [])
    if not isinstance(raw_questions, list):
        return []

    result: list[ClarifyQuestion] = []
    for i, q in enumerate(raw_questions):
        if not isinstance(q, dict):
            continue
        qid = q.get("id", f"llm_{i:03d}")
        text = q.get("text", "")
        reason = q.get("reason", "")
        options = q.get("options", [])
        if not text:
            continue
        result.append(ClarifyQuestion(
            id=str(qid),
            text=str(text),
            reason=str(reason),
            options=[str(o) for o in options] if options else None,
        ))
    return result


async def detect_with_llm(
    prompt: str,
    ctx: ClarifyContext,
    *,
    model: Optional[str] = None,
) -> LLMFallbackResult:
    """调 LLM 检测歧义并生成澄清问题.

    Args:
        prompt: 用户原始指令.
        ctx: 上下文 (domain, locale, recent_prompts 等).
        model: 模型名, None 则用环境变量默认值.

    Returns:
        LLMFallbackResult (questions, model, latency_ms, error).
    """
    if not LLM_ENABLED:
        return LLMFallbackResult(error="LLM fallback disabled (CLARIFY_LLM_ENABLED=false)")

    if not LLM_API_KEY:
        return LLMFallbackResult(error="No API key configured (CLARIFY_LLM_API_KEY)")

    t0 = time.perf_counter()
    used_model = model or LLM_MODEL

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _build_user_prompt(prompt, ctx)},
    ]

    url = f"{LLM_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": used_model,
        "messages": messages,
        "max_tokens": LLM_MAX_TOKENS,
        "temperature": 0.1,  # 低温度 → 确定性输出
    }

    try:
        async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
            resp = await client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except httpx.TimeoutException:
        return LLMFallbackResult(
            model=used_model,
            latency_ms=(time.perf_counter() - t0) * 1000,
            error=f"LLM timeout after {LLM_TIMEOUT}s",
        )
    except Exception as exc:
        return LLMFallbackResult(
            model=used_model,
            latency_ms=(time.perf_counter() - t0) * 1000,
            error=f"LLM call failed: {exc}",
        )

    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    questions = _parse_llm_response(content)
    latency = (time.perf_counter() - t0) * 1000

    return LLMFallbackResult(
        questions=questions,
        model=used_model,
        latency_ms=latency,
    )


def detect_with_llm_sync(
    prompt: str,
    ctx: ClarifyContext,
    *,
    model: Optional[str] = None,
) -> LLMFallbackResult:
    """同步版本 — 用于非 async 环境 (如 CLI)."""
    import asyncio
    return asyncio.run(detect_with_llm(prompt, ctx, model=model))
