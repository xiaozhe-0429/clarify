"""规则引擎 — YAML 加载、pattern 匹配、i18n、级联消解."""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Optional

import yaml

from clarify.models import ClarifyContext, ClarifyQuestion, ClarifyResponse


# ── i18n: 语言判断 ────────────────────────────────────

def _is_chinese_locale(locale: str) -> bool:
    """locale 是否中文 (zh-CN, zh-TW, zh, zh-Hans 等)."""
    return locale.lower().startswith("zh")


def _i18n(rule_raw: dict, locale: str, field: str) -> str | list[str] | None:
    """从规则 raw dict 取字段, 优先 en 子段, 否则 fallback 到顶层 (中文).

    顶层字段 == 中文 (向后兼容, 不破坏已有数据).
    """
    if not _is_chinese_locale(locale):
        en = rule_raw.get("en", {})
        if field in en:
            val = en[field]
            # list 类型直接返回
            if isinstance(val, list):
                return val if val else None
            # str 类型: 非空才用
            if isinstance(val, str) and val:
                return val
    # fallback: 顶层 (中文)
    val = rule_raw.get(field)
    if isinstance(val, list):
        return val if val else None
    if isinstance(val, str) and val:
        return val
    return None


# ── Pattern 匹配 ───────────────────────────────────────

def _pattern_match(rule_raw: dict, prompt: str) -> bool:
    """检查 prompt 是否匹配规则的 patterns 列表.

    逻辑:
    - 优先读 patterns (复数), 兼容 pattern (单数, 场景文件)
    - 如果两者都没有 → 总是匹配 (向后兼容)
    - 如果 patterns 为空列表 → 总是匹配 (通配)
    - 否则: prompt 必须包含至少一个关键词
    """
    patterns: list[str] = rule_raw.get("patterns", [])
    # 兼容场景文件的 pattern (单数)
    if not patterns:
        single = rule_raw.get("pattern", "")
        if single:
            patterns = [single]
    if not patterns:
        return True  # 无 patterns = 该规则无条件触发

    prompt_lower = prompt.lower()
    for pat in patterns:
        if pat.lower() in prompt_lower:
            return True
    return False


# ── Rule ───────────────────────────────────────────────

class Rule:
    """单条规则 — 存储 raw dict 以便 i18n 动态取值."""

    __slots__ = (
        "id", "domain", "scene", "priority", "mode",
        "depends_on", "_raw",
    )

    def __init__(self, raw: dict) -> None:
        self.id: str = raw["id"]
        self.domain: str = raw.get("domain", "general")
        self.scene: str = raw.get("scene", "general")
        self.priority: int = raw.get("priority", 50)
        self.mode: str = raw.get("mode", "must_clarify")
        self.depends_on: Optional[str] = raw.get("depends_on")
        self._raw = raw  # 保留完整 raw, i18n 时用

    def i18n_question(self, locale: str) -> str:
        return _i18n(self._raw, locale, "question") or ""

    def i18n_reason(self, locale: str) -> str:
        return _i18n(self._raw, locale, "reason") or ""

    def i18n_options(self, locale: str) -> Optional[list[str]]:
        return _i18n(self._raw, locale, "options")  # type: ignore[return-value]

    def matches_prompt(self, prompt: str) -> bool:
        return _pattern_match(self._raw, prompt)


# ── Engine ─────────────────────────────────────────────

