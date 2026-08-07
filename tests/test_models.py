from datetime import date
import json

import pytest

from taskr.app import available_filter_options, target_date, task_matches, window_title
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


def test_filter_options_are_constrained_by_the_other_active_filters():
    tasks = [
        Task(task="A", category="Work", reference="AC", target=date(2026, 8, 6), status=Status.BLOCKED),
        Task(task="B", category="Work", reference="BD", target=date(2026, 8, 7), status=Status.COMPLETE),
        Task(task="C", category="Home", reference="AC", target=date(2026, 8, 8), status=Status.COMPLETE),
    ]
    view = ViewConfig(category="Work", reference="AC")
    assert available_filter_options(tasks, view, "reference") == ["", "AC", "BD"]
    assert available_filter_options(tasks, view, "status") == ["", "Blocked"]
    assert available_filter_options(tasks, view, "date_from") == ["", "2026-08-06"]
