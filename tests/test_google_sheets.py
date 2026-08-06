import json

import pytest

from taskr.models.task import TASK_COLUMNS, Status, Task
from taskr.storage.google_sheets import AuditWriteError, GoogleSheetsTaskStore, LOG_COLUMNS


class Sheet:
    def __init__(self, headers):
        self.rows = [list(headers)]
        self.fail_append = False

    def row_values(self, number): return self.rows[number - 1]
    def get_all_values(self): return [row[:] for row in self.rows]
    def append_row(self, values, **kwargs):
        if self.fail_append: raise RuntimeError("offline")
        self.rows.append(values)
    def update(self, values, range_name, **kwargs):
        start = range_name.split(":", 1)[0]
        letters = "".join(c for c in start if c.isalpha())
        number = int("".join(c for c in start if c.isdigit()))
        column = 0
        for char in letters: column = column * 26 + ord(char) - 64
        while len(self.rows) < number: self.rows.append([])
        while len(self.rows[number - 1]) < column: self.rows[number - 1].append("")
        for offset, value in enumerate(values[0]):
            while len(self.rows[number - 1]) < column + offset: self.rows[number - 1].append("")
            self.rows[number - 1][column + offset - 1] = value
    def delete_rows(self, start_index, end_index=None): self.rows.pop(start_index - 1)


def test_crud_uses_reordered_headers_and_audits():
    db = Sheet(tuple(reversed(TASK_COLUMNS)))
    log = Sheet(("Operation", "After", "Event ID", "Task ID", "Before", "Timestamp", "Actor/Source"))
    store = GoogleSheetsTaskStore(db, log, actor="test")
    made = store.create(Task(task="First"))
    assert store.read(made.id).task == "First"
    changed = store.update(made.id, {"status": Status.COMPLETE})
    assert changed.status is Status.COMPLETE
    assert len(store.list()) == 1
    store.archive(made.id)
    assert store.read(made.id) is None
    assert [row[0] for row in log.rows[1:]] == ["CREATE", "UPDATE", "ARCHIVE"]
    after_index = log.rows[0].index("After")
    assert json.loads(log.rows[1][after_index])["Task"] == "First"


def test_partial_failure_exposes_idempotent_audit_retry():
    db, log = Sheet(TASK_COLUMNS), Sheet(LOG_COLUMNS)
    log.fail_append = True
    store = GoogleSheetsTaskStore(db, log)
    with pytest.raises(AuditWriteError) as caught:
        store.create(Task(task="Persisted"))
    assert len(db.rows) == 2
    log.fail_append = False
    store.retry_audit(caught.value.event)
    store.retry_audit(caught.value.event)
    assert len(log.rows) == 2
