"""Non-secret local preferences for the Apps Script client."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path


def default_path() -> Path:
    return Path(os.environ.get("TASKR_CONFIG", Path.home() / ".config/taskr/config.json"))


@dataclass(slots=True)
class AppConfig:
    api_url: str = ""
    user: str = ""
    categories: list[str] = field(default_factory=list)
    references: list[str] = field(default_factory=list)
    assigned: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path | None = None) -> AppConfig:
        path = path or default_path()
        data = json.loads(path.read_text()) if path.exists() else {}
        data["api_url"] = os.environ.get("TASKR_API_URL", data.get("api_url", ""))
        data["user"] = os.environ.get("TASKR_USER", data.get("user", ""))
        return cls(
            api_url=data.get("api_url", ""), user=data.get("user", ""),
            categories=list(data.get("categories", [])), references=list(data.get("references", [])),
            assigned=list(data.get("assigned", [])),
        )

    def remember(self, category: str, reference: str, assigned: str) -> None:
        for collection, value in ((self.categories, category), (self.references, reference), (self.assigned, assigned)):
            if value and value not in collection:
                collection.append(value)
                collection.sort(key=str.casefold)

    def save(self, path: Path | None = None) -> None:
        path = path or default_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2) + "\n")
