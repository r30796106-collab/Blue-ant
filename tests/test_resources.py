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



def test_detect_maps_cgroup_v1_membership_relative_to_non_root_mount(tmp_path, monkeypatch) -> None:
    proc = tmp_path / "proc"
    cgroup = tmp_path / "cgroup-mount"
    memory_root = cgroup / "memory"
    cpu_root = cgroup / "cpu"
    memory_leaf = memory_root / "service"
    cpu_leaf = cpu_root / "service"
    (proc / "self").mkdir(parents=True)
    memory_leaf.mkdir(parents=True)
    cpu_leaf.mkdir(parents=True)
    (proc / "meminfo").write_text(
        "MemTotal: 8388608 kB\nMemAvailable: 3145728 kB\n", encoding="ascii"
    )
    (proc / "self" / "cgroup").write_text(
        "5:memory:/tenant/service\n6:cpu,cpuacct:/tenant/service\n",
        encoding="ascii",
    )
    (proc / "self" / "mountinfo").write_text(
        f"30 23 0:27 /tenant {memory_root} rw - cgroup cgroup rw,memory\n"
        f"31 23 0:28 /tenant {cpu_root} rw - cgroup cgroup rw,cpu,cpuacct\n",
        encoding="ascii",
    )
    (memory_root / "memory.limit_in_bytes").write_text(str(4 * 1024**3), encoding="ascii")
    (memory_root / "memory.usage_in_bytes").write_text(str(1024**3), encoding="ascii")
    (memory_leaf / "memory.limit_in_bytes").write_text(str(2 * 1024**3), encoding="ascii")
    (memory_leaf / "memory.usage_in_bytes").write_text(str(1536 * 1024**2), encoding="ascii")
    (cpu_root / "cpu.cfs_quota_us").write_text("400000", encoding="ascii")
    (cpu_root / "cpu.cfs_period_us").write_text("100000", encoding="ascii")
    (cpu_leaf / "cpu.cfs_quota_us").write_text("150000", encoding="ascii")
    (cpu_leaf / "cpu.cfs_period_us").write_text("100000", encoding="ascii")
    monkeypatch.setattr("blue_ant.resources.os.cpu_count", lambda: 8)

    snapshot = ResourceSnapshot.detect(proc_root=proc, cgroup_root=cgroup)

    assert snapshot.cpu_count == 1
    assert snapshot.available_memory_bytes == 512 * 1024**2


def test_detect_decodes_escaped_cgroup_v1_mountpoint(tmp_path, monkeypatch) -> None:
    proc = tmp_path / "proc"
    cgroup = tmp_path / "cgroup mount"
    memory_root = cgroup / "memory"
    (proc / "self").mkdir(parents=True)
    memory_root.mkdir(parents=True)
    (proc / "meminfo").write_text(
        "MemTotal: 8388608 kB\nMemAvailable: 3145728 kB\n", encoding="ascii"
    )
    (proc / "self" / "cgroup").write_text(
        "5:memory:/tenant\n", encoding="ascii"
    )
    escaped = str(memory_root).replace(" ", r"\040")
    (proc / "self" / "mountinfo").write_text(
        f"30 23 0:27 /tenant {escaped} rw - cgroup cgroup rw,memory\n",
        encoding="ascii",
    )
    (memory_root / "memory.limit_in_bytes").write_text(str(2 * 1024**3), encoding="ascii")
    (memory_root / "memory.usage_in_bytes").write_text(str(1024**3), encoding="ascii")
    monkeypatch.setattr("blue_ant.resources.os.cpu_count", lambda: 4)

    snapshot = ResourceSnapshot.detect(proc_root=proc, cgroup_root=cgroup)

    assert snapshot.available_memory_bytes == 1024**3


def test_detect_fails_safe_for_cgroup_v1_membership_outside_mount_root(tmp_path, monkeypatch) -> None:
    proc = tmp_path / "proc"
    cgroup = tmp_path / "cgroup-mount"
    memory_root = cgroup / "memory"
    unrelated = memory_root / "tenant"
    (proc / "self").mkdir(parents=True)
    unrelated.mkdir(parents=True)
    (proc / "meminfo").write_text(
        "MemTotal: 8388608 kB\nMemAvailable: 3145728 kB\n", encoding="ascii"
    )
    (proc / "self" / "cgroup").write_text(
        "5:memory:/tenant/service\n", encoding="ascii"
    )
    (proc / "self" / "mountinfo").write_text(
        f"30 23 0:27 /other {memory_root} rw - cgroup cgroup rw,memory\n",
        encoding="ascii",
    )
    # A mismatched root must not make the membership path resolve under this mount.
    (memory_root / "memory.limit_in_bytes").write_text(str(4 * 1024**3), encoding="ascii")
    (memory_root / "memory.usage_in_bytes").write_text(str(1024**3), encoding="ascii")
    (unrelated / "memory.limit_in_bytes").write_text(str(512 * 1024**2), encoding="ascii")
    (unrelated / "memory.usage_in_bytes").write_text("0", encoding="ascii")
    monkeypatch.setattr("blue_ant.resources.os.cpu_count", lambda: 4)

    snapshot = ResourceSnapshot.detect(proc_root=proc, cgroup_root=cgroup)

    assert snapshot.available_memory_bytes == 3 * 1024**3



