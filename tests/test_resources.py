from __future__ import annotations

import pytest

from blue_ant.resources import ResourcePolicy, ResourceSnapshot


def test_worker_limit_is_bounded_by_cpu_and_configuration() -> None:
    policy = ResourcePolicy(max_workers=8, reserve_memory_bytes=0, memory_per_worker_bytes=100)
    assert policy.worker_limit(ResourceSnapshot(cpu_count=3, available_memory_bytes=10_000)) == 3


def test_worker_limit_is_bounded_by_available_memory() -> None:
    policy = ResourcePolicy(max_workers=8, reserve_memory_bytes=500, memory_per_worker_bytes=250)
    assert policy.worker_limit(ResourceSnapshot(cpu_count=8, available_memory_bytes=1_000)) == 2


def test_worker_limit_rejects_memory_below_one_worker_reserve() -> None:
    policy = ResourcePolicy(max_workers=4, reserve_memory_bytes=1_000, memory_per_worker_bytes=500)
    with pytest.raises(ValueError, match="insufficient available memory"):
        policy.worker_limit(ResourceSnapshot(cpu_count=4, available_memory_bytes=100))


def test_invalid_resource_snapshot_is_rejected() -> None:
    with pytest.raises(ValueError):
        ResourceSnapshot(cpu_count=0, available_memory_bytes=100)


def test_worker_limit_respects_memory_cap_without_forcing_one_worker() -> None:
    policy = ResourcePolicy(max_workers=8, reserve_memory_bytes=500, memory_per_worker_bytes=250)
    assert policy.worker_limit(ResourceSnapshot(cpu_count=8, available_memory_bytes=1_000)) == 2


def test_detect_reads_host_capacity_and_tighter_cgroup_v2_limits(tmp_path, monkeypatch) -> None:
    proc = tmp_path / "proc"
    cgroup = tmp_path / "cgroup"
    proc.mkdir()
    cgroup.mkdir()
    (proc / "meminfo").write_text(
        "MemTotal: 8388608 kB\nMemAvailable: 2097152 kB\n", encoding="ascii"
    )
    (cgroup / "memory.max").write_text(str(1024 * 1024 * 1024), encoding="ascii")
    (cgroup / "memory.current").write_text(str(256 * 1024 * 1024), encoding="ascii")
    (cgroup / "cpu.max").write_text("250000 100000", encoding="ascii")
    monkeypatch.setattr("blue_ant.resources.os.cpu_count", lambda: 8)

    snapshot = ResourceSnapshot.detect(proc_root=proc, cgroup_root=cgroup)

    assert snapshot.cpu_count == 2
    assert snapshot.available_memory_bytes == 768 * 1024 * 1024


def test_detect_uses_host_capacity_when_cgroup_limits_are_unavailable(tmp_path, monkeypatch) -> None:
    proc = tmp_path / "proc"
    cgroup = tmp_path / "cgroup"
    proc.mkdir()
    cgroup.mkdir()
    (proc / "meminfo").write_text(
        "MemTotal: 4096000 kB\nMemAvailable: 1048576 kB\n", encoding="ascii"
    )
    monkeypatch.setattr("blue_ant.resources.os.cpu_count", lambda: 6)

    snapshot = ResourceSnapshot.detect(proc_root=proc, cgroup_root=cgroup)

    assert snapshot.cpu_count == 6
    assert snapshot.available_memory_bytes == 1024 * 1024 * 1024


