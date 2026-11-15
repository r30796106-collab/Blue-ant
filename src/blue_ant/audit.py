"""Append-only JSON Lines audit events with a tamper-evident hash chain."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import re
import stat
import threading
from typing import Any

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None


_ZERO_HASH = "0" * 64
_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_MAX_EVENT_BYTES = 1_000_000


@dataclass(frozen=True, slots=True)
class AuditVerification:
    valid: bool
    records: int
    last_hash: str
    error: str | None = None


def _reject_symlink_components(path: Path) -> None:
    for component in (path, *path.parents):
        if component.is_symlink():
            raise ValueError(f"audit path must not contain symlinks: {component}")


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    ).encode("utf-8")


def _last_record_hash(fd: int) -> str:
    """Read and validate the final JSONL record while the caller holds a lock."""
    end = os.lseek(fd, 0, os.SEEK_END)
    if end == 0:
        return _ZERO_HASH

    cursor = end
    tail = b""
    while cursor > 0:
        start = max(0, cursor - 4096)
        os.lseek(fd, start, os.SEEK_SET)
        tail = os.read(fd, cursor - start) + tail
        cursor = start
        stripped = tail.rstrip(b"\n")
        separator = stripped.rfind(b"\n")
        if separator >= 0:
            line = stripped[separator + 1:]
            break
        if cursor == 0:
            line = stripped
            break
        if len(stripped) > _MAX_EVENT_BYTES:
            raise ValueError("last audit record exceeds the 1 MB limit")
    else:
        line = tail.rstrip(b"\n")

    if not tail.endswith(b"\n") or tail.endswith(b"\n\n"):
        raise ValueError("audit log final record must end with exactly one newline")
    if not line or len(line) > _MAX_EVENT_BYTES:
        raise ValueError("audit log has an empty or oversized final record")
    try:
        record = json.loads(line.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("audit log final record is not valid UTF-8 JSON") from exc
    if not isinstance(record, dict):
        raise ValueError("audit log final record must be a JSON object")
    digest = record.get("record_hash")
    if not isinstance(digest, str) or not _HASH_PATTERN.fullmatch(digest):
        raise ValueError("audit log final record has no valid record_hash")
    previous = record.get("previous_hash")
    if not isinstance(previous, str) or not _HASH_PATTERN.fullmatch(previous):
        raise ValueError("audit log final record has no valid previous_hash")
    payload = dict(record)
    payload.pop("record_hash")
    expected = hashlib.sha256(_canonical_json(payload)).hexdigest()
    if digest != expected:
        raise ValueError("audit log final record hash mismatch")
    return digest


class AuditLog:
    """Append structured events with file/path guards and a verifiable hash chain.

    POSIX file locks coordinate independent writer instances/processes. On
    platforms without fcntl, writes remain thread-safe per AuditLog instance.
    """

    def __init__(self, path: str | Path) -> None:
        supplied_path = Path(path).expanduser()
        _reject_symlink_components(supplied_path)
        supplied_path.parent.mkdir(parents=True, exist_ok=True)
        _reject_symlink_components(supplied_path)
        if supplied_path.exists() and not supplied_path.is_file():
            raise ValueError("audit path must be a regular file")
        self.path = supplied_path.resolve(strict=False)
        self._lock = threading.Lock()

    def record(self, event: str, **details: Any) -> str:
        """Append one event and return its SHA-256 record hash."""
        if not isinstance(event, str) or not event.strip():
            raise ValueError("audit event must be a non-empty string")
        reserved = {"timestamp", "event", "previous_hash", "record_hash"} & details.keys()
        if reserved:
            raise ValueError("audit details cannot override reserved fields: " + ", ".join(sorted(reserved)))

        with self._lock:
            flags = os.O_RDWR | os.O_APPEND | os.O_CREAT
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            fd = os.open(self.path, flags, 0o600)
            locked = False
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    raise ValueError("audit path must be a regular file")
                if fcntl is not None:
                    fcntl.flock(fd, fcntl.LOCK_EX)
                    locked = True

                payload = {
                    **details,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "event": event,
                    "previous_hash": _last_record_hash(fd),
                }
                digest = hashlib.sha256(_canonical_json(payload)).hexdigest()
                record = {**payload, "record_hash": digest}
                encoded = json.dumps(record, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8") + b"\n"
                if len(encoded) > _MAX_EVENT_BYTES:
                    raise ValueError("audit event exceeds the 1 MB limit")

                os.lseek(fd, 0, os.SEEK_END)
                written = os.write(fd, encoded)
                if written != len(encoded):
                    raise OSError("short write while appending audit event")
                os.fsync(fd)
                return digest
            finally:
                if locked:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)

    def verify(self) -> AuditVerification:
        """Verify every record hash and previous-hash link in the JSONL file."""
        if not self.path.exists():
            return AuditVerification(True, 0, _ZERO_HASH)
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(self.path, flags)
        locked = False
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ValueError("audit path must be a regular file")
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_SH)
                locked = True

            previous = _ZERO_HASH
            count = 0
            with os.fdopen(os.dup(fd), "rb") as stream:
                for line_number, raw_line in enumerate(stream, start=1):
                    if len(raw_line) > _MAX_EVENT_BYTES:
                        return AuditVerification(False, count, previous, f"line {line_number} exceeds 1 MB")
                    if not raw_line.endswith(b"\n"):
                        return AuditVerification(False, count, previous, f"line {line_number} is not newline-terminated")
                    try:
                        record = json.loads(raw_line.decode("utf-8"))
                    except (UnicodeError, json.JSONDecodeError):
                        return AuditVerification(False, count, previous, f"line {line_number} is not valid UTF-8 JSON")
                    if not isinstance(record, dict):
                        return AuditVerification(False, count, previous, f"line {line_number} is not a JSON object")
                    digest = record.get("record_hash")
                    if not isinstance(digest, str) or not _HASH_PATTERN.fullmatch(digest):
                        return AuditVerification(False, count, previous, f"line {line_number} has an invalid record_hash")
                    if record.get("previous_hash") != previous:
                        return AuditVerification(False, count, previous, f"line {line_number} breaks the hash chain")
                    payload = dict(record)
                    payload.pop("record_hash")
                    expected = hashlib.sha256(_canonical_json(payload)).hexdigest()
                    if digest != expected:
                        return AuditVerification(False, count, previous, f"line {line_number} record hash mismatch")
                    previous = digest
                    count += 1
            return AuditVerification(True, count, previous)
        finally:
            if locked:
                fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
