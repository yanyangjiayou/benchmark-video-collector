"""Persist platform safety pauses across local app restarts."""
from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path


class PlatformAccessGuard:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def _read(self) -> dict[str, dict[str, str]]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def get(self, platform: str) -> dict[str, str] | None:
        with self._lock:
            value = self._read().get(platform)
            return dict(value) if isinstance(value, dict) else None

    def block(self, platform: str, reason: str) -> dict[str, str]:
        with self._lock:
            data = self._read()
            entry = {
                "reason": reason,
                "detected_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            }
            data[platform] = entry
            self._write(data)
            return dict(entry)

    def clear(self, platform: str) -> None:
        with self._lock:
            data = self._read()
            data.pop(platform, None)
            self._write(data)

    def _write(self, data: dict[str, dict[str, str]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)
