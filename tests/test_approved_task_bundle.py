import json

import pytest

from blue_ant.approved_task_bundle import stage_bundle, validate_bundle


def make_bundle():
    def proposal(task_id, path):
        return {
            "proposal_id": "proposal-" + task_id,
            "project_id": "demo",
            "task_id": task_id,
            "changes": [{
                "path": path,
                "content": "updated = True\n",
                "expected_sha256": "a" * 64,
            }],
        }
    return {
        "schema_version": 1,
        "target_repository": "r30796106-collab/ELON",
        "target_ref": "master",
        "project_id": "demo",
        "apply_approved": True,
        "tasks": [
            {"task_id": "worker_one", "proposal": proposal("worker_one", "src/one.py")},
            {"task_id": "worker_two", "proposal": proposal("worker_two", "src/two.py")},
        ],
    }


def test_validates_and_stages_independent_task_proposals(tmp_path):
    bundle = make_bundle()
    metadata = stage_bundle(bundle, tmp_path / "staged")
    assert len(metadata["tasks"]) == 2
    assert json.loads((tmp_path / "staged/worker_one/proposal.json").read_text())["task_id"] == "worker_one"
    assert json.loads((tmp_path / "staged/worker_two/proposal.json").read_text())["task_id"] == "worker_two"


def test_requires_explicit_approval_and_owner_scoped_repository():
    bundle = make_bundle()
    bundle["apply_approved"] = False
    with pytest.raises(PermissionError):
        validate_bundle(bundle)
    bundle = make_bundle()
    bundle["target_repository"] = "someone-else/private"
    with pytest.raises(ValueError):
        validate_bundle(bundle)


def test_limits_tasks_and_rejects_duplicate_ids_or_paths():
    bundle = make_bundle()
    bundle["tasks"] *= 3
    with pytest.raises(ValueError, match="1–4"):
        validate_bundle(bundle)
    bundle = make_bundle()
    bundle["tasks"][1]["task_id"] = "worker_one"
    bundle["tasks"][1]["proposal"]["task_id"] = "worker_one"
    with pytest.raises(ValueError, match="unique"):
        validate_bundle(bundle)
    bundle = make_bundle()
    bundle["tasks"][1]["proposal"]["changes"][0]["path"] = "src/one.py"
    with pytest.raises(ValueError, match="same file"):
        validate_bundle(bundle)


@pytest.mark.parametrize("path", ["../secret", "/etc/passwd", ".git/config", "src\\bad.py", "src/../bad.py"])
def test_rejects_unsafe_paths(path):
    bundle = make_bundle()
    bundle["tasks"][0]["proposal"]["changes"][0]["path"] = path
    with pytest.raises(ValueError):
        validate_bundle(bundle)


def test_rejects_parent_child_path_overlap():
    bundle = make_bundle()
    bundle["tasks"][1]["proposal"]["changes"][0]["path"] = "src/one.py/child"
    with pytest.raises(ValueError, match="overlapping"):
        validate_bundle(bundle)


def test_rejects_bad_hash_or_oversized_payload():
    bundle = make_bundle()
    bundle["tasks"][0]["proposal"]["changes"][0]["expected_sha256"] = "BAD"
    with pytest.raises(ValueError, match="SHA-256"):
        validate_bundle(bundle)
    bundle = make_bundle()
    bundle["tasks"][0]["proposal"]["changes"][0]["content"] = "x" * 2_000_001
    with pytest.raises(ValueError, match="2 MB"):
        validate_bundle(bundle)


def test_cli_stages_bundle(tmp_path):
    from blue_ant.approved_task_bundle import main

    source = tmp_path / "bundle.json"
    source.write_text(json.dumps(make_bundle()), encoding="utf-8")
    output = tmp_path / "output"
    assert main(["--input", str(source), "--output-dir", str(output)]) == 0
    assert (output / "metadata.json").is_file()
    assert (output / "worker_one" / "proposal.json").is_file()
