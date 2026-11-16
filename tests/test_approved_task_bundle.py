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



def test_rejects_symlinked_output_root(tmp_path):
    real_root = tmp_path / "real-output"
    real_root.mkdir()
    linked_root = tmp_path / "linked-output"
    linked_root.symlink_to(real_root, target_is_directory=True)

    with pytest.raises(ValueError, match="output directory"):
        stage_bundle(make_bundle(), linked_root)
    assert list(real_root.iterdir()) == []


def test_rejects_symlinked_task_directory_before_writing(tmp_path):
    root = tmp_path / "staged"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "worker_one").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="task directory"):
        stage_bundle(make_bundle(), root)
    assert list(outside.iterdir()) == []
    assert not (root / "worker_two").exists()


def test_rejects_symlinked_proposal_file_without_following_it(tmp_path):
    root = tmp_path / "staged"
    task_dir = root / "worker_one"
    task_dir.mkdir(parents=True)
    outside = tmp_path / "outside.json"
    outside.write_text("do not overwrite", encoding="utf-8")
    (task_dir / "proposal.json").symlink_to(outside)

    with pytest.raises(FileExistsError, match="already exists"):
        stage_bundle(make_bundle(), root)
    assert outside.read_text(encoding="utf-8") == "do not overwrite"
    assert not (root / "worker_two").exists()


def test_refuses_to_overwrite_existing_staged_metadata(tmp_path):
    root = tmp_path / "staged"
    root.mkdir()
    metadata = root / "metadata.json"
    metadata.write_text("preserve", encoding="utf-8")

    with pytest.raises(FileExistsError, match="already exists"):
        stage_bundle(make_bundle(), root)
    assert metadata.read_text(encoding="utf-8") == "preserve"
    assert not (root / "worker_one").exists()


def test_refuses_to_overwrite_existing_proposal(tmp_path):
    root = tmp_path / "staged"
    task_dir = root / "worker_one"
    task_dir.mkdir(parents=True)
    proposal_path = task_dir / "proposal.json"
    proposal_path.write_text("preserve", encoding="utf-8")

    with pytest.raises(FileExistsError, match="already exists"):
        stage_bundle(make_bundle(), root)
    assert proposal_path.read_text(encoding="utf-8") == "preserve"
    assert not (root / "worker_two").exists()


def test_rejects_boolean_schema_version():
    bundle = make_bundle()
    bundle["schema_version"] = True
    with pytest.raises(ValueError, match="schema_version"):
        validate_bundle(bundle)


def test_rejects_symlinked_parent_of_staging_root(tmp_path):
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    output = linked_parent / "staged"

    with pytest.raises(ValueError, match="parent directories"):
        stage_bundle(make_bundle(), output)
    assert list(real_parent.iterdir()) == []


@pytest.mark.parametrize("schema_version", [True, 1.0, "1"])
def test_rejects_non_integer_schema_version(schema_version):
    bundle = make_bundle()
    bundle["schema_version"] = schema_version
    with pytest.raises(ValueError, match="schema_version"):
        validate_bundle(bundle)
