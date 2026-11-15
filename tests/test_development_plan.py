import json

import pytest

from blue_ant.development_plan import generate_development_plan, plan_to_dict
from blue_ant.development_plan_cli import main


def audit_report():
    return {
        "schema_version": 1,
        "mode": "bounded_sequential_read_only_audit_loop",
        "project_id": "demo",
        "cycles_used": 2,
        "stop_reason": "sequence_completed",
        "cycles": [
            {"cycle": 1, "role": "docs_auditor", "status": "success", "findings": [
                {"severity": "warning", "path": "README.md", "message": "README is missing."}
            ]},
            {"cycle": 2, "role": "safety_auditor", "status": "success", "findings": [
                {"severity": "review", "path": "src/app.py", "message": "Line 4: eval pattern."}
            ]},
        ],
    }


def test_plan_converts_audit_and_failed_tests_to_review_tasks():
    tests = {
        "target_repository": "r30796106-collab/demo",
        "target_ref": "main",
        "test_profile": "python-unittest",
        "status": "failure",
    }
    plan = generate_development_plan(audit_report(), tests, project_id="demo")
    assert len(plan.tasks) == 3
    assert plan.tasks[0].kind == "audit_finding_review"
    assert plan.tasks[1].kind == "security_human_review"
    assert plan.tasks[2].kind == "target_test_failure_review"
    assert all(task.requires_human_review for task in plan.tasks)
    assert plan.approval_required is True
    assert plan.apply_approved is False
    assert plan.patch_proposal is None
    assert plan.target_repository == "r30796106-collab/demo"


def test_successful_test_result_is_recorded_without_claiming_future_validity():
    tests = {
        "target_repository": "r30796106-collab/demo",
        "target_ref": "feature-branch",
        "test_profile": "python-unittest",
        "status": "success",
    }
    plan = generate_development_plan(audit_report(), tests, project_id="demo")
    assert plan.tasks[-1].kind == "target_tests_passed"
    assert "exact repository ref" in " ".join(plan.limitations)


def test_plan_id_is_deterministic():
    first = generate_development_plan(audit_report(), project_id="demo")
    second = generate_development_plan(audit_report(), project_id="demo")
    assert first.plan_id == second.plan_id


@pytest.mark.parametrize("bad", [
    {"schema_version": 2, "mode": "bounded_sequential_read_only_audit_loop", "project_id": "demo", "cycles": []},
    {**audit_report(), "project_id": "other"},
    {**audit_report(), "cycles": [{"role": "shell", "status": "success", "findings": []}]},
    {**audit_report(), "cycles": [{"role": "repo_analyst", "status": "success", "findings": [{"severity": "critical", "path": "../secret", "message": "x"}]}]},
])
def test_rejects_invalid_or_untrusted_report_fields(bad):
    with pytest.raises(ValueError):
        generate_development_plan(bad, project_id="demo")


def test_rejects_untrusted_target_repository_and_ref():
    report = {
        "target_repository": "attacker/project",
        "target_ref": "main",
        "test_profile": "python-unittest",
        "status": "success",
    }
    with pytest.raises(ValueError, match="owner scope"):
        generate_development_plan(audit_report(), report, project_id="demo")
    report["target_repository"] = "r30796106-collab/demo"
    report["target_ref"] = "../main"
    with pytest.raises(ValueError, match="target_ref"):
        generate_development_plan(audit_report(), report, project_id="demo")


def test_rejects_oversized_findings():
    report = audit_report()
    report["cycles"] = [{
        "role": "repo_analyst", "status": "success",
        "findings": [{"severity": "info", "path": ".", "message": "x"}] * 101,
    }]
    with pytest.raises(ValueError, match="100-finding"):
        generate_development_plan(report, project_id="demo")


def test_cli_writes_plan_without_approving_it(tmp_path):
    audit_file = tmp_path / "audit.json"
    audit_file.write_text(json.dumps(audit_report()), encoding="utf-8")
    output = tmp_path / "plan.json"
    assert main(["--project-id", "demo", "--audit-report", str(audit_file), "--output", str(output)]) == 0
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["approval_required"] is True
    assert result["apply_approved"] is False
    assert result["patch_proposal"] is None



def test_plan_can_bind_target_repository_without_claiming_tests_ran():
    plan = generate_development_plan(
        audit_report(),
        project_id="demo",
        target_repository="r30796106-collab/demo",
        target_ref="feature/audit",
    )
    result = plan_to_dict(plan)
    assert result["target_repository"] == "r30796106-collab/demo"
    assert result["target_ref"] == "feature/audit"
    assert not any(task.kind == "target_tests_passed" for task in plan.tasks)


def test_target_repository_and_ref_must_be_supplied_together():
    with pytest.raises(ValueError, match="provided together"):
        generate_development_plan(
            audit_report(), project_id="demo",
            target_repository="r30796106-collab/demo",
        )


def test_target_metadata_is_validated_and_matches_test_report():
    with pytest.raises(ValueError, match="owner scope"):
        generate_development_plan(
            audit_report(), project_id="demo",
            target_repository="attacker/demo", target_ref="main",
        )
    tests = {
        "target_repository": "r30796106-collab/demo",
        "target_ref": "main",
        "test_profile": "python-unittest",
        "status": "success",
    }
    with pytest.raises(ValueError, match="does not match"):
        generate_development_plan(
            audit_report(), tests, project_id="demo",
            target_repository="r30796106-collab/demo", target_ref="other",
        )


def test_cli_accepts_target_metadata_without_test_report(tmp_path):
    audit_file = tmp_path / "audit.json"
    audit_file.write_text(json.dumps(audit_report()), encoding="utf-8")
    output = tmp_path / "plan.json"
    assert main([
        "--project-id", "demo",
        "--audit-report", str(audit_file),
        "--target-repository", "r30796106-collab/demo",
        "--target-ref", "main",
        "--output", str(output),
    ]) == 0
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["target_repository"] == "r30796106-collab/demo"
    assert result["target_ref"] == "main"
    assert result["apply_approved"] is False
