from __future__ import annotations

import http.client
import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from titan_api.config import Settings
from titan_api.server import build_server


class TitanHTTPServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = build_server(
            Settings(host="127.0.0.1", port=0, max_request_bytes=1_024)
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address[:2]
        self.base_url = f"http://{host}:{port}"
        self.host = host
        self.port = port

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_health_over_real_http(self) -> None:
        request = Request(
            f"{self.base_url}/healthz",
            headers={"X-Request-ID": "integration-test"},
        )

        with urlopen(request, timeout=2) as response:
            document = json.load(response)
            self.assertEqual(200, response.status)
            self.assertEqual("integration-test", response.headers["X-Request-ID"])
            self.assertEqual("ok", document["status"])

    def test_create_task_over_real_http(self) -> None:
        body = json.dumps({"title": "Run an integration test"}).encode("utf-8")
        request = Request(
            f"{self.base_url}/api/tasks",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )

        with urlopen(request, timeout=2) as response:
            document = json.load(response)
            self.assertEqual(201, response.status)
            self.assertEqual("Run an integration test", document["task"]["title"])
            self.assertTrue(response.headers["Location"].startswith("/api/tasks/task_"))

    def test_oversized_body_is_rejected_before_reading(self) -> None:
        connection = http.client.HTTPConnection(self.host, self.port, timeout=2)
        try:
            connection.request(
                "POST",
                "/api/tasks",
                body=b"x" * 1_025,
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            document = json.loads(response.read())
        finally:
            connection.close()

        self.assertEqual(413, response.status)
        self.assertEqual("REQUEST_TOO_LARGE", document["error"]["code"])

    def test_invalid_request_id_is_not_reflected(self) -> None:
        request = Request(
            f"{self.base_url}/healthz",
            headers={"X-Request-ID": "unsafe request id with spaces"},
        )

        with urlopen(request, timeout=2) as response:
            request_id = response.headers["X-Request-ID"]

        self.assertNotEqual("unsafe request id with spaces", request_id)
        self.assertRegex(request_id, r"^[a-f0-9]{32}$")

    def test_api_error_remains_json_over_http(self) -> None:
        request = Request(f"{self.base_url}/missing")

        with self.assertRaises(HTTPError) as context:
            urlopen(request, timeout=2)

        document = json.loads(context.exception.read())
        self.assertEqual(404, context.exception.code)
        self.assertEqual("RESOURCE_NOT_FOUND", document["error"]["code"])


if __name__ == "__main__":
    unittest.main()

