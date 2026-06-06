"""规则引擎 — YAML 加载、匹配、歧义检测、级联消解."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Optional

import yaml

from clarify.models import ClarifyContext, ClarifyQuestion, ClarifyResponse


class Rule:
    """单条规则."""

    __slots__ = (
        "id", "domain", "scene", "priority", "mode",
        "question_template", "reason", "options",
        "depends_on", "condition",
    )

    def __init__(self, raw: dict) -> None:
        self.id: str = raw["id"]
        self.domain: str = raw["domain"]
        self.scene: str = raw["scene"]
        self.priority: int = raw.get("priority", 50)
        self.mode: str = raw.get("mode", "must_clarify")
        self.question_template: str = raw["question"]
        self.reason: str = raw.get("reason", "")
        self.options: Optional[list[str]] = raw.get("options")
        self.depends_on: Optional[str] = raw.get("depends_on")
        self.condition: Optional[str] = raw.get("condition")


class RuleEngine:
    """规则引擎 — 加载 YAML、匹配规则、级联消解.

    PRD 约束:
    - 规则库硬上限 50 条
    - 3 种模式: pass / silent_resolve / must_clarify
    - previous_answers 影响后续匹配 (级联消解)
    """

    MAX_RULES = 50

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

        if len(raw_rules) > self.MAX_RULES:
            raise ValueError(
                f"规则数量 {len(raw_rules)} 超过硬上限 {self.MAX_RULES}"
            )

        self._rules = [Rule(r) for r in raw_rules]
        # 按优先级降序
        self._rules.sort(key=lambda r: r.priority, reverse=True)

    @property
    def version(self) -> str:
        return self._version

    @property
    def rule_count(self) -> int:
        return len(self._rules)

    # ── 匹配 ──────────────────────────────────────────

    def match(self, ctx: ClarifyContext) -> list[Rule]:
        """返回匹配 ctx.domain 的规则 (已排序)."""
        candidates = [
            r for r in self._rules
            if r.domain == ctx.domain.value
        ]
        return candidates

    # ── 级联消解 ──────────────────────────────────────

    def _resolve_cascade(
        self, rules: list[Rule], previous_answers: Optional[list[dict[str, str]]]
    ) -> list[Rule]:
        """根据 previous_answers 过滤已消解的规则.

        规则: 如果某规则的 depends_on 指向的 question_id 已在
        previous_answers 中出现, 则该规则被消解 (移除).
        """
        if not previous_answers:
            return rules

        answered_ids = set()
        for entry in previous_answers:
            answered_ids.update(entry.keys())

        remaining: list[Rule] = []
        for rule in rules:
            if rule.depends_on and rule.depends_on in answered_ids:
                continue  # 级联消解
            remaining.append(rule)
        return remaining

    # ── 歧义检测 ──────────────────────────────────────

    def detect(self, ctx: ClarifyContext) -> ClarifyResponse:
        """执行歧义检测, 返回 ClarifyResponse."""
        import uuid
        import time

        t0 = time.perf_counter()

        rules = self.match(ctx)
        rules = self._resolve_cascade(rules, ctx.previous_answers)

        questions: list[ClarifyQuestion] = []
        mode = "pass"

        for rule in rules:
            if rule.mode == "must_clarify":
                mode = "must_clarify"
            elif rule.mode == "silent_resolve" and mode == "pass":
                mode = "silent_resolve"

            questions.append(ClarifyQuestion(
                id=rule.id,
                text=rule.question_template,
                reason=rule.reason,
                options=rule.options,
            ))

        latency = (time.perf_counter() - t0) * 1000

        return ClarifyResponse(
            mode=mode,
            questions=questions,
            rule_version=self._version,
            log_id=str(uuid.uuid4()),
        )
