"""Deterministic worker limits from caller-supplied or detected device capacity."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


_MAX_CPUSET_TEXT_BYTES = 65_536


@dataclass(frozen=True, slots=True)
class ResourceSnapshot:
    """A point-in-time capacity snapshot; detection is explicit and opt-in."""

    cpu_count: int
    available_memory_bytes: int

    def __post_init__(self) -> None:
        if self.cpu_count < 1:
            raise ValueError("cpu_count must be at least 1")
        if self.available_memory_bytes < 0:
            raise ValueError("available_memory_bytes must not be negative")

    @classmethod
    def detect(
        cls,
        *,
        proc_root: str | Path = "/proc",
        cgroup_root: str | Path = "/sys/fs/cgroup",
    ) -> "ResourceSnapshot":
        """Detect Linux capacity using procfs and common cgroup v1/v2 files.

        This method performs a one-time read only when explicitly called. It
        starts with host MemAvailable/CPU count, then applies tighter cgroup
        memory, CPU quota, and cpuset limits when those files are available. Unsupported
        hosts or missing MemAvailable data fail closed with RuntimeError.
        """
        proc = Path(proc_root)
        cgroup = Path(cgroup_root)
        meminfo = _read_meminfo(proc / "meminfo")
        host_available = meminfo.get("MemAvailable")
        host_total = meminfo.get("MemTotal")
        if host_available is None or host_total is None:
            raise RuntimeError("Linux /proc/meminfo must provide MemAvailable and MemTotal")

        available_memory = host_available * 1024
        total_memory = host_total * 1024
        cpu_count = max(1, os.cpu_count() or 1)

        v2_dirs = _cgroup_v2_dirs(proc, cgroup)
        v2_memory_limits_found = False
        for directory in v2_dirs:
            memory_limit = _read_first_int(directory / "memory.max")
            memory_current = _read_first_int(directory / "memory.current")
            if memory_limit is None or memory_current is None:
                continue
            # Some cgroup v1 systems use a very large integer for "unlimited".
            if memory_limit > 2 * total_memory:
                continue
            v2_memory_limits_found = True
            available_memory = min(
                available_memory, max(0, memory_limit - memory_current)
            )

        if not v2_memory_limits_found:
            for directory in _cgroup_v1_dirs(proc, cgroup, "memory"):
                memory_limit = _read_first_int(directory / "memory.limit_in_bytes")
                memory_current = _read_first_int(directory / "memory.usage_in_bytes")
                if memory_limit is None or memory_current is None:
                    continue
                if memory_limit > 2 * total_memory:
                    continue
                available_memory = min(
                    available_memory, max(0, memory_limit - memory_current)
                )

        v2_cpu_limits = [
            quota
            for directory in v2_dirs
            if (quota := _read_v2_cpu_quota(directory)) is not None
        ]
        if v2_cpu_limits:
            cpu_count = min(
                cpu_count,
                *(max(1, quota // period) for quota, period in v2_cpu_limits),
            )
        else:
            v1_cpu_limits = [
                quota
                for directory in _cgroup_v1_dirs(proc, cgroup, "cpu")
                if (quota := _read_v1_cpu_quota(directory)) is not None
            ]
            if v1_cpu_limits:
                cpu_count = min(
                    cpu_count,
                    *(max(1, quota // period) for quota, period in v1_cpu_limits),
                )

        v2_cpuset_limits = [
            count
            for directory in v2_dirs
            if (count := _read_cpu_set_count(directory / "cpuset.cpus.effective")) is not None
        ]
        if v2_cpuset_limits:
            cpu_count = min(cpu_count, *v2_cpuset_limits)
        else:
            v1_cpuset_limits = [
                count
                for directory in _cgroup_v1_dirs(proc, cgroup, "cpuset")
                if (count := _read_cpu_set_count(directory / "cpuset.cpus")) is not None
            ]
            if v1_cpuset_limits:
                cpu_count = min(cpu_count, *v1_cpuset_limits)

        return cls(cpu_count=cpu_count, available_memory_bytes=available_memory)


def _read_meminfo(path: Path) -> dict[str, int]:
    values: dict[str, int] = {}
    try:
        lines = path.read_text(encoding="ascii").splitlines()
    except OSError as exc:
        raise RuntimeError("Linux /proc/meminfo is unavailable") from exc
    for line in lines:
        key, separator, remainder = line.partition(":")
        if not separator:
            continue
        fields = remainder.split()
        if fields and fields[0].isdigit():
            values[key] = int(fields[0])
    return values


def _cgroup_v2_dirs(proc_root: Path, cgroup_root: Path) -> tuple[Path, ...]:
    """Return the visible cgroup v2 mount root and this process's ancestors."""
    try:
        lines = (proc_root / "self" / "cgroup").read_text(encoding="ascii").splitlines()
    except OSError:
        return (cgroup_root,)

    membership = next(
        (line.partition("::")[2] for line in lines if line.startswith("0::")),
        None,
    )
    if membership is None:
        return (cgroup_root,)

    process_path = PurePosixPath(membership)
    if not process_path.is_absolute() or ".." in process_path.parts:
        return (cgroup_root,)

    mount_root = PurePosixPath("/")
    mountinfo = proc_root / "self" / "mountinfo"
    try:
        mount_lines = mountinfo.read_text(encoding="ascii").splitlines()
    except OSError:
        mount_lines = []

    for line in mount_lines:
        before, separator, after = line.partition(" - ")
        if not separator:
            continue
        left = before.split()
        right = after.split()
        if len(left) < 5 or not right or right[0] != "cgroup2":
            continue
        mountpoint = Path(_unescape_mountinfo(left[4]))
        if mountpoint == cgroup_root:
            candidate_root = PurePosixPath(_unescape_mountinfo(left[3]))
            if candidate_root.is_absolute() and ".." not in candidate_root.parts:
                mount_root = candidate_root
            break

    try:
        relative = process_path.relative_to(mount_root)
    except ValueError:
        return (cgroup_root,)

    if any(part in {"", ".", ".."} for part in relative.parts):
        return (cgroup_root,)

    directories = [cgroup_root]
    current = cgroup_root
    for part in relative.parts:
        current = current / part
        directories.append(current)
    return tuple(directories)


