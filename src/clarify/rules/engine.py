"""规则引擎 — YAML 加载、pattern 匹配、i18n、级联消解."""

from __future__ import annotations

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

def _is_cjk(s: str) -> bool:
    """Check if string is composed entirely of CJK Unified Ideographs."""
    return bool(s) and all('\u4e00' <= c <= '\u9fff' or '\u3400' <= c <= '\u4dbf' for c in s)


def _is_short_cjk(pat: str) -> bool:
    """Check if pattern is a short CJK keyword (≤2 CJK chars) that needs boundary-aware matching."""
    cjk_count = sum(1 for c in pat if '\u4e00' <= c <= '\u9fff' or '\u3400' <= c <= '\u4dbf')
    return cjk_count > 0 and cjk_count <= 2 and len(pat) == cjk_count


def _match_short_cjk(pat: str, prompt: str) -> bool:
    """Match a short CJK keyword with boundary awareness.

    For 2-char CJK keywords, rejects matches where the keyword is a prefix
    fragment of a longer CJK compound word formed by a dangerous suffix.

    Dangerous suffixes (器/端/员/化/性) form semantically different compound
    words when appended to 2-char bases:
    - "服务" + "器" = "服务器" (server, NOT service)
    - "监控" + "器" = "监控器" (monitor device, NOT monitoring)

    Non-dangerous suffixes (了/太/满/新/扩 etc.) don't change the core meaning:
    - "部署" + "了" = "部署了" (still about deployment)
    - "磁盘" + "满" = "磁盘满" (still about disk)
    """
    import re
    pat_len = len(pat)
    cjk_pattern = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf]')
    # Suffixes that form semantically different compound words
    _dangerous_suffixes = frozenset({'器', '端', '员', '化', '性'})

    start = 0
    while True:
        idx = prompt.find(pat, start)
        if idx == -1:
            break
        # Check if followed by a dangerous suffix forming a different compound
        char_after = prompt[idx + pat_len] if idx + pat_len < len(prompt) else ''
        if char_after in _dangerous_suffixes:
            # Keyword is prefix of a different compound word → skip this occurrence
            start = idx + 1
            continue
        # Safe match
        return True

    return False


def _pattern_match(rule_raw: dict, prompt: str) -> bool:
    """检查 prompt 是否匹配规则的 patterns 列表.

    逻辑:
    - 优先读 patterns (复数), 兼容 pattern (单数, 场景文件)
    - 如果两者都没有 → 总是匹配 (向后兼容)
    - 如果 patterns 为空列表 → 总是匹配 (通配)
    - 否则: prompt 必须包含至少一个关键词
    - 短 CJK 关键词 (≤2 字符, 如 "服务") 使用边界感知匹配,
      避免子串误命中 (如 "服务" 不应匹配 "服务器")
    - 英文关键词使用简单子串匹配 (已有 \\b 边界效果)
    - exclude_patterns: 匹配 patterns 但命中排除词 → 不触发
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
    matched = False
    for pat in patterns:
        pat_lower = pat.lower()
        if _is_short_cjk(pat):
            # Short CJK: boundary-aware match (case-insensitive on the prompt side)
            if _match_short_cjk(pat, prompt):
                matched = True
                break
        else:
            # Non-CJK or longer CJK: simple substring match
            if pat_lower in prompt_lower:
                matched = True
                break

    if not matched:
        return False

    # exclude_patterns: 命中排除词则规则不触发
    exclude_patterns: list[str] = rule_raw.get("exclude_patterns", [])
    if exclude_patterns:
        for pat in exclude_patterns:
            if pat.lower() in prompt_lower:
                return False
    return True


# ── Rule ───────────────────────────────────────────────

class Rule:
    """单条规则 — 存储 raw dict 以便 i18n 动态取值."""

    __slots__ = (
        "id", "domain", "scene", "priority", "mode",
        "depends_on", "default_option", "_raw",
    )

    def __init__(self, raw: dict) -> None:
        self.id: str = raw["id"]
        self.domain: str = raw.get("domain", "general")
        self.scene: str = raw.get("scene", "general")
        self.priority: int = raw.get("priority", 50)
        self.mode: str = raw.get("mode", "must_clarify")
        self.depends_on: Optional[str] = raw.get("depends_on")
        self.default_option: Optional[str] = raw.get("default_option")
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

    MAX_RULES = 60
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

        # ── 收集已覆盖的规则 ID (用于 LLM fallback) ──
        covered_rule_ids: list[str] = [r.id for r in rules]

        # ── LLM Fallback ──────────────────────────
        if not questions and not is_cascade and prompt:
            # 极短（≤3字符）且无技术关键词的 prompt 跳过 LLM fallback
            skip_llm = False
            if len(prompt) <= 3:
                tech_keywords = [
                    "API", "HTTP", "JWT", "CI", "QA",
                ]
                if not any(kw in prompt for kw in tech_keywords):
                    skip_llm = True

            if not skip_llm:
                from clarify.llm_fallback import detect_with_llm
                llm_result = await detect_with_llm(prompt, ctx, covered_rule_ids=covered_rule_ids)
                if llm_result.questions:
                    questions = llm_result.questions
                    mode = "must_clarify"

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