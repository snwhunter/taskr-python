"""Taskr's canonical representation of the existing Tasks sheet."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from enum import Enum
import json
import re
from typing import Any, Mapping


# This order is an external contract: it is the order of the existing Sheet.
TASK_COLUMNS = (
    "ID", "Category", "Reference", "Task", "Details", "Target", "Assigned",
    "Priority", "Status", "Notes", "Tags",
)
VISIBLE_COLUMNS = TASK_COLUMNS[:-1]
ID_PATTERN = re.compile(r"^\d{12}$")


class Status(str, Enum):
    """Values already used by the project; blank is the unstarted state."""

    NONE = ""
    IN_PROGRESS = "InProgress"
    BLOCKED = "Blocked"
    COMPLETE = "Complete"


def creation_timestamp_id(now: datetime | None = None) -> str:
    """Return a local creation timestamp ID in YYMMDDHHmmSS format."""
    return (now or datetime.now()).strftime("%y%m%d%H%M%S")


@dataclass(frozen=True, slots=True)
class Task:
    task: str
    id: str = ""
    category: str = ""
    reference: str = ""
    details: str = ""
    target: date | None = None
    assigned: str = ""
    priority: str = ""
    status: Status = Status.NONE
    notes: str = ""
    tags: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.task.strip():
            raise ValueError("Task must not be blank")
        if not isinstance(self.status, Status):
            object.__setattr__(self, "status", Status(self.status))
        if self.id and not ID_PATTERN.fullmatch(self.id):
            raise ValueError("Task ID must use YYMMDDHHmmSS format")

    def with_id(self) -> Task:
        return self if self.id else replace(self, id=creation_timestamp_id())

    def to_record(self) -> dict[str, str]:
        tags = json.dumps(dict(self.tags or {}), separators=(",", ":"), sort_keys=True)
        return {
            "ID": self.id, "Category": self.category, "Reference": self.reference,
            "Task": self.task, "Details": self.details,
            "Target": self.target.isoformat() if self.target else "",
            "Assigned": self.assigned, "Priority": self.priority,
            "Status": self.status.value, "Notes": self.notes, "Tags": tags,
        }

    @classmethod
    def from_record(cls, row: Mapping[str, Any]) -> Task:
        raw_tags = row.get("Tags") or "{}"
        tags = raw_tags if isinstance(raw_tags, Mapping) else json.loads(str(raw_tags))
        target = str(row.get("Target") or "").strip()
        return cls(
            id=str(row.get("ID") or "").strip(), category=str(row.get("Category") or ""),
            reference=str(row.get("Reference") or ""), task=str(row.get("Task") or ""),
            details=str(row.get("Details") or ""), target=date.fromisoformat(target) if target else None,
            assigned=str(row.get("Assigned") or ""), priority=str(row.get("Priority") or ""),
            status=Status(str(row.get("Status") or "")), notes=str(row.get("Notes") or ""),
            tags=dict(tags),
        )

    @classmethod
    def new(cls, *, user: str, **values: Any) -> Task:
        tags = {"created_by": user, "source": "python_app", "created_at": datetime.now(timezone.utc).isoformat()}
        return cls(tags=tags, **values).with_id()
