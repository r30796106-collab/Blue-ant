import pytest

from blue_ant.ci_evidence import validate_ci_evidence

REPOSITORY = "r30796106-collab/VoiceStudio"
REF = "upgrade/parallel-track-2026-11-17"
SHA = "a" * 40


def evidence(**updates):
    value = {
        "repository": REPOSITORY,
        "ref": REF,
        "commit_sha": SHA,
        "workflow": "tests",
        "conclusion": "success",
        "required_checks": ["unit", "lint"],
        "passed_checks": ["unit", "lint"],
    }
    value.update(updates)
    return value


def validate(value):
    return validate_ci_evidence(
        value,
        expected_repository=REPOSITORY,
        expected_ref=REF,
        expected_sha=SHA,
    )


def test_accepts_successful_evidence_for_exact_commit():
    result = validate(evidence())
    assert result.commit_sha == SHA
    assert result.required_checks == ("unit", "lint")


@pytest.mark.parametrize(
    "updates",
    [
        {"conclusion": "failure"},
        {"commit_sha": "b" * 40},
        {"ref": "main"},
        {"repository": "someone-else/project"},
        {"passed_checks": ["unit"]},
    ],
)
def test_rejects_failed_or_mismatched_evidence(updates):
    with pytest.raises(ValueError):
        validate(evidence(**updates))


def test_rejects_unknown_schema_fields():
    value = evidence()
    value["approved"] = True
    with pytest.raises(ValueError, match="schema"):
        validate(value)
