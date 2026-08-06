import json

from taskr.storage.config import AppConfig


def test_local_history_is_deduplicated_and_saved(tmp_path):
    path = tmp_path / "config.json"
    config = AppConfig(api_url="url", user="me")
    config.remember("Work", "R1", "Me"); config.remember("Work", "R1", "Me")
    config.save(path)
    assert AppConfig.load(path).categories == ["Work"]
    assert json.loads(path.read_text())["assigned"] == ["Me"]