def test_detect_supports_common_cgroup_v1_limits(tmp_path, monkeypatch) -> None:
    proc = tmp_path / "proc"
    cgroup = tmp_path / "cgroup"
    memory = cgroup / "memory"
    cpu = cgroup / "cpu"
    proc.mkdir()
    memory.mkdir(parents=True)
    cpu.mkdir()
    (proc / "meminfo").write_text(
        "MemTotal: 8388608 kB\nMemAvailable: 2097152 kB\n", encoding="ascii"
    )
    (memory / "memory.limit_in_bytes").write_text(str(2 * 1024**3), encoding="ascii")
    (memory / "memory.usage_in_bytes").write_text(str(512 * 1024**2), encoding="ascii")
    (cpu / "cpu.cfs_quota_us").write_text("150000", encoding="ascii")
    (cpu / "cpu.cfs_period_us").write_text("100000", encoding="ascii")
    monkeypatch.setattr("blue_ant.resources.os.cpu_count", lambda: 8)

    snapshot = ResourceSnapshot.detect(proc_root=proc, cgroup_root=cgroup)

    assert snapshot.cpu_count == 1
    assert snapshot.available_memory_bytes == 1536 * 1024 * 1024


def test_detect_fails_closed_when_memavailable_is_missing(tmp_path) -> None:
    proc = tmp_path / "proc"
    proc.mkdir()
    (proc / "meminfo").write_text("MemTotal: 1000 kB\n", encoding="ascii")

    with pytest.raises(RuntimeError, match="MemAvailable"):
        ResourceSnapshot.detect(proc_root=proc, cgroup_root=tmp_path / "cgroup")



def test_detect_ignores_cgroup_v1_unlimited_memory_sentinel(tmp_path, monkeypatch) -> None:
    proc = tmp_path / "proc"
    cgroup = tmp_path / "cgroup"
    memory = cgroup / "memory"
    cpu = cgroup / "cpu"
    proc.mkdir()
    memory.mkdir(parents=True)
    cpu.mkdir()
    host_available = 2 * 1024**3
    (proc / "meminfo").write_text(
        "MemTotal: 8388608 kB\nMemAvailable: 2097152 kB\n", encoding="ascii"
    )
    # Common cgroup v1 unlimited sentinel: far larger than physical RAM.
    (memory / "memory.limit_in_bytes").write_text(str(2**63 - 4096), encoding="ascii")
    (memory / "memory.usage_in_bytes").write_text(str(512 * 1024**2), encoding="ascii")
    (cpu / "cpu.cfs_quota_us").write_text("200000", encoding="ascii")
    (cpu / "cpu.cfs_period_us").write_text("100000", encoding="ascii")
    monkeypatch.setattr("blue_ant.resources.os.cpu_count", lambda: 8)

    snapshot = ResourceSnapshot.detect(proc_root=proc, cgroup_root=cgroup)

    assert snapshot.available_memory_bytes == host_available
    assert snapshot.cpu_count == 2



def test_detect_ignores_unlimited_cgroup_v2_memory_and_cpu_limits(tmp_path, monkeypatch) -> None:
    proc = tmp_path / "proc"
    cgroup = tmp_path / "cgroup"
    proc.mkdir()
    cgroup.mkdir()
    host_available = 1536 * 1024**2
    (proc / "meminfo").write_text(
        "MemTotal: 4194304 kB\nMemAvailable: 1572864 kB\n", encoding="ascii"
    )
    (cgroup / "memory.max").write_text("max", encoding="ascii")
    (cgroup / "memory.current").write_text(str(512 * 1024**2), encoding="ascii")
    (cgroup / "cpu.max").write_text("max 100000", encoding="ascii")
    monkeypatch.setattr("blue_ant.resources.os.cpu_count", lambda: 6)

    snapshot = ResourceSnapshot.detect(proc_root=proc, cgroup_root=cgroup)

    assert snapshot.available_memory_bytes == host_available
    assert snapshot.cpu_count == 6


