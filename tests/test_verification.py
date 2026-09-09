"""Tests for violation-evidence parsing and all-bugs candidate gaps in src.verification."""

import json

import pytest

from src import verification
from src.verification import _parse_failure_gaps


_PROPERTY_LABELS = {
    "invariant": "Invariants",
    "resource": "Resource-contracts",
    "ordering": "Ordering-constraints",
}


def _property_failure(kind, label):
    return (
        "Verification FAILED.\n"
        f"Statements triggering the {kind} violation:\n"
        "unlock();\nread_shared();\n\n"
        f"{label}:\n"
        "shared state is only accessed while holding the lock\n\n"
        "Reason for violation:\n"
        "read_shared() runs after the lock is released"
    )


class TestParseFailureGaps:
    @pytest.mark.parametrize("kind", ["invariant", "resource", "ordering"])
    def test_property_violation_fields_extracted(self, kind):
        gaps = _parse_failure_gaps(_property_failure(kind, _PROPERTY_LABELS[kind]), "post text")

        assert gaps["kind"] == kind
        assert gaps["spec_claim"] == "shared state is only accessed while holding the lock"
        assert gaps["code_evidence"] == "unlock();\nread_shared();"
        assert gaps["trigger_condition"] == "read_shared() runs after the lock is released"
        assert gaps["actual_behavior"] == ""

    def test_post_condition_violation_keeps_original_mapping(self):
        result = (
            "Verification FAILED.\n"
            "Statements triggering the violation:\n"
            "return -1;\n\n"
            "Post-condition:\n"
            "returns a non-negative index\n\n"
            "Reason for violation:\n"
            "the not-found path returns -1"
        )
        gaps = _parse_failure_gaps(result, "spec post text")

        assert gaps["kind"] == "post_condition"
        assert gaps["spec_claim"] == "spec post text"
        assert gaps["actual_behavior"] == "returns a non-negative index"
        assert gaps["code_evidence"] == "return -1;"
        assert gaps["trigger_condition"] == "the not-found path returns -1"


def _write_function(input_dir, name="f.c"):
    input_dir.mkdir(parents=True, exist_ok=True)
    path = input_dir / name
    path.write_text("int f() { return 0; }")
    return path


def _stub_parse(func, spec, knowledge=""):
    return lambda path, language: (func, spec, knowledge)


class TestAllBugsCandidateGaps:
    def test_candidate_gaps_carry_violation_kind(self, tmp_path, monkeypatch):
        input_dir = tmp_path / "input"
        output_dir = tmp_path / "output"
        func_file = _write_function(input_dir)
        spec = "sig\n\nPre-condition:\ntrue\n\nPost-condition:\nreturns 0"

        monkeypatch.setattr(verification, "parse_input_function", _stub_parse("int f() {}", spec))
        monkeypatch.setattr(
            verification,
            "reasoner",
            lambda *args, **kwargs: {
                "status": "MISMATCH",
                "reasoning_complete": True,
                "error": None,
                "violations": [
                    {
                        "kind": "ordering",
                        "statements": "unlock(); read_shared();",
                        "post_condition": None,
                        "reason": "shared state read after the lock is released",
                    },
                    {
                        "kind": "post_condition",
                        "statements": "return -1;",
                        "post_condition": "returns a non-negative index",
                        "reason": "the not-found path returns -1",
                    },
                ],
            },
        )

        _, verdict = verification._verify_single_file(
            str(func_file), str(input_dir), str(output_dir), "c", all_bugs=True
        )

        assert verdict == "MISMATCH"
        candidates = []
        for index in (1, 2):
            with open(output_dir / f"f.bug-{index:03d}.json", encoding="utf-8") as f:
                candidates.append(json.load(f)["gaps"])

        assert candidates[0]["kind"] == "ordering"
        assert candidates[0]["actual_behavior"] == ""
        assert candidates[0]["code_evidence"] == "unlock(); read_shared();"
        assert candidates[0]["trigger_condition"] == "shared state read after the lock is released"
        assert candidates[1]["kind"] == "post_condition"
        assert candidates[1]["actual_behavior"] == "returns a non-negative index"

        with open(output_dir / "f.json", encoding="utf-8") as f:
            result = json.load(f)
        assert result["gaps"]["kind"] == "ordering"
        assert result["bug_count"] == 2
