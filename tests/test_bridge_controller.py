import pytest

from blue_ant.bridge_controller import evaluate_bridge_result


def bundle(*, roles=None, cycles=None, tasks=None, max_cycles=None, snapshot_sources=False):
    roles = roles or ["repo_analyst", "docs_auditor"]
    cycles = cycles if cycles is not None else [
        {"role": roles[0], "status": "success", "findings": []}
    ]
    return {
        "schema_version": 1,
        "command": {
            "schema_version": 1, "command_id": "controller-test",
            "command": "audit_plan", "project_id": "demo",
            "repository": "r30796106-collab/ELON", "ref": "master",
            "roles": roles, "max_cycles": max_cycles or len(roles),
            "task": "Read-only review",
            "snapshot_sources": snapshot_sources,
        },
        "audit_report": {
            "schema_version": 1, "mode": "bounded_sequential_read_only_audit_loop",
            "project_id": "demo", "cycles": cycles,
        },
        "plan": {
            "schema_version": 1, "project_id": "demo",
            "target_repository": "r30796106-collab/ELON", "target_ref": "master",
            "tasks": tasks or [], "apply_approved": False, "patch_proposal": None,
        },
    }


def test_emits_next_preapproved_role_after_clean_partial_result():
    result = evaluate_bridge_result(bundle())
    assert result.action == "next_instruction"
    assert result.next_role == "docs_auditor"
    assert result.next_command["roles"] == ["docs_auditor"]
    assert result.next_command["max_cycles"] == 1


def test_stops_for_actionable_plan_finding():
    result = evaluate_bridge_result(bundle(tasks=[{"kind": "audit_finding_review"}]))
    assert result.action == "human_review"
    assert result.status == "stopped"
    assert result.next_command is None


def test_stops_for_safety_review():
    result = evaluate_bridge_result(bundle(tasks=[{"kind": "security_human_review"}]))
    assert result.action == "human_review"


def test_stops_after_worker_failure():
    result = evaluate_bridge_result(bundle(cycles=[
        {"role": "repo_analyst", "status": "failed", "error": "worker failed"}
    ]))
    assert result.action == "human_review"


def test_completes_when_all_roles_are_clean():
    roles = ["repo_analyst", "docs_auditor"]
    result = evaluate_bridge_result(bundle(
        roles=roles,
        cycles=[
            {"role": role, "status": "success", "findings": []}
            for role in roles
        ],
    ))
    assert result.status == "completed"
    assert result.action == "stop"


def test_stops_at_explicit_cycle_limit():
    result = evaluate_bridge_result(bundle(max_cycles=1))
    assert result.action == "cycle_limit"


def test_rejects_target_mismatch():
    value = bundle()
    value["plan"]["target_ref"] = "other"
    with pytest.raises(ValueError, match="target"):
        evaluate_bridge_result(value)


def test_rejects_any_implicit_approval_or_patch():
    value = bundle()
    value["plan"]["apply_approved"] = True
    with pytest.raises(ValueError, match="approval"):
        evaluate_bridge_result(value)


def test_rejects_unrequested_role():
    value = bundle(cycles=[
        {"role": "safety_auditor", "status": "success", "findings": []}
    ])
    with pytest.raises(ValueError, match="unrequested"):
        evaluate_bridge_result(value)


def test_generated_command_id_stays_within_bridge_limit():
    value = bundle()
    value["command"]["command_id"] = "a" * 48
    result = evaluate_bridge_result(value)
    assert len(result.next_command["command_id"]) <= 48



def test_controller_preserves_snapshot_mode_in_next_instruction():
    result = evaluate_bridge_result(bundle(snapshot_sources=True))
    assert result.action == "next_instruction"
    assert result.next_command["snapshot_sources"] is True

def test_informational_findings_do_not_block_next_preapproved_role():
    result = evaluate_bridge_result(bundle(
        tasks=[{"kind": "informational_observation"}],
    ))
    assert result.status == "continue"
    assert result.action == "next_instruction"
    assert result.next_role == "docs_auditor"


def test_all_roles_complete_with_informational_findings_stops_normally():
    roles = ["repo_analyst", "test_auditor", "docs_auditor", "safety_auditor"]
    cycles = [
        {"role": role, "status": "success", "findings": []}
        for role in roles
    ]
    tasks = [
        {"kind": "informational_observation", "priority": "low"}
        for _ in range(4)
    ]
    result = evaluate_bridge_result(bundle(roles=roles, cycles=cycles, tasks=tasks))

    assert result.status == "completed"
    assert result.action == "stop"
    assert result.completed_roles == tuple(roles)
    assert result.next_command is None


def test_audit_finding_cannot_be_hidden_by_empty_derived_plan():
    value = bundle(tasks=[])
    value["audit_report"]["cycles"][0]["findings"] = [{
        "severity": "warning",
        "path": "src/example.py",
        "message": "Potential issue",
    }]
    result = evaluate_bridge_result(value)
    assert result.status == "stopped"
    assert result.action == "human_review"
    assert result.next_command is None


def test_safety_auditor_observation_requires_human_review_even_if_info():
    roles = ["safety_auditor", "docs_auditor"]
    value = bundle(
        roles=roles,
        cycles=[{
            "role": "safety_auditor",
            "status": "success",
            "findings": [{
                "severity": "info",
                "path": "security/policy.py",
                "message": "Safety observation",
            }],
        }],
        tasks=[],
    )
    result = evaluate_bridge_result(value)
    assert result.status == "stopped"
    assert result.action == "human_review"
