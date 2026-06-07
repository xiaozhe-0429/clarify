"""结构化日志配置 — structlog + optional JSON output."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

import structlog


class JsonFormatter(logging.Formatter):
    """JSON 格式的 logging Formatter.

    输出: {"timestamp": "...", "level": "...", "message": "...", **extra}
    """

    def format(self, record: logging.LogRecord) -> str:
        extra = {}
        # 收集 record.__dict__ 中的额外字段 (structlog 传入的 kwarg)
        for key, value in record.__dict__.items():
            if key not in (
                "name", "msg", "args", "levelname", "levelno",
                "pathname", "filename", "module", "lineno", "funcName",
                "created", "relativeCreated", "exc_info", "exc_text",
                "stack_info", "lineno", "thread", "threadName",
                "process", "processName", "message", "taskName",
                "pathname", "module", "msecs",
            ):
                extra[key] = value

        log_entry = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
        }
        log_entry.update(extra)
        return json.dumps(log_entry, ensure_ascii=False)


def setup_logging(level: str = "INFO", json_log: bool = True) -> None:
    """配置日志输出.

    Args:
        level: 日志级别 (INFO, DEBUG 等).
        json_log: 若为 True 则使用 JsonFormatter 输出 JSON.
    """
    if json_log:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)
        root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer() if json_log else structlog.dev.ConsoleRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "clarify") -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
