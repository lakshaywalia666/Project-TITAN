"""Process entrypoint for the Titan AI API."""

from __future__ import annotations

import logging

from titan_ai.http_api import AIHTTPSettings, build_http_server
from titan_control.auth import authenticator_from_environ
from titan_ops.lifecycle import serve_with_signals


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = AIHTTPSettings.from_environ()
    server = build_http_server(
        settings=settings,
        authenticator=authenticator_from_environ(),
    )
    logging.getLogger("titan.ai.api").info(
        "Titan AI API listening on http://%s:%s", settings.host, settings.port
    )
    serve_with_signals(server, service="titan.ai.api")


if __name__ == "__main__":
    main()
