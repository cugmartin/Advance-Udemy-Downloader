from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests


@dataclass
class WordPressClient:
    wordpress_url: str
    username: str
    app_password: str
    disable_proxy: bool = False

    def __post_init__(self) -> None:
        self.api_base = self.wordpress_url.rstrip("/") + "/wp-json/wp/v2"
        self._session = requests.Session()
        self._session.auth = (self.username, self.app_password)
        if self.disable_proxy:
            self._session.trust_env = False

    def create_post(self, title: str, content: str, status: str = "draft") -> Dict[str, Any]:
        payload = {
            "title": title,
            "content": content,
            "status": status,
        }
        response = self._session.post(f"{self.api_base}/posts", json=payload)
        response.raise_for_status()
        return response.json()
