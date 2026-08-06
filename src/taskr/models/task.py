"""Canonical task model and its spreadsheet representation.

``Target`` uses ISO 8601 dates (``YYYY-MM-DD``). ``Priority`` is an integer from
1 (highest) through 4 (lowest). IDs are UUIDv7 values: UUIDs remain stable when
rows move, while their leading bits retain the requested millisecond timestamp.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum, IntEnum
import secrets
import time
import uuid
from typing import Any, Mapping


TASK_COLUMNS = (
    "ID", "Category", "Reference", "Task", "Details", "Tags", "Target",
    "Assigned", "Priority", "Status", "Notes",
)


class Status(str, Enum):
    NONE = "None"
    IN_PROGRESS = "InProgress"
    BLOCKED = "Blocked"
    COMPLETE = "Complete"


class Priority(IntEnum):
    HIGH = 1
    MEDIUM = 2
    LOW = 3
    SOMEDAY = 4


def timestamp_uuid() -> str:
    """Return a standards-compatible UUIDv7 (timestamp-based, not a timestamp ID)."""
    milliseconds = int(time.time_ns() // 1_000_000) & ((1 << 48) - 1)
    value = milliseconds << 80
    value |= 0x7 << 76
    value |= secrets.randbits(12) << 64
    value |= 0b10 << 62
    value |= secrets.randbits(62)
    return str(uuid.UUID(int=value))


@dataclass(frozen=True, slots=True)
class Task:
    task: str
    id: str = ""
    category: str = ""
    reference: str = ""
    details: str = ""
    tags: str = ""
    target: date | None = None
    assigned: str = ""
    priority: Priority = Priority.SOMEDAY
    status: Status = Status.NONE
    notes: str = ""

    def __post_init__(self) -> None:
        if self.id:
            parsed = uuid.UUID(self.id)
            if parsed.version != 7:
                raise ValueError("Task ID must be a UUIDv7")
        if not self.task.strip():
            raise ValueError("Task must not be blank")

    def with_id(self) -> Task:
        if self.id:
            return self
        values = self.to_record()
        values["ID"] = timestamp_uuid()
        return Task.from_record(values)

    def to_record(self) -> dict[str, str]:
        return {
            "ID": self.id, "Category": self.category, "Reference": self.reference,
            "Task": self.task, "Details": self.details, "Tags": self.tags,
            "Target": self.target.isoformat() if self.target else "",
            "Assigned": self.assigned, "Priority": str(int(self.priority)),
            "Status": self.status.value, "Notes": self.notes,
        }

    @classmethod
    def from_record(cls, row: Mapping[str, Any]) -> Task:
        target = str(row.get("Target", "")).strip()
        return cls(
            id=str(row.get("ID", "")).strip(), task=str(row.get("Task", "")),
            category=str(row.get("Category", "")), reference=str(row.get("Reference", "")),
            details=str(row.get("Details", "")), tags=str(row.get("Tags", "")),
            target=date.fromisoformat(target) if target else None,
            assigned=str(row.get("Assigned", "")),
            priority=Priority(int(row.get("Priority") or Priority.SOMEDAY)),
            status=Status(str(row.get("Status") or Status.NONE.value)),
            notes=str(row.get("Notes", "")),
        )

