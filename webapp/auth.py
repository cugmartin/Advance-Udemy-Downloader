import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import threading
from typing import Dict, Optional


@dataclass
class SessionToken:
    token: str
    username: str
    expires_at: datetime


class TokenManager:
    def __init__(self, ttl_seconds: int, storage_path: Optional[Path] = None):
        self.ttl_seconds = ttl_seconds
        self.storage_path = storage_path
        self._tokens: Dict[str, SessionToken] = {}
        self._lock = threading.Lock()
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        if not self.storage_path:
            return
        try:
            if not self.storage_path.exists():
                return
            raw = self.storage_path.read_text(encoding="utf-8")
            if not raw.strip():
                return
            data = json.loads(raw)
            tokens = data.get("tokens", {}) if isinstance(data, dict) else {}
            now = datetime.now(timezone.utc)
            loaded: Dict[str, SessionToken] = {}
            for token_value, entry in tokens.items():
                if not isinstance(entry, dict):
                    continue
                username = entry.get("username")
                expires_at = entry.get("expires_at")
                if not token_value or not username or not expires_at:
                    continue
                try:
                    exp = datetime.fromisoformat(expires_at)
                    if exp.tzinfo is None:
                        exp = exp.replace(tzinfo=timezone.utc)
                except Exception:
                    continue
                if exp < now:
                    continue
                loaded[token_value] = SessionToken(token=token_value, username=username, expires_at=exp)
            with self._lock:
                self._tokens = loaded
            self._save_to_disk()
        except Exception:
            return

    def _save_to_disk(self) -> None:
        if not self.storage_path:
            return
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                data = {
                    "tokens": {
                        token: {"username": st.username, "expires_at": st.expires_at.isoformat()}
                        for token, st in self._tokens.items()
                    }
                }
            tmp_path = self.storage_path.with_suffix(self.storage_path.suffix + ".tmp")
            tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp_path.replace(self.storage_path)
        except Exception:
            return

    def issue_token(self, username: str) -> SessionToken:
        token_value = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=self.ttl_seconds)
        token = SessionToken(token=token_value, username=username, expires_at=expires_at)
        with self._lock:
            self._tokens[token_value] = token
        self._save_to_disk()
        return token

    def validate(self, token_value: str) -> Optional[SessionToken]:
        with self._lock:
            token = self._tokens.get(token_value)
        if not token:
            return None
        if token.expires_at < datetime.now(timezone.utc):
            with self._lock:
                self._tokens.pop(token_value, None)
            self._save_to_disk()
            return None
        return token

    def revoke(self, token_value: str) -> None:
        with self._lock:
            self._tokens.pop(token_value, None)
        self._save_to_disk()
