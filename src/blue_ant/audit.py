"""Append-only JSON Lines audit events with guarded file handling."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
import stat
import threading
from typing import Any


def _reject_symlink_components(path: Path) -> None:
    for component in (path, *path.parents):
        if component.is_symlink():
            raise ValueError(f"audit path must not contain symlinks: {component}")


class AuditLog:
    """Append structured audit events without following symlinked paths."""

    def __init__(self, path: str | Path) -> None:
        supplied_path = Path(path).expanduser()
        _reject_symlink_components(supplied_path)
        supplied_path.parent.mkdir(parents=True, exist_ok=True)
        _reject_symlink_components(supplied_path)
        if supplied_path.exists() and not supplied_path.is_file():
            raise ValueError("audit path must be a regular file")
        self.path = supplied_path.resolve(strict=False)
        self._lock = threading.Lock()

    def record(self, event: str, **details: Any) -> None:
        """Append one event; callers cannot override reserved audit metadata."""
        if not isinstance(event, str) or not event.strip():
            raise ValueError("audit event must be a non-empty string")
        reserved = {"timestamp", "event"} & details.keys()
        if reserved:
            raise ValueError("audit details cannot override reserved fields: " + ", ".join(sorted(reserved)))

        payload = {
            **details,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
        }
        encoded = (json.dumps(payload, sort_keys=True, default=str) + "\\n").encode("utf-8")

        with self._lock:
            flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            fd = os.open(self.path, flags, 0o600)
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    raise ValueError("audit path must be a regular file")
                written = os.write(fd, encoded)
                if written != len(encoded):
                    raise OSError("short write while appending audit event")
                os.fsync(fd)
            finally:
                os.close(fd)
