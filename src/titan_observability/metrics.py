"""Prometheus-compatible metrics with bounded label cardinality.

Titan deliberately keeps its bootstrap runtime dependency-free.  This registry is
not intended to replace a full telemetry SDK; it provides the four golden signals
until the optional OpenTelemetry stack is enabled by the deployment layer.
"""

from __future__ import annotations

import math
import re
import threading
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Mapping

METRIC_NAME = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")
DEFAULT_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)


@dataclass(frozen=True, slots=True)
class _Series:
    name: str
    labels: tuple[tuple[str, str], ...]


class MetricsRegistry:
    """Thread-safe in-process metric registry.

    Callers must pass normalized routes (for example ``/v1/resources/:id``), never
    unbounded request IDs or user values, as labels.
    """

    def __init__(self) -> None:
        self._counters: dict[_Series, float] = defaultdict(float)
        self._gauges: dict[_Series, float] = {}
        self._histograms: dict[
            _Series, tuple[tuple[float, ...], list[int], float, int]
        ] = {}
        self._help: dict[str, tuple[str, str]] = {}
        self._lock = threading.RLock()

    def counter(
        self,
        name: str,
        amount: float = 1.0,
        *,
        labels: Mapping[str, object] | None = None,
        help_text: str = "",
    ) -> None:
        if amount < 0 or not math.isfinite(amount):
            raise ValueError("counter increments must be finite and non-negative")
        series = self._series(name, labels)
        with self._lock:
            self._declare(name, "counter", help_text)
            self._counters[series] += amount

    def gauge(
        self,
        name: str,
        value: float,
        *,
        labels: Mapping[str, object] | None = None,
        help_text: str = "",
    ) -> None:
        if not math.isfinite(value):
            raise ValueError("gauge values must be finite")
        series = self._series(name, labels)
        with self._lock:
            self._declare(name, "gauge", help_text)
            self._gauges[series] = value

    def histogram(
        self,
        name: str,
        value: float,
        *,
        labels: Mapping[str, object] | None = None,
        buckets: Iterable[float] = DEFAULT_BUCKETS,
        help_text: str = "",
    ) -> None:
        if value < 0 or not math.isfinite(value):
            raise ValueError("histogram observations must be finite and non-negative")
        bounds = tuple(float(bound) for bound in buckets)
        if not bounds or tuple(sorted(set(bounds))) != bounds:
            raise ValueError("histogram buckets must be unique and increasing")
        series = self._series(name, labels)
        with self._lock:
            self._declare(name, "histogram", help_text)
            stored_bounds, counts, total, observations = self._histograms.get(
                series, (bounds, [0] * len(bounds), 0.0, 0)
            )
            if stored_bounds != bounds:
                raise ValueError("histogram bucket definitions cannot change")
            for index, bound in enumerate(bounds):
                if value <= bound:
                    counts[index] += 1
            self._histograms[series] = (
                stored_bounds,
                counts,
                total + value,
                observations + 1,
            )

    def render_prometheus(self) -> bytes:
        lines: list[str] = []
        with self._lock:
            names = sorted(self._help)
            for name in names:
                metric_type, help_text = self._help[name]
                if help_text:
                    lines.append(f"# HELP {name} {_escape_help(help_text)}")
                lines.append(f"# TYPE {name} {metric_type}")
                if metric_type == "counter":
                    for series, value in sorted(
                        self._counters.items(), key=_series_sort_key
                    ):
                        if series.name == name:
                            lines.append(_sample(name, series.labels, value))
                elif metric_type == "gauge":
                    for series, value in sorted(
                        self._gauges.items(), key=_series_sort_key
                    ):
                        if series.name == name:
                            lines.append(_sample(name, series.labels, value))
                else:
                    for series, values in sorted(
                        self._histograms.items(), key=_series_sort_key
                    ):
                        if series.name != name:
                            continue
                        bounds, counts, total, observations = values
                        for bound, count in zip(bounds, counts, strict=True):
                            lines.append(
                                _sample(
                                    f"{name}_bucket",
                                    series.labels + (("le", _number(bound)),),
                                    count,
                                )
                            )
                        lines.append(
                            _sample(
                                f"{name}_bucket",
                                series.labels + (("le", "+Inf"),),
                                observations,
                            )
                        )
                        lines.append(_sample(f"{name}_sum", series.labels, total))
                        lines.append(
                            _sample(f"{name}_count", series.labels, observations)
                        )
        return ("\n".join(lines) + "\n").encode("utf-8")

    def observe_http(
        self,
        *,
        service: str,
        method: str,
        route: str,
        status: int,
        duration_seconds: float,
    ) -> None:
        labels = {
            "service": service,
            "method": method,
            "route": route,
            "status_class": f"{status // 100}xx",
        }
        self.counter(
            "titan_http_requests_total",
            labels=labels,
            help_text="HTTP requests completed by Titan services.",
        )
        self.histogram(
            "titan_http_request_duration_seconds",
            duration_seconds,
            labels={key: labels[key] for key in ("service", "method", "route")},
            help_text="Titan HTTP request latency in seconds.",
        )

    def _declare(self, name: str, metric_type: str, help_text: str) -> None:
        current = self._help.get(name)
        declaration = (metric_type, help_text)
        if current is not None and current != declaration:
            raise ValueError(f"metric {name} was declared inconsistently")
        self._help[name] = declaration

    @staticmethod
    def _series(
        name: str, labels: Mapping[str, object] | None
    ) -> _Series:
        if not METRIC_NAME.fullmatch(name):
            raise ValueError(f"invalid Prometheus metric name: {name}")
        normalized: list[tuple[str, str]] = []
        for key, value in sorted((labels or {}).items()):
            if not METRIC_NAME.fullmatch(key):
                raise ValueError(f"invalid Prometheus label name: {key}")
            normalized.append((key, str(value)))
        return _Series(name, tuple(normalized))


def _sample(name: str, labels: tuple[tuple[str, str], ...], value: float) -> str:
    suffix = ""
    if labels:
        rendered = ",".join(
            f'{key}="{_escape_label(item)}"' for key, item in labels
        )
        suffix = "{" + rendered + "}"
    return f"{name}{suffix} {_number(value)}"


def _number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else format(value, ".12g")


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _escape_help(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n")


def _series_sort_key(item: tuple[_Series, object]) -> tuple[object, ...]:
    return (item[0].name, item[0].labels)
