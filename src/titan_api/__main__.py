"""Command-line entry point for ``python -m titan_api``."""

from __future__ import annotations

import json
import logging

from titan_api.config import ConfigurationError, Settings
from titan_api.server import configure_logging, run


def main() -> int:
    configure_logging()
    try:
        settings = Settings.from_environ()
    except ConfigurationError as error:
        logging.getLogger("titan.api").error(
            json.dumps(
                {"event": "configuration_error", "message": str(error)},
                separators=(",", ":"),
            )
        )
        return 2

    run(settings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

