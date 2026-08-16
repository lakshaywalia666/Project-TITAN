from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

from titan_ai.http_api import AIHTTPSettings, build_http_server as build_ai_server, runtime_from_environ
from titan_control.auth import IdentityRecord, TokenAuthenticator, _hash_token
from titan_control.domain import Identity
from titan_control.http_api import HTTPSettings, build_http_server as build_control_server
from titan_control.store import SQLiteStore
from titan_ops.backup import SQLiteBackupManager
from titan_workloads.shop import ShopStore
from titan_workloads.shop_api import ShopSettings, build_http_server as build_shop_server


class TitanEndToEndTests(unittest.TestCase):
    TOKEN = "titan-end-to-end-admin-token-value"

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.authenticator = TokenAuthenticator(
            (
                IdentityRecord(
                    token_sha256=_hash_token(self.TOKEN),
                    identity=Identity("capstone-admin", ("admin",)),
                ),
            )
        )
        self.servers: list[object] = []
        self.threads: list[threading.Thread] = []

    def tearDown(self) -> None:
        for server in self.servers:
            server.shutdown()
            server.server_close()
        for thread in self.threads:
            thread.join(timeout=2)
        self.temporary_directory.cleanup()

    def start(self, server) -> str:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.servers.append(server)
        self.threads.append(thread)
        host, port = server.server_address[:2]
        return f"http://{host}:{port}"

    def call(self, base: str, method: str, path: str, body=None, extra_headers=None):
        headers = {"Authorization": f"Bearer {self.TOKEN}", **(extra_headers or {})}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        with urlopen(Request(base + path, method=method, data=data, headers=headers), timeout=3) as response:
            return response.status, json.load(response)

    def test_capstone_flow_from_desired_state_to_ai_shop_and_backup(self) -> None:
        control_db = self.root / "control.db"
        control = build_control_server(
            settings=HTTPSettings(host="127.0.0.1", port=0, database_path=str(control_db)),
            authenticator=self.authenticator,
            store=SQLiteStore(control_db),
        )
        control_url = self.start(control)
        _, project = self.call(
            control_url,
            "POST",
            "/v1/projects",
            {"name": "capstone"},
            {"Idempotency-Key": "capstone-project"},
        )
        resource_status, resource = self.call(
            control_url,
            "POST",
            f"/v1/projects/{project['id']}/resources",
            {
                "name": "titan-shop",
                "kind": "service",
                "spec": {
                    "replicas": 1,
                    "image": "ghcr.io/example/titan-shop@sha256:abc",
                },
            },
            {"Idempotency-Key": "capstone-shop"},
        )
        self.call(control_url, "POST", "/v1/reconcile", {"limit": 20})
        _, observed = self.call(control_url, "GET", f"/v1/resources/{resource['id']}")

        knowledge_db = self.root / "knowledge.db"
        ai_settings = AIHTTPSettings(host="127.0.0.1", port=0, knowledge_database=str(knowledge_db))
        runtime = runtime_from_environ(
            ai_settings,
            {
                "TITAN_AI_ALLOWED_MODELS_JSON": json.dumps({project["id"]: ["titan-offline"]}),
                "TITAN_AI_TOKEN_BUDGETS_JSON": json.dumps({project["id"]: 10000}),
            },
        )
        ai_url = self.start(
            build_ai_server(settings=ai_settings, authenticator=self.authenticator, runtime=runtime)
        )
        _, chat = self.call(
            ai_url,
            "POST",
            "/v1/chat/completions",
            {"project_id": project["id"], "messages": [{"role": "user", "content": "status"}]},
        )

        shop_db = self.root / "shop.db"
        shop_url = self.start(
            build_shop_server(
                settings=ShopSettings(host="127.0.0.1", port=0, database_path=str(shop_db)),
                authenticator=self.authenticator,
                store=ShopStore(shop_db),
            )
        )
        _, order = self.call(
            shop_url,
            "POST",
            "/v1/orders",
            {"project_id": project["id"], "items": [{"sku": "SRE-NOTE", "quantity": 1}]},
            {"Idempotency-Key": "capstone-order"},
        )

        manifest = SQLiteBackupManager().backup(
            databases={"control": control_db, "knowledge": knowledge_db, "shop": shop_db},
            destination=self.root / "backup",
        )

        self.assertEqual(202, resource_status)
        self.assertEqual("READY", observed["state"])
        self.assertEqual("offline", chat["titan"]["backend"])
        self.assertEqual("PAID", order["state"])
        self.assertEqual(3, len(manifest.artifacts))


if __name__ == "__main__":
    unittest.main()
