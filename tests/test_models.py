from datetime import date
import json

import pytest

from taskr.app import target_date
from taskr.models.task import TASK_COLUMNS, Status, Task


def test_exact_schema_and_round_trip_preserves_tags():
    assert TASK_COLUMNS == ("ID", "Category", "Reference", "Task", "Details", "Target", "Assigned", "Priority", "Status", "Notes", "Tags")
    made = Task.new(user="alex", task="Ship", target=date(2026, 8, 6))
    record = made.to_record()
    assert record["Priority"] == record["Status"] == record["Notes"] == ""
    assert json.loads(record["Tags"])["source"] == "python_app"
    assert Task.from_record(record) == made


def test_dates_and_validation():
    assert target_date("EOD", date(2026, 8, 6)) == date(2026, 8, 6)
    assert target_date("EOW", date(2026, 8, 6)) == date(2026, 8, 9)
    assert target_date("EOM", date(2026, 8, 6)) == date(2026, 8, 31)
    with pytest.raises(ValueError): Task(task=" ")
    with pytest.raises(ValueError): Task(task="x", status="Done")