def test_detect_applies_parent_limits_for_nested_cgroup_v2(tmp_path, monkeypatch) -> None:
    proc = tmp_path / "proc"
    cgroup = tmp_path / "cgroup"
    tenant = cgroup / "tenant"
    service = tenant / "service"
    (proc / "self").mkdir(parents=True)
    service.mkdir(parents=True)
    (proc / "meminfo").write_text(
        "MemTotal: 8388608 kB\nMemAvailable: 3145728 kB\n", encoding="ascii"
    )
    (proc / "self" / "cgroup").write_text("0::/tenant/service\n", encoding="ascii")

    # The intermediate parent is more restrictive than both the root and leaf.
    (cgroup / "memory.max").write_text(str(5 * 1024**3), encoding="ascii")
    (cgroup / "memory.current").write_text(str(1024**3), encoding="ascii")
    (tenant / "memory.max").write_text(str(2 * 1024**3), encoding="ascii")
    (tenant / "memory.current").write_text(str(1536 * 1024**2), encoding="ascii")
    (service / "memory.max").write_text(str(3 * 1024**3), encoding="ascii")
    (service / "memory.current").write_text(str(1024**3), encoding="ascii")

    (cgroup / "cpu.max").write_text("600000 100000", encoding="ascii")
    (tenant / "cpu.max").write_text("150000 100000", encoding="ascii")
    (service / "cpu.max").write_text("400000 100000", encoding="ascii")
    monkeypatch.setattr("blue_ant.resources.os.cpu_count", lambda: 8)

    snapshot = ResourceSnapshot.detect(proc_root=proc, cgroup_root=cgroup)

    assert snapshot.cpu_count == 1
    assert snapshot.available_memory_bytes == 512 * 1024**2


def test_detect_maps_membership_relative_to_non_root_cgroup2_mount(tmp_path, monkeypatch) -> None:
    proc = tmp_path / "proc"
    cgroup = tmp_path / "cgroup-mount"
    service = cgroup / "service"
    (proc / "self").mkdir(parents=True)
    service.mkdir(parents=True)
    (proc / "meminfo").write_text(
        "MemTotal: 8388608 kB\nMemAvailable: 3145728 kB\n", encoding="ascii"
    )
    (proc / "self" / "cgroup").write_text("0::/tenant/service\n", encoding="ascii")
    (proc / "self" / "mountinfo").write_text(
        f"29 23 0:26 /tenant {cgroup} rw,nosuid,nodev - cgroup2 cgroup rw\n",
        encoding="ascii",
    )

    # cgroup_root represents the mountpoint for /tenant, not hierarchy /.
    (cgroup / "memory.max").write_text(str(4 * 1024**3), encoding="ascii")
    (cgroup / "memory.current").write_text(str(1024**3), encoding="ascii")
    (service / "memory.max").write_text(str(2 * 1024**3), encoding="ascii")
    (service / "memory.current").write_text(str(1536 * 1024**2), encoding="ascii")
    (cgroup / "cpu.max").write_text("400000 100000", encoding="ascii")
    (service / "cpu.max").write_text("150000 100000", encoding="ascii")
    monkeypatch.setattr("blue_ant.resources.os.cpu_count", lambda: 8)

    snapshot = ResourceSnapshot.detect(proc_root=proc, cgroup_root=cgroup)

    assert snapshot.cpu_count == 1
    assert snapshot.available_memory_bytes == 512 * 1024**2



def test_detect_decodes_escaped_cgroup2_mountpoint(tmp_path, monkeypatch) -> None:
    proc = tmp_path / "proc"
    cgroup = tmp_path / "cgroup mount"
    service = cgroup / "service"
    (proc / "self").mkdir(parents=True)
    service.mkdir(parents=True)
    (proc / "meminfo").write_text(
        "MemTotal: 8388608 kB\nMemAvailable: 3145728 kB\n", encoding="ascii"
    )
    (proc / "self" / "cgroup").write_text("0::/tenant/service\n", encoding="ascii")
    escaped_mountpoint = str(cgroup).replace(" ", r"\040")
    (proc / "self" / "mountinfo").write_text(
        f"29 23 0:26 /tenant {escaped_mountpoint} rw - cgroup2 cgroup rw\n",
        encoding="ascii",
    )
    (cgroup / "memory.max").write_text(str(4 * 1024**3), encoding="ascii")
    (cgroup / "memory.current").write_text(str(1024**3), encoding="ascii")
    (service / "memory.max").write_text(str(2 * 1024**3), encoding="ascii")
    (service / "memory.current").write_text(str(1536 * 1024**2), encoding="ascii")
    monkeypatch.setattr("blue_ant.resources.os.cpu_count", lambda: 8)

    snapshot = ResourceSnapshot.detect(proc_root=proc, cgroup_root=cgroup)

    assert snapshot.available_memory_bytes == 512 * 1024**2


