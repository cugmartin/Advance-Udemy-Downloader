import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional


@dataclass
class SessionToken:
    token: str
    username: str
    expires_at: datetime


class TokenManager:
    def __init__(self, ttl_seconds: int):
        self.ttl_seconds = ttl_seconds
        self._tokens: Dict[str, SessionToken] = {}

    def issue_token(self, username: str) -> SessionToken:
        token_value = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=self.ttl_seconds)
        token = SessionToken(token=token_value, username=username, expires_at=expires_at)
        self._tokens[token_value] = token
        return token

    def validate(self, token_value: str) -> Optional[SessionToken]:
        token = self._tokens.get(token_value)
        if not token:
            return None
        if token.expires_at < datetime.now(timezone.utc):
            self._tokens.pop(token_value, None)
            return None
        return token

    def revoke(self, token_value: str) -> None:
        self._tokens.pop(token_value, None)
