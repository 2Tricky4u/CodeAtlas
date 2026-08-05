"""structlog configuration: JSON lines, contextvars-bound run/stage context.

The sink resolves `sys.stderr` at write time and swallows sink failures. Both
matter: structlog's stock factories capture the stream at construction, so a
redirected or closed stream (test capture teardown, a detached service, a closed
pipe) turns every later log call into an exception — which, in a pipeline, means
logging can take down a run it was only supposed to describe.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog


class _ResilientStderrLogger:
    """Writes to whatever `sys.stderr` is now; never raises."""

    def msg(self, message: str) -> None:
        try:
            stream = sys.stderr
            if stream is None or getattr(stream, "closed", False):
                return
            stream.write(message + "\n")
            stream.flush()
        except (ValueError, OSError):
            # A vanished sink is not a reason to fail the work being logged.
            return

    log = debug = info = warning = warn = error = critical = fatal = exception = msg

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<ResilientStderrLogger>"


class _ResilientLoggerFactory:
    def __call__(self, *args: Any) -> _ResilientStderrLogger:
        return _ResilientStderrLogger()


def configure_logging(level: int = logging.INFO) -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=_ResilientLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]
