"""Executable entry point for the authenticated control-plane HTTP API."""

from __future__ import annotations

import json
import logging

from titan_api.server import configure_logging
from titan_control.auth import authenticator_from_environ
from titan_control.http_api import HTTPSettings, build_http_server
from titan_ops.lifecycle import serve_with_signals


def main() -> int:
    configure_logging()
    logger = logging.getLogger("titan.control.api")
    try:
        settings = HTTPSettings.from_environ()
        authenticator = authenticator_from_environ()
        server = build_http_server(settings=settings, authenticator=authenticator)
    except (ValueError, RuntimeError) as error:
        logger.error(
            json.dumps(
                {"event": "control_api_configuration_error", "message": str(error)},
                separators=(",", ":"),
            )
        )
        return 2

    host, port = server.server_address[:2]
    logger.info(
        json.dumps(
            {"event": "control_api_started", "host": host, "port": port},
            separators=(",", ":"),
        )
    )
    serve_with_signals(server, service="titan.control.api")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
