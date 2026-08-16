from __future__ import annotations

import logging

from titan_control.auth import authenticator_from_environ
from titan_workloads.shop_api import ShopSettings, build_http_server
from titan_ops.lifecycle import serve_with_signals


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = ShopSettings.from_environ()
    server = build_http_server(
        settings=settings, authenticator=authenticator_from_environ()
    )
    serve_with_signals(server, service="titan.shop.api")


if __name__ == "__main__":
    main()
