"""Logging must describe the work, never break it.

Regression: structlog's stock PrintLoggerFactory captures `sys.stderr` at
construction. When the stream was later closed (pytest capture teardown), every
subsequent log call raised and took down the reviewer dispatch that was only
trying to report an error.
"""

from __future__ import annotations

import io
import sys

from codeatlas.core.logging import configure_logging, get_logger


def test_log_call_survives_a_closed_stream(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    configure_logging()
    stream = io.StringIO()
    stream.close()
    monkeypatch.setattr(sys, "stderr", stream)

    get_logger("test").info("event.after_close", key="value")  # must not raise


def test_log_call_survives_a_missing_stream(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    configure_logging()
    monkeypatch.setattr(sys, "stderr", None)

    get_logger("test").error("event.no_stream", key="value")  # must not raise


def test_output_follows_stream_redirection(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The sink resolves sys.stderr per call, so redirection is honored."""
    configure_logging()
    first, second = io.StringIO(), io.StringIO()

    monkeypatch.setattr(sys, "stderr", first)
    get_logger("test").info("event.one")
    monkeypatch.setattr(sys, "stderr", second)
    get_logger("test").info("event.two")

    assert "event.one" in first.getvalue()
    assert "event.two" in second.getvalue()
    assert "event.two" not in first.getvalue()


def test_emits_json_lines(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import json

    configure_logging()
    stream = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stream)

    get_logger("test").info("event.structured", run_id="R1", stage="extract")
    payload = json.loads(stream.getvalue().strip())
    assert payload["event"] == "event.structured"
    assert payload["run_id"] == "R1"
    assert payload["level"] == "info"