def test_detect_applies_nested_cgroup_v2_cpuset_limits(tmp_path, monkeypatch) -> None:
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
    (cgroup / "cpuset.cpus.effective").write_text("0-7", encoding="ascii")
    (tenant / "cpuset.cpus.effective").write_text("1-3,6", encoding="ascii")
    (service / "cpuset.cpus.effective").write_text("2-3", encoding="ascii")
    monkeypatch.setattr("blue_ant.resources.os.cpu_count", lambda: 16)

    snapshot = ResourceSnapshot.detect(proc_root=proc, cgroup_root=cgroup)

    assert snapshot.cpu_count == 2


def test_detect_applies_cgroup_v1_cpuset_parent_limit(tmp_path, monkeypatch) -> None:
    proc = tmp_path / "proc"
    cgroup = tmp_path / "cgroup"
    cpuset = cgroup / "cpuset"
    tenant = cpuset / "tenant"
    service = tenant / "service"
    (proc / "self").mkdir(parents=True)
    service.mkdir(parents=True)
    (proc / "meminfo").write_text(
        "MemTotal: 8388608 kB\nMemAvailable: 3145728 kB\n", encoding="ascii"
    )
    (proc / "self" / "cgroup").write_text(
        "7:cpuset:/tenant/service\n", encoding="ascii"
    )
    (proc / "self" / "mountinfo").write_text(
        f"32 23 0:29 / {cpuset} rw - cgroup cgroup rw,cpuset\n",
        encoding="ascii",
    )
    (cpuset / "cpuset.cpus").write_text("0-7", encoding="ascii")
    (tenant / "cpuset.cpus").write_text("0-1,4", encoding="ascii")
    # An empty leaf cpuset inherits its effective parent set.
    (service / "cpuset.cpus").write_text("", encoding="ascii")
    monkeypatch.setattr("blue_ant.resources.os.cpu_count", lambda: 16)

    snapshot = ResourceSnapshot.detect(proc_root=proc, cgroup_root=cgroup)

    assert snapshot.cpu_count == 3


def test_detect_ignores_invalid_cpuset_without_raising(tmp_path, monkeypatch) -> None:
    proc = tmp_path / "proc"
    cgroup = tmp_path / "cgroup"
    proc.mkdir()
    cgroup.mkdir()
    (proc / "meminfo").write_text(
        "MemTotal: 8388608 kB\nMemAvailable: 3145728 kB\n", encoding="ascii"
    )
    (cgroup / "cpuset.cpus.effective").write_text("0-3,broken", encoding="ascii")
    monkeypatch.setattr("blue_ant.resources.os.cpu_count", lambda: 6)

    snapshot = ResourceSnapshot.detect(proc_root=proc, cgroup_root=cgroup)

    assert snapshot.cpu_count == 6


def test_read_cpu_set_count_merges_overlapping_ranges(tmp_path) -> None:
    from blue_ant.resources import _read_cpu_set_count

    cpuset = tmp_path / "cpuset.cpus"
    cpuset.write_text("0-3,2-5,7", encoding="ascii")

    assert _read_cpu_set_count(cpuset) == 7



def test_read_cpu_set_count_ignores_integer_tokens_beyond_python_limit(tmp_path) -> None:
    from blue_ant.resources import _read_cpu_set_count

    cpuset = tmp_path / "cpuset.cpus"
    cpuset.write_text("9" * 5000, encoding="ascii")

    assert _read_cpu_set_count(cpuset) is None


def test_read_cpu_set_count_ignores_oversized_range_endpoint(tmp_path) -> None:
    from blue_ant.resources import _read_cpu_set_count

    cpuset = tmp_path / "cpuset.cpus"
    cpuset.write_text("0-" + "9" * 5000, encoding="ascii")

    assert _read_cpu_set_count(cpuset) is None



def test_read_cpu_set_count_ignores_non_ascii_host_data(tmp_path) -> None:
    from blue_ant.resources import _read_cpu_set_count

    cpuset = tmp_path / "cpuset.cpus"
    cpuset.write_bytes(b"0-3,\xff")

    assert _read_cpu_set_count(cpuset) is None


def test_read_cpu_set_count_bounds_input_size(tmp_path, monkeypatch) -> None:
    import blue_ant.resources as resources
    from blue_ant.resources import _read_cpu_set_count

    monkeypatch.setattr(resources, "_MAX_CPUSET_TEXT_BYTES", 8)
    cpuset = tmp_path / "cpuset.cpus"
    cpuset.write_text("0," * 5, encoding="ascii")

    assert _read_cpu_set_count(cpuset) is None



def test_read_first_int_bounds_scalar_reads_and_ignores_non_ascii(tmp_path, monkeypatch):
    import blue_ant.resources as resources
    from blue_ant.resources import _read_first_int

    monkeypatch.setattr(resources, "_MAX_CGROUP_SCALAR_BYTES", 8)
    scalar = tmp_path / "memory.max"
    scalar.write_text("123456789", encoding="ascii")
    assert _read_first_int(scalar) is None

    scalar.write_bytes(b"123\xff")
    assert _read_first_int(scalar) is None


