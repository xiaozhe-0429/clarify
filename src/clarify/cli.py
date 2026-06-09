"""Click CLI — 命令行入口."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
import uvicorn

from clarify.rules.engine import RuleEngine
from clarify.compile import TemplateCompiler
from clarify.models import ClarifyContext, Domain

# ── Scene → Domain 推导 ─────────────────────────────────
SCENE_DOMAIN_MAP: dict[str, str] = {
    "deploy": "ops",
    "monitor": "ops",
    "alert": "ops",
    "scale": "ops",
    "restart": "ops",
    "incident": "ops",
    "maintenance": "ops",
    "api_design": "dev",
    "data_model": "dev",
    "performance": "dev",
    "error_handling": "dev",
    "tech_stack": "dev",
    "refactor": "dev",
    "logging": "dev",
    "async": "dev",
    "translation": "general",
    "naming": "general",
    "format": "general",
    "documentation": "general",
    "project_setup": "general",
    "planning": "general",
}


def _derive_domain_from_scene(scene: str) -> tuple[str, str]:
    """Derive domain and clean scene from scene name.

    Returns (domain, cleaned_scene).
    """
    if not scene:
        return "general", ""

    # {domain}_{subscene} 格式, 例如 ops_deploy → (ops, deploy)
    if "_" in scene:
        prefix, suffix = scene.split("_", 1)
        if prefix in ("ops", "dev", "general"):
            return prefix, suffix

    # 硬编码映射表查找
    dom = SCENE_DOMAIN_MAP.get(scene, "general")
    return dom, scene


@click.group()
def cli() -> None:
    """Clarify v1 — 歧义检测与消解 CLI."""


@cli.command()
@click.option("--domain", default=None, help="业务域: ops / dev / general (未提供时从场景名推导)")
@click.option("--scene", default="", help="场景 (seed 规则库必填, 场景文件可选)")
@click.option("--question", required=True, help="待消歧问题")
@click.option("--language", default="zh")
@click.option("--rules", default=None, help="自定义规则 YAML 路径")
@click.option(
    "--scene-file",
    default=None,
    help="场景 YAML 文件路径 (scenarios/ops.yaml 等)",
)
@click.option(
    "--previous-answers",
    default=None,
    help='先前的澄清答案, JSON 格式: \'[{"q1":"answer1"}]\'',
)
def detect(
    domain: str | None,
    scene: str,
    question: str,
    language: str,
    rules: str | None,
    scene_file: str | None,
    previous_answers: str | None,
) -> None:
    """运行歧义检测并输出结果 (人类可读 + JSON)."""
    # ── 从场景名推导 domain ──────────────────────────
    if domain is None:
        derived_domain, derived_scene = _derive_domain_from_scene(scene)
        domain = derived_domain
        scene = derived_scene  # 例如 ops_deploy → 清洗为 deploy

    # 构建引擎
    if scene_file:
        engine = RuleEngine(Path(scene_file))
    elif rules:
        engine = RuleEngine(Path(rules))
    else:
        engine = RuleEngine()

    # 解析 previous_answers
    prev_answers = None
    if previous_answers:
        try:
            prev_answers = json.loads(previous_answers)
        except json.JSONDecodeError as exc:
            click.echo(f"错误: --previous-answers 不是合法 JSON: {exc}", err=True)
            sys.exit(1)

    # 映射 domain 字符串到 Domain 枚举
    domain_map = {"ops": Domain.OPS, "dev": Domain.DEV, "general": Domain.GENERAL}
    try:
        dom = domain_map[domain]
    except KeyError:
        click.echo(f"错误: 不支持的 domain '{domain}', 仅支持: {list(domain_map)}", err=True)
        sys.exit(1)

    ctx = ClarifyContext(
        domain=dom,
        locale=language,
        previous_answers=prev_answers,
    )
    result = engine.detect_sync(ctx, prompt=question)

    # ── 人类可读输出 ────────────────────────────────
    click.echo("=" * 60)
    click.echo("  歧义检测报告")
    click.echo("=" * 60)
    click.echo(f"  域:     {domain}")
    if scene:
        click.echo(f"  场景:   {scene}")
    click.echo(f"  模式:   {result.mode}")
    click.echo(f"  规则版本: {result.rule_version}")
    if prev_answers:
        click.echo(f"  级联轮次: {len(prev_answers)}")
    click.echo(f"  问题数: {len(result.questions)}")
    click.echo("-" * 60)

    if result.questions:
        for i, q in enumerate(result.questions, 1):
            click.echo(f"  [{i}] {q.id}")
            click.echo(f"      问题: {q.text}")
            click.echo(f"      原因: {q.reason}")
            if q.options:
                click.echo(f"      选项: {', '.join(q.options)}")
            click.echo("")
    else:
        click.echo("  ✓ 无需澄清, 可直接执行.")

    # ── JSON 输出 (机器可读) ────────────────────────
    click.echo("-" * 60)
    click.echo("JSON:")
    click.echo(result.model_dump_json(indent=2))


@cli.command()
@click.option("--template", default=None, help="模板名 (未指定时由 --domain/--scene 推导)")
@click.option("--domain", default=None, help="业务域: ops / dev / general (未提供时从场景名推导)")
@click.option("--scene", default="", help="场景名")
@click.option("--answers", multiple=True, help="key=value 形式, 例如 --answers lang=cn format=json")
@click.option("--vars", default="{}", help="JSON 变量字典 (与 --answers 互斥, 提供则忽略 --answers)")
def compile_cmd(
    template: str | None,
    domain: str | None,
    scene: str,
    answers: tuple[str, ...],
    vars: str,
) -> None:
    """编译模板并输出结果."""
    # ── 从 scene 推导 domain ────────────────────────
    if domain is None:
        domain, scene = _derive_domain_from_scene(scene)

    # ── 推导 template ──────────────────────────────
    if template is None:
        if domain and scene:
            template = f"{domain}/{scene}"
        elif domain:
            template = domain
        else:
            click.echo("错误: 必须提供 --template 或 --domain/--scene", err=True)
            sys.exit(1)

    # ── 解析变量 ──────────────────────────────────
    if vars != "{}":
        variables = json.loads(vars)
    elif answers:
        variables = {}
        for a in answers:
            if "=" not in a:
                click.echo(f"错误: --answers 格式错误 '{a}', 应为 key=value", err=True)
                sys.exit(1)
            k, v = a.split("=", 1)
            variables[k] = v
    else:
        variables = {}

    compiler = TemplateCompiler()
    rendered, missing = compiler.render(template, variables)
    click.echo(f"Rendered:\n{rendered}")
    if missing:
        click.echo(f"\nMissing vars: {missing}")


@cli.command()
@click.option("--host", default="0.0.0.0")
@click.option("--port", default=8000, type=int)
@click.option("--workers", default=1, type=int)
@click.option("--log-level", default="info")
def serve(host: str, port: int, workers: int, log_level: str) -> None:
    """启动 HTTP 服务."""
    uvicorn.run(
        "clarify.api:app",
        host=host,
        port=port,
        workers=workers,
        log_level=log_level,
    )


@cli.command()
def version() -> None:
    """输出版本信息."""
    engine = RuleEngine()
    click.echo(f"Clarify v1 — rules version: {engine.version}")


@cli.command()
@click.option("--path", default=None)
def stats(path: str | None) -> None:
    """输出规则库统计."""
    from pathlib import Path
    engine = RuleEngine(Path(path)) if path else RuleEngine()
    click.echo(f"Rules loaded: {engine.rule_count}")
    click.echo(f"Version: {engine.version}")


if __name__ == "__main__":
    cli()