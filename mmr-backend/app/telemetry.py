"""Bounded, content-free telemetry for the local single-process API."""

import json
import logging
import time
from collections import Counter, deque
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Lock


logger = logging.getLogger("rag_trace")
_trace_id: ContextVar[str | None] = ContextVar("rag_trace_id", default=None)
_lock = Lock()
_requests = Counter()
_latency_buckets = Counter()
_spans = Counter()
_errors = deque(maxlen=25)
LATENCY_BOUNDS_MS = (50, 100, 250, 500, 1000, 2500, 5000)
SPAN_NAMES = {"chat_answer", "structured_output", "web_fetch"}


def set_trace(trace_id: str):
    return _trace_id.set(trace_id)


def reset_trace(token) -> None:
    _trace_id.reset(token)


def observe_request(route: str, status: int, duration_ms: float, request_id: str,
                    error_type: str | None = None) -> None:
    """Aggregate route-template/status labels and keep a bounded 5xx summary."""
    status_class = f"{status // 100}xx"
    bucket = next((str(bound) for bound in LATENCY_BOUNDS_MS if duration_ms <= bound), "+Inf")
    with _lock:
        _requests[(route, status_class)] += 1
        _latency_buckets[(route, bucket)] += 1
        if status >= 500:
            _errors.append({"request_id": request_id, "route": route,
                            "status": status, "type": error_type or "http_error"})


@contextmanager
def trace_span(name: str):
    """Log a named operation duration against the active request trace."""
    if name not in SPAN_NAMES:
        raise ValueError("Unknown trace span.")
    started = time.monotonic()
    failed = False
    try:
        yield
    except Exception:
        failed = True
        raise
    finally:
        duration_ms = round((time.monotonic() - started) * 1000, 1)
        with _lock:
            _spans[(name, "failed" if failed else "ok")] += 1
        logger.info(json.dumps({"event": "span", "trace_id": _trace_id.get(),
                                "name": name, "duration_ms": duration_ms,
                                "status": "failed" if failed else "ok"}, separators=(",", ":")))


def metrics_snapshot() -> dict:
    with _lock:
        return {
            "requests": [{"route": route, "status_class": status, "count": count}
                         for (route, status), count in sorted(_requests.items())],
            "latency_buckets_ms": [{"route": route, "le": bound, "count": count}
                                   for (route, bound), count in sorted(_latency_buckets.items())],
            "spans": [{"name": name, "status": status, "count": count}
                      for (name, status), count in sorted(_spans.items())],
            "recent_errors": list(_errors),
        }
