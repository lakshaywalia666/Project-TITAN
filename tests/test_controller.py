from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from titan_control.controller import ControllerSettings, run_controller
from titan_control.domain import Identity, ResourceState
from titan_control.service import ControlPlane
from titan_control.store import SQLiteStore


class ControllerTests(unittest.TestCase):
    def test_background_controller_converges_and_stops(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "control.db"
            store = SQLiteStore(database)
            control_plane = ControlPlane(store)
            admin = Identity("test-admin", ("admin",))
            project = control_plane.create_project(
                identity=admin,
                name="controller-test",
                idempotency_key="controller-project-key",
            )
            resource = control_plane.create_resource(
                identity=admin,
                project_id=project.id,
                kind="service",
                name="background-service",
                spec={"image": "registry.example/test@sha256:abc"},
                idempotency_key="controller-resource-key",
            )
            stop_event = threading.Event()
            controller = threading.Thread(
                target=run_controller,
                args=(ControllerSettings(str(database), 0.1, 10), stop_event),
                daemon=True,
            )
            controller.start()

            for _ in range(30):
                observed = store.get_resource(resource.id)
                if observed.state == ResourceState.READY:
                    break
                stop_event.wait(0.05)

            stop_event.set()
            controller.join(timeout=2)

            self.assertEqual(ResourceState.READY, observed.state)
            self.assertFalse(controller.is_alive())


if __name__ == "__main__":
    unittest.main()

