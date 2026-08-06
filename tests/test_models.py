from datetime import date
import uuid

import pytest

from taskr.models.task import Priority, Status, Task


def test_task_round_trip_and_timestamp_uuid():
    task = Task(task="Ship", target=date(2026, 8, 6), priority=Priority.HIGH, status=Status.IN_PROGRESS).with_id()
    assert uuid.UUID(task.id).version == 7
    assert Task.from_record(task.to_record()) == task


def test_rejects_non_v7_id():
    with pytest.raises(ValueError, match="UUIDv7"):
        Task(task="Bad", id=str(uuid.uuid4()))

