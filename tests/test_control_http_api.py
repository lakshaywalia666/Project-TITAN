from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from titan_control.auth import IdentityRecord, TokenAuthenticator, _hash_token
from titan_control.domain import Identity
from titan_control.http_api import HTTPSettings, build_http_server
from titan_control.store import SQLiteStore


class ControlPlaneHTTPTests(unittest.TestCase):
    ADMIN_TOKEN = "this-is-a-long-admin-test-token"

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        database = Path(self.temporary_directory.name) / "control.db"
        self.store = SQLiteStore(database)
        authenticator = TokenAuthenticator(
            (
                IdentityRecord(
                    token_sha256=_hash_token(self.ADMIN_TOKEN),
                    identity=Identity("test-admin", ("admin",)),
                ),
            )
        )
        self.server = build_http_server(
            settings=HTTPSettings(host="127.0.0.1", port=0, database_path=str(database)),
            authenticator=authenticator,
            store=self.store,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address[:2]
        self.base_url = f"http://{host}:{port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary_directory.cleanup()

    def request(
        self,
        method: str,
        path: str,
        *,
        document: object | None = None,
        headers: dict[str, str] | None = None,
        authenticated: bool = True,
    ) -> tuple[int, object, MappingLike]:
        request_headers = dict(headers or {})
        if authenticated:
            request_headers["Authorization"] = f"Bearer {self.ADMIN_TOKEN}"
        data = None
        if document is not None:
            data = json.dumps(document).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        request = Request(
            f"{self.base_url}{path}",
            data=data,
            method=method,
            headers=request_headers,
        )
        try:
            with urlopen(request, timeout=3) as response:
                return response.status, json.load(response), response.headers
        except HTTPError as error:
            return error.code, json.loads(error.read()), error.headers

    def test_authentication_is_required(self) -> None:
        status, document, _ = self.request(
            "GET", "/v1/projects", authenticated=False
        )

        self.assertEqual(401, status)
        self.assertEqual("UNAUTHENTICATED", document["error"]["code"])

    def test_full_resource_lifecycle_over_http(self) -> None:
        project_status, project, _ = self.request(
            "POST",
            "/v1/projects",
            document={"name": "payments"},
            headers={"Idempotency-Key": "create-payments-project"},
        )
        resource_status, resource, _ = self.request(
            "POST",
            f"/v1/projects/{project['id']}/resources",
            document={
                "kind": "service",
                "name": "payments-api",
                "spec": {"image": "registry.example/payments@sha256:abc"},
            },
            headers={"Idempotency-Key": "create-payments-service"},
        )
        reconcile_status, reconcile, _ = self.request(
            "POST", "/v1/reconcile", document={"limit": 10}
        )
        get_status, observed, response_headers = self.request(
            "GET", f"/v1/resources/{resource['id']}"
        )

        self.assertEqual(201, project_status)
        self.assertEqual(202, resource_status)
        self.assertEqual(200, reconcile_status)
        self.assertEqual(1, reconcile["succeeded"])
        self.assertEqual(200, get_status)
        self.assertEqual("READY", observed["state"])
        self.assertEqual("1", response_headers["ETag"])

    def test_idempotent_http_retry_returns_same_project(self) -> None:
        headers = {"Idempotency-Key": "stable-project-request"}
        first_status, first, _ = self.request(
            "POST", "/v1/projects", document={"name": "stable"}, headers=headers
        )
        second_status, second, _ = self.request(
            "POST", "/v1/projects", document={"name": "stable"}, headers=headers
        )

        self.assertEqual(201, first_status)
        self.assertEqual(201, second_status)
        self.assertEqual(first["id"], second["id"])

    def test_metrics_endpoint_exports_normalized_route(self) -> None:
        self.request("GET", "/v1/projects")
        with urlopen(f"{self.base_url}/metrics", timeout=3) as response:
            output = response.read().decode("utf-8")

        self.assertIn("titan_http_requests_total", output)
        self.assertIn('route="/v1/projects"', output)

    def test_cors_preflight_allows_only_configured_local_portal(self) -> None:
        request = Request(
            f"{self.base_url}/v1/projects",
            method="OPTIONS",
            headers={"Origin": "http://localhost:3000"},
        )
        with urlopen(request, timeout=3) as response:
            self.assertEqual(204, response.status)
            self.assertEqual(
                "http://localhost:3000",
                response.headers["Access-Control-Allow-Origin"],
            )

        denied = Request(
            f"{self.base_url}/v1/projects",
            method="OPTIONS",
            headers={"Origin": "https://untrusted.example"},
        )
        with self.assertRaises(HTTPError) as result:
            urlopen(denied, timeout=3)
        self.assertEqual(403, result.exception.code)


class MappingLike:
    def __getitem__(self, key: str) -> str: ...


if __name__ == "__main__":
    unittest.main()
