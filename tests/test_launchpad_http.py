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
from titan_launchpad.http_api import LaunchpadSettings, build_http_server
from titan_launchpad.models import example_workload
from titan_launchpad.store import LaunchpadStore


class LaunchpadHTTPTests(unittest.TestCase):
    ALICE_TOKEN = "alice-launchpad-test-token-0001"
    BOB_TOKEN = "bob-launchpad-test-token-000002"

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        database = Path(self.temp.name) / "launchpad.db"
        authenticator = TokenAuthenticator(
            (
                IdentityRecord(_hash_token(self.ALICE_TOKEN), Identity("alice", ("developer",))),
                IdentityRecord(_hash_token(self.BOB_TOKEN), Identity("bob", ("developer",))),
            )
        )
        self.server = build_http_server(
            settings=LaunchpadSettings(host="127.0.0.1", port=0, database_path=str(database)),
            authenticator=authenticator,
            store=LaunchpadStore(database),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address[:2]
        self.base_url = f"http://{host}:{port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def request(
        self,
        method: str,
        path: str,
        *,
        document: object | None = None,
        token: str | None = ALICE_TOKEN,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, object, object]:
        request_headers = dict(headers or {})
        if token:
            request_headers["Authorization"] = f"Bearer {token}"
        data = None
        if document is not None:
            data = json.dumps(document).encode()
            request_headers["Content-Type"] = "application/json"
        request = Request(
            f"{self.base_url}{path}", data=data, method=method, headers=request_headers
        )
        try:
            with urlopen(request, timeout=3) as response:
                return response.status, json.load(response), response.headers
        except HTTPError as error:
            try:
                return error.code, json.loads(error.read()), error.headers
            finally:
                error.close()

    def test_public_discovery_and_protected_assessments(self) -> None:
        health_status, health, _ = self.request("GET", "/healthz", token=None)
        catalog_status, catalog, _ = self.request("GET", "/v1/catalog", token=None)
        denied_status, denied, headers = self.request("GET", "/v1/assessments", token=None)

        self.assertEqual((200, "ok"), (health_status, health["status"]))
        self.assertEqual(200, catalog_status)
        self.assertEqual(
            {"aws", "azure", "gcp"},
            {provider["key"] for provider in catalog["providers"]},
        )
        self.assertEqual(401, denied_status)
        self.assertEqual("UNAUTHENTICATED", denied["error"]["code"])
        self.assertEqual("Bearer", headers["WWW-Authenticate"])

    def test_assessment_plan_idempotency_and_ownership(self) -> None:
        spec = example_workload()
        spec.update(
            {
                "image": "ghcr.io/example/support-api@sha256:" + "b" * 64,
                "budget_usd_month": 20,
            }
        )
        headers = {"Idempotency-Key": "assessment-1"}
        first_status, first, _ = self.request(
            "POST", "/v1/assessments", document=spec, headers=headers
        )
        replay_status, replay, _ = self.request(
            "POST", "/v1/assessments", document=spec, headers=headers
        )
        conflict_spec = dict(spec, name="other-api")
        conflict_status, conflict, _ = self.request(
            "POST", "/v1/assessments", document=conflict_spec, headers=headers
        )
        get_status, _, _ = self.request("GET", f"/v1/assessments/{first['id']}")
        denied_status, _, _ = self.request(
            "GET", f"/v1/assessments/{first['id']}", token=self.BOB_TOKEN
        )
        plan_status, plan, _ = self.request(
            "POST",
            f"/v1/assessments/{first['id']}/plans",
            document={"provider": "gcp"},
            headers={"Idempotency-Key": "plan-1"},
        )
        plan_get_status, fetched_plan, _ = self.request("GET", f"/v1/plans/{plan['id']}")

        self.assertEqual(201, first_status)
        self.assertEqual(200, replay_status)
        self.assertTrue(replay["idempotently_replayed"])
        self.assertEqual(first["id"], replay["id"])
        self.assertEqual(409, conflict_status)
        self.assertEqual("IDEMPOTENCY_CONFLICT", conflict["error"]["code"])
        self.assertEqual(200, get_status)
        self.assertEqual(403, denied_status)
        self.assertEqual(201, plan_status)
        self.assertEqual("READY_FOR_CREDENTIALS", plan["status"])
        self.assertEqual((200, plan["id"]), (plan_get_status, fetched_plan["id"]))

    def test_cors_preflight_allows_local_portal(self) -> None:
        request = Request(
            f"{self.base_url}/v1/assessments",
            method="OPTIONS",
            headers={"Origin": "http://localhost:3000"},
        )
        with urlopen(request, timeout=3) as response:
            self.assertEqual(204, response.status)
            self.assertIn("Idempotency-Key", response.headers["Access-Control-Allow-Headers"])


if __name__ == "__main__":
    unittest.main()
