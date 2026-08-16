from __future__ import annotations

import threading
import unittest

from titan_ops.lifecycle import serve_with_signals


class FakeServer:
    def __init__(self) -> None:
        self.serving = threading.Event()
        self.stopped = threading.Event()
        self.closed = False

    def serve_forever(self, poll_interval: float) -> None:
        self.serving.set()
        self.stopped.wait(timeout=2)

    def shutdown(self) -> None:
        self.stopped.set()

    def server_close(self) -> None:
        self.closed = True


class LifecycleTests(unittest.TestCase):
    def test_stop_event_drains_and_closes_server(self) -> None:
        server = FakeServer()
        stop = threading.Event()
        runner = threading.Thread(
            target=serve_with_signals,
            kwargs={
                "server": server,
                "service": "test.service",
                "stop_event": stop,
                "install_signal_handlers": False,
            },
        )
        runner.start()
        self.assertTrue(server.serving.wait(timeout=1))
        stop.set()
        runner.join(timeout=2)
        self.assertFalse(runner.is_alive())
        self.assertTrue(server.closed)


if __name__ == "__main__":
    unittest.main()