def test_read_v2_cpu_quota_ignores_oversized_and_non_ascii_values(tmp_path, monkeypatch):
    import blue_ant.resources as resources
    from blue_ant.resources import _read_v2_cpu_quota

    monkeypatch.setattr(resources, "_MAX_CGROUP_SCALAR_BYTES", 8)
    (tmp_path / "cpu.max").write_text("100000 100000", encoding="ascii")
    assert _read_v2_cpu_quota(tmp_path) is None

    (tmp_path / "cpu.max").write_bytes(b"100000 \xff")
    assert _read_v2_cpu_quota(tmp_path) is None


def test_read_v2_cpu_quota_accepts_valid_value(tmp_path):
    from blue_ant.resources import _read_v2_cpu_quota

    (tmp_path / "cpu.max").write_text("150000 100000", encoding="ascii")
    assert _read_v2_cpu_quota(tmp_path) == (150000, 100000)



def test_bounded_proc_reader_rejects_oversized_and_non_ascii_data(tmp_path, monkeypatch):
    import blue_ant.resources as resources

    path = tmp_path / "proc-metadata"
    monkeypatch.setattr(resources, "_MAX_PROC_CGROUP_BYTES", 8)
    path.write_bytes(b"123456789")
    assert resources._read_bounded_proc_lines(path, 8) is None

    path.write_bytes(b"valid\xff")
    assert resources._read_bounded_proc_lines(path, 8) is None


def test_detect_fails_closed_for_oversized_meminfo(tmp_path, monkeypatch):
    import blue_ant.resources as resources

    proc = tmp_path / "proc"
    cgroup = tmp_path / "cgroup"
    proc.mkdir()
    cgroup.mkdir()
    monkeypatch.setattr(resources, "_MAX_PROC_MEMINFO_BYTES", 8)
    (proc / "meminfo").write_text("MemTotal: 1000 kB", encoding="ascii")

    with pytest.raises(RuntimeError, match="meminfo"):
        ResourceSnapshot.detect(proc_root=proc, cgroup_root=cgroup)


def test_cgroup_metadata_falls_back_for_oversized_membership(tmp_path, monkeypatch):
    import blue_ant.resources as resources

    proc = tmp_path / "proc"
    cgroup = tmp_path / "cgroup"
    self_dir = proc / "self"
    self_dir.mkdir(parents=True)
    cgroup.mkdir()
    monkeypatch.setattr(resources, "_MAX_PROC_CGROUP_BYTES", 8)
    (self_dir / "cgroup").write_text("0::/tenant/service", encoding="ascii")

    assert resources._cgroup_v2_dirs(proc, cgroup) == (cgroup,)



def test_meminfo_ignores_numeric_tokens_beyond_python_integer_limit(tmp_path):
    from blue_ant.resources import _read_meminfo

    path = tmp_path / "meminfo"
    path.write_text("MemTotal: " + "9" * 5000 + " kB\n", encoding="ascii")

    assert _read_meminfo(path) == {}



def test_legacy_cpu_quota_reader_uses_bounded_v2_and_v1_readers(tmp_path, monkeypatch):
    import blue_ant.resources as resources
    from blue_ant.resources import _read_cpu_quota

    monkeypatch.setattr(resources, "_MAX_CGROUP_SCALAR_BYTES", 8)
    (tmp_path / "cpu.max").write_text("100000 100000", encoding="ascii")
    cpu = tmp_path / "cpu"
    cpu.mkdir()
    (cpu / "cpu.cfs_quota_us").write_text("150000", encoding="ascii")
    (cpu / "cpu.cfs_period_us").write_text("100000", encoding="ascii")

    assert _read_cpu_quota(tmp_path) == (150000, 100000)


def test_detect_maps_cgroup_v1_cpuset_membership_relative_to_non_root_mount(
    tmp_path, monkeypatch
) -> None:
    proc = tmp_path / "proc"
    cgroup = tmp_path / "cgroup-mount"
    cpuset_root = cgroup / "cpuset"
    service = cpuset_root / "service"
    (proc / "self").mkdir(parents=True)
    service.mkdir(parents=True)
    (proc / "meminfo").write_text(
        "MemTotal: 8388608 kB\nMemAvailable: 3145728 kB\n", encoding="ascii"
    )
    (proc / "self" / "cgroup").write_text(
        "7:cpuset:/tenant/service\n", encoding="ascii"
    )
    (proc / "self" / "mountinfo").write_text(
        f"32 23 0:29 /tenant {cpuset_root} rw - cgroup cgroup rw,cpuset\n",
        encoding="ascii",
    )
    (cpuset_root / "cpuset.cpus").write_text("0-7", encoding="ascii")
    (service / "cpuset.cpus").write_text("2-3,6", encoding="ascii")
    monkeypatch.setattr("blue_ant.resources.os.cpu_count", lambda: 16)

    snapshot = ResourceSnapshot.detect(proc_root=proc, cgroup_root=cgroup)

    assert snapshot.cpu_count == 3