def test_detect_ignores_membership_outside_cgroup2_mount_root(tmp_path, monkeypatch) -> None:
    proc = tmp_path / "proc"
    cgroup = tmp_path / "cgroup-mount"
    service = cgroup / "tenant" / "service"
    (proc / "self").mkdir(parents=True)
    service.mkdir(parents=True)
    (proc / "meminfo").write_text(
        "MemTotal: 8388608 kB\nMemAvailable: 3145728 kB\n", encoding="ascii"
    )
    (proc / "self" / "cgroup").write_text("0::/tenant/service\n", encoding="ascii")
    (proc / "self" / "mountinfo").write_text(
        f"29 23 0:26 /other {cgroup} rw - cgroup2 cgroup rw\n",
        encoding="ascii",
    )
    # A mismatched mount root must not cause the membership path to be joined
    # beneath cgroup_root; only the supplied mount root is considered.
    (cgroup / "memory.max").write_text(str(4 * 1024**3), encoding="ascii")
    (cgroup / "memory.current").write_text(str(1024**3), encoding="ascii")
    (service / "memory.max").write_text(str(1 * 1024**3), encoding="ascii")
    (service / "memory.current").write_text(str(0), encoding="ascii")
    monkeypatch.setattr("blue_ant.resources.os.cpu_count", lambda: 8)

    snapshot = ResourceSnapshot.detect(proc_root=proc, cgroup_root=cgroup)

    assert snapshot.available_memory_bytes == 3 * 1024**3



def test_detect_uses_mount_root_when_process_is_at_mount_root(tmp_path, monkeypatch) -> None:
    proc = tmp_path / "proc"
    cgroup = tmp_path / "cgroup-mount"
    (proc / "self").mkdir(parents=True)
    cgroup.mkdir()
    (proc / "meminfo").write_text(
        "MemTotal: 8388608 kB\nMemAvailable: 3145728 kB\n", encoding="ascii"
    )
    (proc / "self" / "cgroup").write_text("0::/tenant\n", encoding="ascii")
    (proc / "self" / "mountinfo").write_text(
        f"29 23 0:26 /tenant {cgroup} rw - cgroup2 cgroup rw\n",
        encoding="ascii",
    )
    (cgroup / "memory.max").write_text(str(2 * 1024**3), encoding="ascii")
    (cgroup / "memory.current").write_text(str(1024**3), encoding="ascii")
    # This child must not be included when membership equals the mount root.
    child = cgroup / "service"
    child.mkdir()
    (child / "memory.max").write_text(str(512 * 1024**2), encoding="ascii")
    (child / "memory.current").write_text("0", encoding="ascii")
    monkeypatch.setattr("blue_ant.resources.os.cpu_count", lambda: 4)

    snapshot = ResourceSnapshot.detect(proc_root=proc, cgroup_root=cgroup)

    assert snapshot.available_memory_bytes == 1024**3


def test_detect_preserves_direct_membership_mapping_without_mountinfo(tmp_path, monkeypatch) -> None:
    proc = tmp_path / "proc"
    cgroup = tmp_path / "cgroup"
    tenant = cgroup / "tenant"
    (proc / "self").mkdir(parents=True)
    tenant.mkdir(parents=True)
    (proc / "meminfo").write_text(
        "MemTotal: 8388608 kB\nMemAvailable: 3145728 kB\n", encoding="ascii"
    )
    (proc / "self" / "cgroup").write_text("0::/tenant\n", encoding="ascii")
    (cgroup / "memory.max").write_text(str(4 * 1024**3), encoding="ascii")
    (cgroup / "memory.current").write_text(str(1024**3), encoding="ascii")
    (tenant / "memory.max").write_text(str(2 * 1024**3), encoding="ascii")
    (tenant / "memory.current").write_text(str(1536 * 1024**2), encoding="ascii")
    monkeypatch.setattr("blue_ant.resources.os.cpu_count", lambda: 4)

    snapshot = ResourceSnapshot.detect(proc_root=proc, cgroup_root=cgroup)

    assert snapshot.available_memory_bytes == 512 * 1024**2



