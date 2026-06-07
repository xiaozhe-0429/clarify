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
        self.domain: str = raw.get("domain", "general")
        self.scene: str = raw.get("scene", "general")
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

    # ── 匹配 ──────────────────────────────────────────

    def match(self, ctx: ClarifyContext) -> list[Rule]:
        """返回匹配 ctx.domain 的规则 (已排序)."""
        candidates = [
            r for r in self._rules
            if r.domain == ctx.domain.value
        ]
        return candidates

    # ── 级联消解 ──────────────────────────────────────

    MAX_CASCADE_ROUNDS = 2

    def _resolve_cascade(
        self,
        rules: list[Rule],
        previous_answers: Optional[list[dict[str, str]]],
        first_round_questions: Optional[set[str]] = None,
    ) -> list[Rule]:
        """根据 previous_answers 过滤已消解的规则.

        级联消解策略 (最多 MAX_CASCADE_ROUNDS 轮):
        - 第 1 轮: 正常匹配, 返回所有 must_clarify 问题.
        - 第 2 轮: 基于第 1 轮答案, 匹配 depends_on 指向已答问题的规则,
          且排除第 1 轮已问过的问题 (去重).
        - 不再支持第 3 轮.

        Args:
            rules: 候选规则列表 (第 1 轮返回的所有规则).
            previous_answers: [{question_id: answer}, ...] 来自前一轮.
            first_round_questions: 第 1 轮已生成的问题 ID 集合 (用于去重).

        Returns:
            过滤后的规则列表.
        """
        if not previous_answers:
            return rules

        # 计算级联轮次：每提交一次答案算一轮
        cascade_round = len(previous_answers)
        if cascade_round >= self.MAX_CASCADE_ROUNDS:
            return []  # 超过 2 轮, 不再追问

        answered_ids: set[str] = set()
        for entry in previous_answers:
            answered_ids.update(entry.keys())

        # 第一轮问题 ID (用于去重)
        first_round_ids = first_round_questions if first_round_questions else set()

        remaining: list[Rule] = []
        for rule in rules:
            # 排除第 1 轮已问过的问题 (去重)
            if rule.id in first_round_ids:
                continue
            # 该规则自身已被回答 → 跳过
            if rule.id in answered_ids:
                continue
            # 第 2 轮: 只返回依赖已回答问题的规则 (新规则),
            # 或者没有 depends_on 约束的规则
            # 如果没有 depends_on → 新规则, 加入
            # 如果 depends_on 且已回答 → 新规则, 加入
            # 如果 depends_on 但未回答 → 跳过
            if rule.depends_on and rule.depends_on not in answered_ids:
                continue
            remaining.append(rule)
        return remaining

    # ── 歧义检测 ──────────────────────────────────────

    def detect(self, ctx: ClarifyContext) -> ClarifyResponse:
        """执行歧义检测, 返回 ClarifyResponse.

        支持级联消解: 当 ctx.previous_answers 非空时,
        基于第 1 轮答案自动匹配第 2 轮相关歧义 (去重).
        """
        import uuid
        import time

        t0 = time.perf_counter()

        rules = self.match(ctx)
        is_cascade = bool(ctx.previous_answers)

        if not is_cascade:
            # 第一轮: 只返回 depends_on 为 None 的独立规则
            rules = [r for r in rules if r.depends_on is None]

        first_round_ids: Optional[set[str]] = None
        if is_cascade:
            # 第一轮问题的 ID 集合 = 所有同 domain 独立规则 (depends_on=None)
            first_round_ids = {r.id for r in rules if r.depends_on is None}
        rules = self._resolve_cascade(rules, ctx.previous_answers, first_round_ids)

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
