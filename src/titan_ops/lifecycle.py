"""Signal-aware HTTP serving with bounded graceful shutdown."""

from __future__ import annotations

import json
import logging
import signal
import threading
from socketserver import BaseServer


def serve_with_signals(
    server: BaseServer,
    *,
    service: str,
    stop_event: threading.Event | None = None,
    install_signal_handlers: bool = True,
    shutdown_timeout_seconds: float = 10.0,
) -> None:
    logger = logging.getLogger(service)
    stopper = stop_event or threading.Event()

    def request_shutdown(signum: int, frame: object) -> None:
        logger.info(
            json.dumps(
                {"event": "shutdown_requested", "service": service, "signal": signum},
                separators=(",", ":"),
            )
        )
        stopper.set()

    if install_signal_handlers:
        for signal_name in (signal.SIGINT, signal.SIGTERM):
            signal.signal(signal_name, request_shutdown)

    serving_thread = threading.Thread(
        target=server.serve_forever,
        kwargs={"poll_interval": 0.25},
        name=f"{service}-http",
        daemon=True,
    )
    serving_thread.start()
    try:
        stopper.wait()
    except KeyboardInterrupt:
        stopper.set()
    finally:
        server.shutdown()
        serving_thread.join(timeout=shutdown_timeout_seconds)
        server.server_close()
        if serving_thread.is_alive():
            logger.error(
                json.dumps(
                    {"event": "shutdown_timeout", "service": service},
                    separators=(",", ":"),
                )
            )
        else:
            logger.info(
                json.dumps(
                    {"event": "server_stopped", "service": service},
                    separators=(",", ":"),
                )
            )

