import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import List, Optional


@dataclass
class HistoryItem:
    task_id: str
    course_url: str
    started_at: str
    finished_at: str
    status: str
    message: str
    is_drm: Optional[bool] = None
    article_status: Optional[str] = None
    article_started_at: Optional[str] = None
    article_finished_at: Optional[str] = None
    article_message: Optional[str] = None


class HistoryStore:
    def __init__(self, file_path: Path, limit: int = 10):
        self.file_path = file_path
        self.limit = limit
        self._lock = Lock()
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> List[dict]:
        if not self.file_path.exists():
            return []
        try:
            return json.loads(self.file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []

    def list_items(self) -> List[dict]:
        with self._lock:
            return self._load()

    def get(self, task_id: str) -> Optional[dict]:
        with self._lock:
            for item in self._load():
                if item.get("task_id") == task_id:
                    return item
        return None

    def add(self, item: HistoryItem) -> None:
        with self._lock:
            items = self._load()
            items.insert(0, asdict(item))
            del items[self.limit :]
            self.file_path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

    def update(self, task_id: str, updates: dict) -> Optional[dict]:
        with self._lock:
            items = self._load()
            for idx, item in enumerate(items):
                if item.get("task_id") == task_id:
                    new_item = {**item, **updates}
                    items[idx] = new_item
                    self.file_path.write_text(
                        json.dumps(items, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    return new_item
        return None

    def clear(self) -> None:
        with self._lock:
            self.file_path.write_text("[]", encoding="utf-8")
