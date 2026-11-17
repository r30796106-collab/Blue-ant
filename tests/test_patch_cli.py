import json
from pathlib import Path

from blue_ant.audit import AuditLog
from blue_ant.patch_cli import load_proposal, main
from blue_ant.patches import sha256_text

PORTFOLIO = Path(__file__).resolve().parents[1] / "config" / "portfolio.json"


def test_load_proposal_and_dry_run(tmp_path, capsys):
    proposal_file = tmp_path / "proposal.json"
    workspace = tmp_path / "workspace"
    target = workspace / "src" / "blue_ant" / "hello.txt"
    target.parent.mkdir(parents=True)
    proposal_file.write_text(json.dumps({
        "proposal_id": "p1",
        "project_id": "blue-ant",
        "task_id": "task-1",
        "changes": [{
            "path": "src/blue_ant/hello.txt",
            "content": "hello",
            "expected_sha256": None,
        }],
    }), encoding="utf-8")

    proposal = load_proposal(proposal_file)
    assert proposal.proposal_id == "p1"
    assert main(["--workspace", str(workspace), "--proposal", str(proposal_file), "--portfolio", str(PORTFOLIO)]) == 0
    assert "DRY RUN ONLY" in capsys.readouterr().out
    assert not target.exists()


def test_cli_requires_explicit_approval_and_applies(tmp_path, capsys):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "src" / "blue_ant" / "hello.txt"
    target.parent.mkdir(parents=True)
    target.write_text("old", encoding="utf-8")
    proposal_file = tmp_path / "proposal.json"
    proposal_file.write_text(json.dumps({
        "proposal_id": "p2",
        "project_id": "blue-ant",
        "task_id": "task-2",
        "changes": [{
            "path": "src/blue_ant/hello.txt",
            "content": "new",
            "expected_sha256": sha256_text("old"),
        }],
    }), encoding="utf-8")

    assert main(["--workspace", str(workspace), "--proposal", str(proposal_file), "--portfolio", str(PORTFOLIO)]) == 0
    assert target.read_text(encoding="utf-8") == "old"
    assert main(["--workspace", str(workspace), "--proposal", str(proposal_file), "--portfolio", str(PORTFOLIO), "--approve"]) == 0
    assert target.read_text(encoding="utf-8") == "new"
    captured = capsys.readouterr().out
    assert "APPLIED: 1 file(s)" in captured
    assert captured.count("APPLIED: 1 file(s)") == 1
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


def test_load_proposal_rejects_duplicate_keys_at_nested_levels(tmp_path):
    proposal_file = tmp_path / "duplicate.json"
    proposal_file.write_text(
        '{"proposal_id":"first","proposal_id":"second","project_id":"demo",'
        '"task_id":"task-1","changes":[{"path":"a.py","path":"b.py",'
        '"content":"x","expected_sha256":null}]}',
        encoding="utf-8",
    )
    try:
        load_proposal(proposal_file)
    except ValueError as exc:
        assert "duplicate JSON object key" in str(exc)
    else:
        raise AssertionError("duplicate JSON keys must be rejected")


def test_patch_cli_rejects_out_of_scope_before_audit_or_write(tmp_path, capsys):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    protected = workspace / "security" / "policy.py"
    protected.parent.mkdir()
    protected.write_text("safe", encoding="utf-8")
    proposal_file = tmp_path / "proposal.json"
    proposal_file.write_text(json.dumps({"proposal_id":"p4","project_id":"elon","task_id":"task-4","changes":[{"path":"security/policy.py","content":"bad","expected_sha256":sha256_text("safe")}]}), encoding="utf-8")
    assert main(["--workspace", str(workspace), "--proposal", str(proposal_file), "--portfolio", str(PORTFOLIO), "--approve"]) == 2
    assert protected.read_text(encoding="utf-8") == "safe"
    assert not (workspace / ".blue-ant" / "patch-audit.jsonl").exists()
    assert "out-of-scope" in capsys.readouterr().err