class RuleEngine:
    """规则引擎 — 加载 YAML、pattern 匹配、i18n、级联消解.

    PRD 约束:
    - 规则库硬上限 50 条
    - 3 种模式: pass / silent_resolve / must_clarify
    - pattern 匹配: 按 prompt 关键词过滤规则
    - i18n: 按 locale 返回中文/英文 question/reason/options
    - previous_answers 影响后续匹配 (级联消解)
    """

    MAX_RULES = 50
    MAX_CASCADE_ROUNDS = 2

    def __init__(self, rules_path: Optional[Path] = None) -> None:
        self._rules: list[Rule] = []
        self._version: str = "0.0.0"
        if rules_path is None:
            rules_path = Path(__file__).resolve().parent / "seed_rules.yaml"
        self.load(rules_path)

    # ── 加载 ──────────────────────────────────────────

    def load(self, path: Path) -> None:
        """从 YAML 加载规则库."""
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)

        self._version = data.get("version", "0.0.0")
        raw_rules = data.get("rules", [])
        file_domain = data.get("domain", "")

        if len(raw_rules) > self.MAX_RULES:
            raise ValueError(
                f"规则数量 {len(raw_rules)} 超过硬上限 {self.MAX_RULES}"
            )

        self._rules = []
        for r in raw_rules:
            # 场景 YAML: 文件级 domain 注入到没 domain 字段的规则
            if file_domain and "domain" not in r:
                r["domain"] = file_domain
            self._rules.append(Rule(r))
        # 按优先级降序
        self._rules.sort(key=lambda r: r.priority, reverse=True)

    @property
    def version(self) -> str:
        return self._version

    @property
    def rule_count(self) -> int:
        return len(self._rules)

    def list_rules(self) -> list[dict]:
        """返回所有规则的摘要列表 (id, name, domain, enabled)."""
        rules_summary = []
        for r in self._rules:
            raw = r._raw or {}
            rule_name = raw.get("name") or raw.get("question", r.id)[:64]
            rules_summary.append({
                "id": r.id,
                "name": rule_name,
                "domain": r.domain,
                "enabled": r.priority > 0,
            })
        return rules_summary

    # ── 匹配 ──────────────────────────────────────────

    def match(self, ctx: ClarifyContext, prompt: str = "") -> list[Rule]:
        """返回匹配 ctx.domain 且 pattern 匹配 prompt 的规则 (已排序)."""
        domain_val = ctx.domain.value if hasattr(ctx.domain, "value") else str(ctx.domain)
        candidates = [
            r for r in self._rules
            if r.domain == domain_val and r.matches_prompt(prompt)
        ]
        return candidates

    # ── 级联消解 ──────────────────────────────────────

    def _resolve_cascade(
        self,
        rules: list[Rule],
        previous_answers: Optional[list[dict[str, str]]],
        first_round_questions: Optional[set[str]] = None,
    ) -> list[Rule]:
        """根据 previous_answers 过滤已消解的规则."""
        if not previous_answers:
            return rules

        cascade_round = len(previous_answers)
        if cascade_round >= self.MAX_CASCADE_ROUNDS:
            return []

        answered_ids: set[str] = set()
        for entry in previous_answers:
            answered_ids.update(entry.keys())

        first_round_ids = first_round_questions if first_round_questions else set()

        remaining: list[Rule] = []
        for rule in rules:
            if rule.id in first_round_ids:
                continue
            if rule.id in answered_ids:
                continue
            if rule.depends_on and rule.depends_on not in answered_ids:
                continue
            remaining.append(rule)
        return remaining

    # ── 歧义检测 ──────────────────────────────────────

    async def detect(self, ctx: ClarifyContext, prompt: str = "") -> ClarifyResponse:
        """执行歧义检测, 返回 ClarifyResponse.

        Args:
            ctx: 上下文 (domain, scene, locale, previous_answers 等).
            prompt: 用户原始指令, 用于 pattern 匹配.

        流程:
        1. 规则引擎 pattern 匹配 → 命中直接返回
        2. 规则空 + 非级联轮次 → LLM fallback 生成澄清问题
        3. 级联消解: previous_answers 非空时自动匹配下一轮
        """
        import uuid
        import time

        t0 = time.perf_counter()

        rules = self.match(ctx, prompt=prompt)
        locale = ctx.locale if ctx.locale else "zh-CN"
        is_cascade = bool(ctx.previous_answers)

        if not is_cascade:
            rules = [r for r in rules if r.depends_on is None]

        first_round_ids: Optional[set[str]] = None
        if is_cascade:
            first_round_ids = {r.id for r in rules if r.depends_on is None}
        rules = self._resolve_cascade(rules, ctx.previous_answers, first_round_ids)

        questions: list[ClarifyQuestion] = []
        mode = "pass"

        # ── 规则命中 ──────────────────────────────
        for rule in rules:
            q_text = rule.i18n_question(locale)
            q_reason = rule.i18n_reason(locale)
            q_options = rule.i18n_options(locale)

            if rule.mode == "must_clarify":
                mode = "must_clarify"
            elif rule.mode == "silent_resolve" and mode == "pass":
                mode = "silent_resolve"

            questions.append(ClarifyQuestion(
                id=rule.id,
                text=q_text,
                reason=q_reason,
                options=q_options,
            ))

        # ── LLM Fallback ──────────────────────────
        if not questions and not is_cascade and prompt:
            from clarify.llm_fallback import detect_with_llm
            llm_result = await detect_with_llm(prompt, ctx)
            if llm_result.questions:
                questions = llm_result.questions
                mode = "must_clarify"

        latency = (time.perf_counter() - t0) * 1000

        return ClarifyResponse(
            mode=mode,
            questions=questions,
            rule_version=self._version,
            log_id=str(uuid.uuid4()),
        )

    def detect_sync(self, ctx: ClarifyContext, prompt: str = "") -> ClarifyResponse:
        """同步版本 — 用于 CLI 等非 async 环境."""
        import asyncio
        return asyncio.run(self.detect(ctx, prompt=prompt))