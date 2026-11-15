from __future__ import annotations

import pytest

from blue_ant.resources import ResourcePolicy, ResourceSnapshot


def test_worker_limit_is_bounded_by_cpu_and_configuration() -> None:
    policy = ResourcePolicy(max_workers=8, reserve_memory_bytes=0, memory_per_worker_bytes=100)
    assert policy.worker_limit(ResourceSnapshot(cpu_count=3, available_memory_bytes=10_000)) == 3


def test_worker_limit_is_bounded_by_available_memory() -> None:
    policy = ResourcePolicy(max_workers=8, reserve_memory_bytes=500, memory_per_worker_bytes=250)
    assert policy.worker_limit(ResourceSnapshot(cpu_count=8, available_memory_bytes=1_000)) == 2


def test_worker_limit_never_returns_zero_for_low_memory() -> None:
    policy = ResourcePolicy(max_workers=4, reserve_memory_bytes=1_000, memory_per_worker_bytes=500)
    assert policy.worker_limit(ResourceSnapshot(cpu_count=4, available_memory_bytes=100)) == 1


def test_invalid_resource_snapshot_is_rejected() -> None:
    with pytest.raises(ValueError):
        ResourceSnapshot(cpu_count=0, available_memory_bytes=100)
