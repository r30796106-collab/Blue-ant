import json

from blue_ant.audit import AuditLog
from blue_ant.patch_cli import load_proposal, main
from blue_ant.patches import sha256_text


def test_load_proposal_and_dry_run(tmp_path, capsys):
    proposal_file = tmp_path / "proposal.json"
    proposal_file.write_text(json.dumps({
        "proposal_id": "p1",
        "project_id": "demo",
        "task_id": "task-1",
        "changes": [{
            "path": "hello.txt",
            "content": "hello",
            "expected_sha256": None,
        }],
    }), encoding="utf-8")

    proposal = load_proposal(proposal_file)
    assert proposal.proposal_id == "p1"
    assert main(["--workspace", str(tmp_path), "--proposal", str(proposal_file)]) == 0
    assert "DRY RUN ONLY" in capsys.readouterr().out
    assert not (tmp_path / "hello.txt").exists()


def test_cli_requires_explicit_approval_and_applies(tmp_path, capsys):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "hello.txt").write_text("old", encoding="utf-8")
    proposal_file = tmp_path / "proposal.json"
    proposal_file.write_text(json.dumps({
        "proposal_id": "p2",
        "project_id": "demo",
        "task_id": "task-2",
        "changes": [{
            "path": "hello.txt",
            "content": "new",
            "expected_sha256": sha256_text("old"),
        }],
    }), encoding="utf-8")

    assert main(["--workspace", str(workspace), "--proposal", str(proposal_file)]) == 0
    assert (workspace / "hello.txt").read_text(encoding="utf-8") == "old"
    assert main([
        "--workspace", str(workspace), "--proposal", str(proposal_file), "--approve"
    ]) == 0
    assert (workspace / "hello.txt").read_text(encoding="utf-8") == "new"
    captured = capsys.readouterr().out
    assert "APPLIED: 1 file(s)" in captured
    audit_path = workspace / ".blue-ant" / "patch-audit.jsonl"
    verification = AuditLog(audit_path).verify()
    assert verification.valid is True
    assert verification.records == 2
    assert "AUDIT VERIFIED: 2 record(s)" in captured


def test_load_proposal_rejects_unknown_fields(tmp_path):
    proposal_file = tmp_path / "bad.json"
    proposal_file.write_text(json.dumps({
        "proposal_id": "p3",
        "project_id": "demo",
        "task_id": "task-3",
        "changes": [],
        "shell": "not allowed",
    }), encoding="utf-8")

    try:
        load_proposal(proposal_file)
    except ValueError as exc:
        assert "exactly" in str(exc)
    else:
        raise AssertionError("unknown fields must be rejected")
