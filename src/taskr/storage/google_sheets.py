"""Header-driven Google Sheets task repository with append-only auditing."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import json
from typing import Any, Mapping, Protocol

from taskr.models.task import TASK_COLUMNS, Task, timestamp_uuid


LOG_COLUMNS = ("Event ID", "Timestamp", "Actor/Source", "Operation", "Task ID", "Before", "After")


class Worksheet(Protocol):
    def row_values(self, row: int) -> list[str]: ...
    def get_all_values(self) -> list[list[str]]: ...
    def append_row(self, values: list[str], **kwargs: Any) -> Any: ...
    def update(self, values: list[list[str]], range_name: str, **kwargs: Any) -> Any: ...
    def delete_rows(self, start_index: int, end_index: int | None = None) -> Any: ...


@dataclass(frozen=True, slots=True)
class AuditEvent:
    event_id: str
    timestamp: str
    actor: str
    operation: str
    task_id: str
    before: Mapping[str, str] | None
    after: Mapping[str, str] | None

    def row(self) -> list[str]:
        dump = lambda value: json.dumps(value, sort_keys=True, separators=(",", ":")) if value is not None else ""
        return [self.event_id, self.timestamp, self.actor, self.operation, self.task_id, dump(self.before), dump(self.after)]


class AuditWriteError(RuntimeError):
    """Task data changed, but its audit append failed; ``event`` can be retried."""

    def __init__(self, event: AuditEvent) -> None:
        super().__init__(f"task write succeeded but audit event {event.event_id} did not")
        self.event = event


def _column_name(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


class GoogleSheetsTaskStore:
    """CRUD store. Coordinates are calculated from current header names each time."""

    def __init__(self, db: Worksheet, log: Worksheet, actor: str = "taskr") -> None:
        self.db, self.log, self.actor = db, log, actor

    def _headers(self, sheet: Worksheet, required: tuple[str, ...]) -> dict[str, int]:
        headers = sheet.row_values(1)
        duplicates = {h for h in headers if h and headers.count(h) > 1}
        missing = set(required) - set(headers)
        if missing or duplicates:
            raise ValueError(f"invalid headers; missing={sorted(missing)}, duplicates={sorted(duplicates)}")
        return {name: headers.index(name) + 1 for name in required}

    def _rows(self) -> list[tuple[int, Task]]:
        columns = self._headers(self.db, TASK_COLUMNS)
        values = self.db.get_all_values()[1:]
        result = []
        for number, row in enumerate(values, 2):
            record = {name: row[index - 1] if index <= len(row) else "" for name, index in columns.items()}
            if record["ID"]:
                result.append((number, Task.from_record(record)))
        return result

    def list(self) -> list[Task]:
        return [task for _, task in self._rows()]

    def read(self, task_id: str) -> Task | None:
        return next((task for _, task in self._rows() if task.id == task_id), None)

    def create(self, task: Task) -> Task:
        created = task.with_id()
        if self.read(created.id):
            raise ValueError(f"duplicate task ID: {created.id}")
        columns = self._headers(self.db, TASK_COLUMNS)
        width = max(columns.values())
        record = created.to_record()
        row = [""] * width
        for name, value in record.items():
            row[columns[name] - 1] = value
        self.db.append_row(row, value_input_option="RAW")
        self._audit("CREATE", created.id, None, record)
        return created

    def update(self, task_id: str, changes: Mapping[str, Any] | Task) -> Task:
        found = next(((row, task) for row, task in self._rows() if task.id == task_id), None)
        if not found:
            raise KeyError(task_id)
        row_number, old = found
        if isinstance(changes, Task):
            new = changes
            if new.id != task_id:
                raise ValueError("an update cannot change ID")
        else:
            if "id" in changes and changes["id"] != task_id:
                raise ValueError("an update cannot change ID")
            new = replace(old, **changes)
        columns = self._headers(self.db, TASK_COLUMNS)
        record = new.to_record()
        row = [""] * max(columns.values())
        for name, value in record.items():
            row[columns[name] - 1] = value
        row_range = f"A{row_number}:{_column_name(len(row))}{row_number}"
        self.db.update([row], range_name=row_range, value_input_option="RAW")
        self._audit("UPDATE", task_id, old.to_record(), record)
        return new

    def archive(self, task_id: str) -> Task:
        return self._remove(task_id, "ARCHIVE")

    def delete(self, task_id: str) -> Task:
        return self._remove(task_id, "DELETE")

    def _remove(self, task_id: str, operation: str) -> Task:
        found = next(((row, task) for row, task in self._rows() if task.id == task_id), None)
        if not found:
            raise KeyError(task_id)
        row, task = found
        self.db.delete_rows(row)
        self._audit(operation, task_id, task.to_record(), None)
        return task

    def _audit(self, operation: str, task_id: str, before: Mapping[str, str] | None, after: Mapping[str, str] | None) -> None:
        event = AuditEvent(timestamp_uuid(), datetime.now(timezone.utc).isoformat(), self.actor, operation, task_id, before, after)
        try:
            self.retry_audit(event)
        except Exception as error:
            raise AuditWriteError(event) from error

    def retry_audit(self, event: AuditEvent) -> None:
        """Idempotently append an event, allowing recovery from a partial mutation."""
        columns = self._headers(self.log, LOG_COLUMNS)
        event_id_column = columns["Event ID"] - 1
        existing = self.log.get_all_values()[1:]
        if any(len(row) > event_id_column and row[event_id_column] == event.event_id for row in existing):
            return
        width = max(columns.values())
        row = [""] * width
        for name, value in zip(LOG_COLUMNS, event.row(), strict=True):
            row[columns[name] - 1] = value
        self.log.append_row(row, value_input_option="RAW")
