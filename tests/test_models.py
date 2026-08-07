from datetime import date
import json

import pytest

from taskr.app import target_date, task_matches, window_title
from taskr.models.task import TASK_COLUMNS, Status, Task
from taskr.storage.config import ViewConfig


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


def test_window_title_includes_timestamp_version():
    assert window_title("260807123456") == "taskr - version: 260807123456"


def test_configured_view_filters_and_parent_tag_round_trip():
    task = Task(task="Child", category="Work", reference="R1", target=date(2026, 8, 6),
                status=Status.BLOCKED, tags={"parent": "parent-id"})
    view = ViewConfig(category="Work", reference="R1", date_from="2026-08-01",
                      date_to="2026-08-31", status="Blocked")
    assert task_matches(task, view)
    assert Task.from_record(task.to_record()).tags["parent"] == "parent-id"
    view.status = "Complete"
    assert not task_matches(task, view)


def test_column_filters_are_combined_and_support_blank_values():
    task = Task(id="1", task="Ship", assigned="Sam", priority="", status=Status.BLOCKED)
    assert task_matches(task, ViewConfig(column_filters={
        "Assigned": ["Sam", "Lee"], "Priority": [""], "Status": ["Blocked"],
    }))
    assert not task_matches(task, ViewConfig(column_filters={"Assigned": ["Lee"]}))
    assert not task_matches(task, ViewConfig(column_filters={"Priority": []}))
