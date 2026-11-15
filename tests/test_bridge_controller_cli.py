import json

from blue_ant.bridge_controller_cli import main


def test_cli_writes_valid_json_decision(tmp_path, monkeypatch, capsys):
    bundle = {
        "schema_version": 1,
        "command": {
            "schema_version": 1,
            "command_id": "cli-test",
            "command": "audit_plan",
            "project_id": "demo",
            "repository": "r30796106-collab/ELON",
            "ref": "master",
            "roles": ["repo_analyst"],
            "max_cycles": 1,
            "task": "Read-only review",
        },
        "audit_report": {
            "schema_version": 1,
            "mode": "bounded_sequential_read_only_audit_loop",
            "project_id": "demo",
            "cycles": [
                {"role": "repo_analyst", "status": "success", "findings": []}
            ],
        },
        "plan": {
            "schema_version": 1,
            "project_id": "demo",
            "target_repository": "r30796106-collab/ELON",
            "target_ref": "master",
            "tasks": [],
            "apply_approved": False,
            "patch_proposal": None,
        },
    }
    source = tmp_path / "bundle.json"
    output = tmp_path / "nested" / "decision.json"
    source.write_text(json.dumps(bundle), encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["blue-ant-bridge-controller", "--input", str(source), "--output", str(output)],
    )

    assert main() == 0
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["status"] == "completed"
    assert result["action"] == "stop"
    assert output.read_text(encoding="utf-8").endswith("\n")
    assert '"status": "completed"' in capsys.readouterr().out
