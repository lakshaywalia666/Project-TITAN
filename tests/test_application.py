from __future__ import annotations

import json
import unittest

from titan_api.app import Request, TitanApplication


class TitanApplicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.application = TitanApplication()

    def request(
        self,
        method: str,
        target: str,
        *,
        document: object | None = None,
        raw_body: bytes | None = None,
        content_type: str = "application/json",
    ):
        body = raw_body
        if body is None:
            body = b"" if document is None else json.dumps(document).encode("utf-8")
        return self.application.handle(
            Request(
                method=method,
                target=target,
                headers={"content-type": content_type},
                body=body,
                request_id="test-request",
            )
        )

    def test_health_is_ok(self) -> None:
        response = self.request("GET", "/healthz")

        self.assertEqual(200, response.status)
        self.assertEqual({"status": "ok"}, response.payload)

    def test_version_is_machine_readable(self) -> None:
        response = self.request("GET", "/version")

        self.assertEqual(200, response.status)
        self.assertEqual("titan-reference-api", response.payload["name"])
        self.assertRegex(str(response.payload["version"]), r"^\d+\.\d+\.\d+$")

    def test_create_then_list_task(self) -> None:
        create_response = self.request(
            "POST",
            "/api/tasks",
            document={"title": "Learn HTTP", "description": "Inspect one request"},
        )
        list_response = self.request("GET", "/api/tasks")

        self.assertEqual(201, create_response.status)
        self.assertEqual(1, list_response.payload["count"])
        task = list_response.payload["items"][0]
        self.assertEqual("Learn HTTP", task["title"])
        self.assertTrue(task["id"].startswith("task_"))

    def test_invalid_json_returns_stable_error_code(self) -> None:
        response = self.request(
            "POST", "/api/tasks", raw_body=b"{not-json", content_type="application/json"
        )

        self.assertEqual(400, response.status)
        self.assertEqual("INVALID_JSON", response.payload["error"]["code"])
        self.assertEqual("test-request", response.payload["error"]["request_id"])

    def test_unknown_fields_are_rejected(self) -> None:
        response = self.request(
            "POST",
            "/api/tasks",
            document={"title": "Valid", "administrator": True},
        )

        self.assertEqual(422, response.status)
        self.assertEqual("UNKNOWN_FIELDS", response.payload["error"]["code"])

    def test_blank_title_is_rejected(self) -> None:
        response = self.request("POST", "/api/tasks", document={"title": "   "})

        self.assertEqual(422, response.status)
        self.assertEqual("INVALID_TITLE", response.payload["error"]["code"])

    def test_non_json_content_type_is_rejected(self) -> None:
        response = self.request(
            "POST",
            "/api/tasks",
            raw_body=b"title=not-json",
            content_type="application/x-www-form-urlencoded",
        )

        self.assertEqual(415, response.status)
        self.assertEqual("UNSUPPORTED_MEDIA_TYPE", response.payload["error"]["code"])

    def test_method_not_allowed_includes_allow_header(self) -> None:
        response = self.request("DELETE", "/api/tasks")

        self.assertEqual(405, response.status)
        self.assertEqual("GET, POST", response.headers["Allow"])

    def test_unknown_resource_returns_404(self) -> None:
        response = self.request("GET", "/not-real")

        self.assertEqual(404, response.status)
        self.assertEqual("RESOURCE_NOT_FOUND", response.payload["error"]["code"])


if __name__ == "__main__":
    unittest.main()

