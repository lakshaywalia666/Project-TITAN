"""Long-running reconciliation worker with signal-aware shutdown."""

from __future__ import annotations

import json
import logging
import os
import signal
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from titan_api.server import configure_logging
from titan_control.reconciler import LocalResourceProvider, Reconciler
from titan_control.store import SQLiteStore


@dataclass(frozen=True, slots=True)
class ControllerSettings:
    database_path: str = "var/titan-control.db"
    interval_seconds: float = 2.0
    batch_size: int = 20

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "ControllerSettings":
        source = os.environ if environ is None else environ
        database_path = source.get("TITAN_DATABASE", "var/titan-control.db").strip()
        if not database_path:
            raise ValueError("TITAN_DATABASE must not be empty")
        interval = float(source.get("TITAN_RECONCILE_INTERVAL_SECONDS", "2"))
        batch_size = int(source.get("TITAN_RECONCILE_BATCH_SIZE", "20"))
        if not 0.1 <= interval <= 300:
            raise ValueError("reconcile interval must be between 0.1 and 300 seconds")
        if not 1 <= batch_size <= 1_000:
            raise ValueError("reconcile batch size must be between 1 and 1000")
        return cls(database_path, interval, batch_size)


def run_controller(
    settings: ControllerSettings, stop_event: threading.Event | None = None
) -> None:
    logger = logging.getLogger("titan.control.controller")
    stopper = stop_event or threading.Event()
    reconciler = Reconciler(
        SQLiteStore(Path(settings.database_path)), LocalResourceProvider()
    )
    logger.info(
        json.dumps(
            {
                "event": "controller_started",
                "interval_seconds": settings.interval_seconds,
                "batch_size": settings.batch_size,
            },
            separators=(",", ":"),
        )
    )
    while not stopper.is_set():
        started = time.monotonic()
        summary = reconciler.run_once(settings.batch_size)
        if summary.claimed:
            logger.info(
                json.dumps(
                    {
                        "event": "reconcile_batch",
                        "claimed": summary.claimed,
                        "succeeded": summary.succeeded,
                        "failed": summary.failed,
                        "duration_ms": round(
                            (time.monotonic() - started) * 1_000, 3
                        ),
                    },
                    separators=(",", ":"),
                )
            )
        stopper.wait(settings.interval_seconds)
    logger.info('{"event":"controller_stopped"}')


def main() -> int:
    configure_logging()
    logger = logging.getLogger("titan.control.controller")
    try:
        settings = ControllerSettings.from_environ()
    except ValueError as error:
        logger.error(
            json.dumps(
                {"event": "controller_configuration_error", "message": str(error)},
                separators=(",", ":"),
            )
        )
        return 2

    stop_event = threading.Event()

    def request_shutdown(signum: int, frame: object) -> None:
        logger.info(
            json.dumps(
                {"event": "controller_shutdown_requested", "signal": signum},
                separators=(",", ":"),
            )
        )
        stop_event.set()

    for signal_name in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signal_name, request_shutdown)

    run_controller(settings, stop_event)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

