"""In-memory domain model for the intentionally small Phase 0 application."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from threading import Lock
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class Task:
    id: str
    title: str
    description: str
    created_at: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


class TaskStore:
    """A process-local, thread-safe task repository.

    Volatile storage is deliberate in Phase 0. PostgreSQL is introduced only after
    the learner has experienced why process-local state is insufficient.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._lock = Lock()

    def create(self, *, title: str, description: str) -> Task:
        task = Task(
            id=f"task_{uuid4().hex}",
            title=title,
            description=description,
            created_at=datetime.now(UTC).isoformat(),
        )
        with self._lock:
            self._tasks[task.id] = task
        return task

    def list_all(self) -> list[Task]:
        with self._lock:
            return list(self._tasks.values())

