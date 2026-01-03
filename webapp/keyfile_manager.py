import json
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Dict, List


@dataclass
class KeyEntry:
    kid: str
    key: str


class KeyfileManager:
    def __init__(self, file_path: Path):
        self.file_path = file_path
        self._lock = Lock()

    def _load(self) -> Dict[str, str]:
        if not self.file_path.exists():
            return {}
        try:
            return json.loads(self.file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def upsert_keys(self, entries: List[KeyEntry]) -> None:
        normalized = {
            entry.kid.strip().lower(): entry.key.strip().lower()
            for entry in entries
            if entry.kid and entry.key
        }
        if not normalized:
            return
        with self._lock:
            existing = self._load()
            existing.update(normalized)
            self.file_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
