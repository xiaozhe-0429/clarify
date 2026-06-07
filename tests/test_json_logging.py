"""M1-3: JsonFormatter 输出 JSON 格式测试."""

import json
import logging
import io
from clarify.logging import JsonFormatter


def test_json_formatter_output_structure() -> None:
    """JsonFormatter 输出的 JSON 包含 timestamp, level, message."""
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="test message",
        args=(),
        exc_info=None,
    )
    output = formatter.format(record)
    data = json.loads(output)
    assert "timestamp" in data
    assert data["level"] == "INFO"
    assert data["message"] == "test message"


def test_json_formatter_extra_fields() -> None:
    """JsonFormatter 输出包含额外字段."""
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.WARNING,
        pathname="test.py",
        lineno=1,
        msg="warning message",
        args=(),
        exc_info=None,
    )
    record.field_a = "value_a"
    record.field_b = 123
    output = formatter.format(record)
    data = json.loads(output)
    assert data["field_a"] == "value_a"
    assert data["field_b"] == 123


def test_json_formatter_different_levels() -> None:
    """JsonFormatter 在不同日志级别下正常工作."""
    formatter = JsonFormatter()
    for level_name in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        record = logging.LogRecord(
            name="test",
            level=getattr(logging, level_name),
            pathname="test.py",
            lineno=1,
            msg=f"{level_name} message",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert data["level"] == level_name
        assert data["message"] == f"{level_name} message"