def _cgroup_v1_dirs(
    proc_root: Path, cgroup_root: Path, controller: str
) -> tuple[Path, ...]:
    """Return the visible cgroup v1 controller mount and process ancestors."""
    controller_root = cgroup_root / controller
    try:
        lines = (proc_root / "self" / "cgroup").read_text(encoding="ascii").splitlines()
    except OSError:
        return (controller_root,)

    membership = None
    for line in lines:
        _, separator, remainder = line.partition(":")
        if not separator:
            continue
        controllers, separator, path = remainder.partition(":")
        if not separator:
            continue
        names = controllers.split(",")
        if controller in names or (controller == "cpu" and "cpuacct" in names):
            membership = path
            break
    if membership is None:
        return (controller_root,)

    process_path = PurePosixPath(membership)
    if not process_path.is_absolute() or ".." in process_path.parts:
        return (controller_root,)

    mount_root = PurePosixPath("/")
    try:
        mount_lines = (proc_root / "self" / "mountinfo").read_text(
            encoding="ascii"
        ).splitlines()
    except OSError:
        mount_lines = []

    for line in mount_lines:
        before, separator, after = line.partition(" - ")
        if not separator:
            continue
        left, right = before.split(), after.split()
        if len(left) < 5 or not right or right[0] != "cgroup":
            continue
        options = set(right[2].split(",")) if len(right) > 2 else set()
        if controller not in options and not (
            controller == "cpu" and "cpuacct" in options
        ):
            continue
        if Path(_unescape_mountinfo(left[4])) != controller_root:
            continue
        candidate = PurePosixPath(_unescape_mountinfo(left[3]))
        if candidate.is_absolute() and ".." not in candidate.parts:
            mount_root = candidate
        break

    try:
        relative = process_path.relative_to(mount_root)
    except ValueError:
        return (controller_root,)
    if any(part in {"", ".", ".."} for part in relative.parts):
        return (controller_root,)

    directories = [controller_root]
    current = controller_root
    for part in relative.parts:
        current = current / part
        directories.append(current)
    return tuple(directories)



