"""Click CLI — 命令行入口."""

from __future__ import annotations

import json
import sys

import click
import uvicorn

from clarify.rules.engine import RuleEngine
from clarify.compile import TemplateCompiler
from clarify.models import ClarifyContext, ClarifyRequest


@click.group()
def cli() -> None:
    """Clarify v1 — 歧义检测与消解 CLI."""


@cli.command()
@click.option("--domain", required=True, help="业务域: ops / dev / general")
@click.option("--scene", required=True, help="场景")
@click.option("--question", required=True, help="待消歧问题")
@click.option("--language", default="zh")
@click.option("--rules", default=None, help="自定义规则 YAML 路径")
def detect(domain: str, scene: str, question: str, language: str, rules: str | None) -> None:
    """运行歧义检测并输出 JSON."""
    from pathlib import Path

    engine = RuleEngine(Path(rules)) if rules else RuleEngine()
    ctx = ClarifyContext(domain=domain, scene=scene, question=question, language=language)
    result = engine.detect(ctx)
    click.echo(result.model_dump_json(indent=2))


@cli.command()
@click.option("--template", required=True, help="模板名")
@click.option("--vars", default="{}", help="JSON 变量字典")
def compile_cmd(template: str, vars: str) -> None:
    """编译模板并输出结果."""
    compiler = TemplateCompiler()
    variables = json.loads(vars)
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
