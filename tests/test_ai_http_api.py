from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from titan_ai.http_api import AIHTTPSettings, build_http_server, runtime_from_environ
from titan_control.auth import IdentityRecord, TokenAuthenticator, _hash_token
from titan_control.domain import Identity


class AIHTTPTests(unittest.TestCase):
    TOKEN = "this-is-a-long-ai-api-test-token"

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        settings = AIHTTPSettings(
            host="127.0.0.1",
            port=0,
            knowledge_database=str(Path(self.temporary_directory.name) / "knowledge.db"),
        )
        authenticator = TokenAuthenticator(
            (
                IdentityRecord(
                    token_sha256=_hash_token(self.TOKEN),
                    identity=Identity("test-admin", ("admin",)),
                ),
            )
        )
        runtime = runtime_from_environ(settings, {})
        self.server = build_http_server(
            settings=settings,
            authenticator=authenticator,
            runtime=runtime,
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
        self, path: str, document: object, *, authenticated: bool = True
    ) -> tuple[int, object]:
        headers = {"Content-Type": "application/json"}
        if authenticated:
            headers["Authorization"] = f"Bearer {self.TOKEN}"
        request = Request(
            f"{self.base_url}{path}",
            data=json.dumps(document).encode("utf-8"),
            method="POST",
            headers=headers,
        )
        try:
            with urlopen(request, timeout=3) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.loads(error.read())

    def test_chat_completion_uses_offline_route(self) -> None:
        status, document = self.request(
            "/v1/chat/completions",
            {
                "project_id": "local",
                "messages": [{"role": "user", "content": "hello"}],
                "max_tokens": 30,
            },
        )

        self.assertEqual(200, status)
        self.assertEqual("chat.completion", document["object"])
        self.assertEqual("offline", document["titan"]["backend"])

    def test_knowledge_ingestion_and_acl_aware_search(self) -> None:
        ingest_status, _ = self.request(
            "/v1/knowledge/documents",
            {
                "project_id": "local",
                "knowledge_base_id": "runbooks",
                "source_id": "api-start",
                "content": "Restart the API only after checking its readiness probe. " * 4,
                "acl": {"projects": ["local"]},
            },
        )
        search_status, search = self.request(
            "/v1/knowledge/search",
            {
                "project_id": "local",
                "knowledge_base_id": "runbooks",
                "query": "API readiness probe",
            },
        )

        self.assertEqual(201, ingest_status)
        self.assertEqual(200, search_status)
        self.assertEqual("api-start", search["items"][0]["citation"]["source_id"])

    def test_authentication_is_required(self) -> None:
        status, document = self.request(
            "/v1/chat/completions",
            {"project_id": "local", "messages": []},
            authenticated=False,
        )
        self.assertEqual(401, status)
        self.assertEqual("UNAUTHENTICATED", document["error"]["code"])

    def test_cors_preflight_allows_local_portal(self) -> None:
        request = Request(
            f"{self.base_url}/v1/chat/completions",
            method="OPTIONS",
            headers={"Origin": "http://127.0.0.1:3000"},
        )
        with urlopen(request, timeout=3) as response:
            self.assertEqual(204, response.status)
            self.assertEqual(
                "http://127.0.0.1:3000",
                response.headers["Access-Control-Allow-Origin"],
            )


if __name__ == "__main__":
    unittest.main()
