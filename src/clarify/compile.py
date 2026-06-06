"""模板编译引擎 — Jinja2 渲染 + 变量管理."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, Template, Undefined, meta


class TemplateCompiler:
    """Jinja2 模板编译.

    PRD 要求:
    - 必选/可选变量管理
    - 缺失变量 fallback
    - 模板错误 → TEMPLATE_ERROR
    """

    def __init__(self, templates_dir: Optional[Path] = None) -> None:
        if templates_dir is None:
            templates_dir = Path(__file__).resolve().parent / "templates"
        self._env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            autoescape=False,
            undefined=Undefined,
        )

    def list_templates(self) -> list[str]:
        return self._env.list_templates()

    def get_required_vars(self, template_name: str) -> set[str]:
        """返回模板中的未定义变量 (必选)."""
        source = self._env.loader.get_source(self._env, template_name)[0]  # type: ignore[union-attr]
        ast = self._env.parse(source)
        return meta.find_undeclared_variables(ast)

    def render(
        self, template_name: str, variables: dict[str, str]
    ) -> tuple[str, list[str]]:
        """渲染模板, 返回 (rendered, missing_vars).

        missing_vars: 在模板中出现但 variables 中未提供的变量名.
        """
        required = self.get_required_vars(template_name)
        missing = [v for v in required if v not in variables]

        tmpl: Template = self._env.get_template(template_name)
        rendered = tmpl.render(**variables)
        return rendered, missing