def _read_cpu_set_count(path: Path) -> int | None:
    """Return the number of CPUs in a Linux cpulist, or None if unavailable/invalid."""
    try:
        with path.open("r", encoding="ascii") as stream:
            value = stream.read(_MAX_CPUSET_TEXT_BYTES + 1)
    except (OSError, UnicodeError):
        return None
    if len(value) > _MAX_CPUSET_TEXT_BYTES:
        return None
    value = value.strip()
    if not value:
        return None

    ranges: list[tuple[int, int]] = []
    for item in value.split(","):
        if "-" in item:
            parts = item.split("-")
            if len(parts) != 2 or not all(part.isdigit() for part in parts):
                return None
            try:
                start, end = map(int, parts)
            except ValueError:
                # Extremely long digit strings can exceed Python's safe
                # integer-conversion limit; malformed host data is ignored.
                return None
            if end < start:
                return None
        elif item.isdigit():
            try:
                start = end = int(item)
            except ValueError:
                return None
        else:
            return None
        ranges.append((start, end))

    ranges.sort()
    count = 0
    last_end = -1
    for start, end in ranges:
        if end <= last_end:
            continue
        count += end - max(start, last_end + 1) + 1
        last_end = end
    return count if count > 0 else None


def _read_v1_cpu_quota(directory: Path) -> tuple[int, int] | None:
    quota = _read_first_int(directory / "cpu.cfs_quota_us")
    period = _read_first_int(directory / "cpu.cfs_period_us")
    if quota is not None and period is not None and quota > 0 and period > 0:
        return quota, period
    return None


def _unescape_mountinfo(value: str) -> str:
    """Decode the octal path escapes used by procfs mountinfo."""
    return re.sub(
        r"\\([0-7]{3})",
        lambda match: chr(int(match.group(1), 8)),
        value,
    )


def _read_v2_cpu_quota(directory: Path) -> tuple[int, int] | None:
    try:
        fields = (directory / "cpu.max").read_text(encoding="ascii").split()
        if len(fields) != 2 or fields[0] == "max":
            return None
        quota, period = int(fields[0]), int(fields[1])
    except (OSError, ValueError):
        return None
    if quota > 0 and period > 0:
        return quota, period
    return None


def _read_first_int(*paths: Path) -> int | None:
    for path in paths:
        try:
            value = path.read_text(encoding="ascii").strip()
        except OSError:
            continue
        if value == "max":
            return None
        try:
            parsed = int(value)
        except ValueError:
            continue
        if parsed >= 0:
            return parsed
    return None


def _read_cpu_quota(cgroup_root: Path) -> tuple[int, int] | None:
    try:
        fields = (cgroup_root / "cpu.max").read_text(encoding="ascii").split()
        if len(fields) == 2 and fields[0] != "max":
            quota, period = int(fields[0]), int(fields[1])
            if quota > 0 and period > 0:
                return quota, period
    except (OSError, ValueError):
        pass

    quota = _read_first_int(cgroup_root / "cpu" / "cpu.cfs_quota_us")
    period = _read_first_int(cgroup_root / "cpu" / "cpu.cfs_period_us")
    if quota is not None and period is not None and quota > 0 and period > 0:
        return quota, period
    return None


@dataclass(frozen=True, slots=True)
class ResourcePolicy:
    """Calculate a conservative worker cap without probing the host itself."""

    max_workers: int = 4
    reserve_memory_bytes: int = 512 * 1024 * 1024
    memory_per_worker_bytes: int = 256 * 1024 * 1024

    def __post_init__(self) -> None:
        if self.max_workers < 1:
            raise ValueError("max_workers must be at least 1")
        if self.reserve_memory_bytes < 0:
            raise ValueError("reserve_memory_bytes must not be negative")
        if self.memory_per_worker_bytes < 1:
            raise ValueError("memory_per_worker_bytes must be at least 1")

    def worker_limit(self, snapshot: ResourceSnapshot) -> int:
        """Return a safe positive worker cap; never exceed configured or CPU limits."""
        usable = max(0, snapshot.available_memory_bytes - self.reserve_memory_bytes)
        memory_cap = usable // self.memory_per_worker_bytes
        if memory_cap < 1:
            raise ValueError("insufficient available memory for one worker")
        return min(self.max_workers, snapshot.cpu_count, memory_cap)