def test_detect_applies_nested_cgroup_v1_parent_memory_and_cpu_limits(tmp_path, monkeypatch) -> None:
    proc = tmp_path / "proc"
    cgroup = tmp_path / "cgroup"
    memory = cgroup / "memory"
    cpu = cgroup / "cpu"
    (proc / "self").mkdir(parents=True)
    (memory / "tenant" / "service").mkdir(parents=True)
    (cpu / "tenant" / "service").mkdir(parents=True)
    (proc / "meminfo").write_text(
        "MemTotal: 8388608 kB\nMemAvailable: 3145728 kB\n", encoding="ascii"
    )
    (proc / "self" / "cgroup").write_text(
        "5:memory:/tenant/service\n6:cpu,cpuacct:/tenant/service\n",
        encoding="ascii",
    )
    (proc / "self" / "mountinfo").write_text(
        f"30 23 0:27 / {memory} rw - cgroup cgroup rw,memory\n"
        f"31 23 0:28 / {cpu} rw - cgroup cgroup rw,cpu,cpuacct\n",
        encoding="ascii",
    )

    for directory, limit, current in (
        (memory, 5 * 1024**3, 1024**3),
        (memory / "tenant", 2 * 1024**3, 1536 * 1024**2),
        (memory / "tenant" / "service", 3 * 1024**3, 1024**3),
    ):
        (directory / "memory.limit_in_bytes").write_text(str(limit), encoding="ascii")
        (directory / "memory.usage_in_bytes").write_text(str(current), encoding="ascii")
    for directory, quota in (
        (cpu, 600000),
        (cpu / "tenant", 150000),
        (cpu / "tenant" / "service", 400000),
    ):
        (directory / "cpu.cfs_quota_us").write_text(str(quota), encoding="ascii")
        (directory / "cpu.cfs_period_us").write_text("100000", encoding="ascii")
    monkeypatch.setattr("blue_ant.resources.os.cpu_count", lambda: 8)

    snapshot = ResourceSnapshot.detect(proc_root=proc, cgroup_root=cgroup)

    assert snapshot.cpu_count == 1
    assert snapshot.available_memory_bytes == 512 * 1024**2


def test_detect_keeps_cgroup_v1_direct_fallback_without_membership(tmp_path, monkeypatch) -> None:
    proc = tmp_path / "proc"
    cgroup = tmp_path / "cgroup"
    memory = cgroup / "memory"
    cpu = cgroup / "cpu"
    proc.mkdir()
    memory.mkdir(parents=True)
    cpu.mkdir()
    (proc / "meminfo").write_text(
        "MemTotal: 8388608 kB\nMemAvailable: 2097152 kB\n", encoding="ascii"
    )
    (memory / "memory.limit_in_bytes").write_text(str(2 * 1024**3), encoding="ascii")
    (memory / "memory.usage_in_bytes").write_text(str(512 * 1024**2), encoding="ascii")
    (cpu / "cpu.cfs_quota_us").write_text("150000", encoding="ascii")
    (cpu / "cpu.cfs_period_us").write_text("100000", encoding="ascii")
    monkeypatch.setattr("blue_ant.resources.os.cpu_count", lambda: 8)

    snapshot = ResourceSnapshot.detect(proc_root=proc, cgroup_root=cgroup)

    assert snapshot.cpu_count == 1
    assert snapshot.available_memory_bytes == 1536 * 1024**2
