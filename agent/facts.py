"""Persistent fact store — key/value memory that survives across conversations.

Stored as a simple JSON file at $IAGENT_HOME/facts.json.
Values can be any JSON-serialisable type; the API surface exposed to tools
keeps it to plain strings for simplicity.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

_IAGENT_HOME = Path(os.environ.get("IAGENT_HOME", Path.home() / ".iagent"))


class FactStore:
    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = path or (_IAGENT_HOME / "facts.json")

    def _load(self) -> dict:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text()) or {}
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _save(self, data: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def get(self, key: str) -> Optional[str]:
        return self._load().get(key)

    def set(self, key: str, value: str) -> None:
        data = self._load()
        data[key] = value
        self._save(data)

    def delete(self, key: str) -> bool:
        data = self._load()
        if key in data:
            del data[key]
            self._save(data)
            return True
        return False

    def all(self) -> dict:
        return self._load()


# Module-level singleton
_store: Optional[FactStore] = None


def get_store(path: Optional[Path] = None) -> FactStore:
    global _store
    if _store is None:
        _store = FactStore(path)
    return _store
