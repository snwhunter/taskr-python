import json

from taskr.storage.config import AppConfig, ViewConfig


def test_local_history_is_deduplicated_and_saved(tmp_path):
    path = tmp_path / "config.json"
    config = AppConfig(api_url="url", user="me")
    config.remember("Work", "R1", "Me"); config.remember("Work", "R1", "Me")
    config.save(path)
    assert AppConfig.load(path).categories == ["Work"]
    assert json.loads(path.read_text())["assigned"] == ["Me"]


def test_five_default_views_and_view_configuration_are_persisted(tmp_path):
    path = tmp_path / "config.json"
    config = AppConfig()
    assert [view.name for view in config.views] == [f"View {number}" for number in range(1, 6)]
    config.views = [ViewConfig(name="My work", category="Work", status="Blocked",
                               column_filters={"Assigned": ["Me", "Sam"], "Priority": ["High"]})]
    config.save(path)
    assert AppConfig.load(path).views == config.views
