"""Tests for spec/callee text rebuilding in src.generate_batch_prompts."""

import json

from src.generate_batch_prompts import extract_spec_block


def _write_spec(tmp_path, spec):
    func_path = tmp_path / "f.c"
    func_path.write_text("int f() { return 0; }")
    with open(str(func_path) + ".spec.json", "w", encoding="utf-8") as f:
        json.dump(spec, f)
    return func_path


class TestExtractSpecBlock:
    def test_required_fields_only(self, tmp_path):
        func_path = _write_spec(
            tmp_path,
            {
                "signature": "f(x)",
                "pre_condition": "x > 0",
                "post_condition": "returns x",
            },
        )
        assert extract_spec_block(func_path) == (
            "f(x)\n\nPre-condition:\nx > 0\n\nPost-condition:\nreturns x"
        )

    def test_optional_property_fields_appended(self, tmp_path):
        func_path = _write_spec(
            tmp_path,
            {
                "signature": "f(x)",
                "pre_condition": "x > 0",
                "post_condition": "returns x",
                "invariants": "queue size <= capacity",
                "resources": "every allocation is freed on all paths",
                "ordering": "lock A acquired before lock B",
            },
        )
        text = extract_spec_block(func_path)
        assert "\n\nInvariants:\nqueue size <= capacity" in text
        assert "\n\nResource-contracts:\nevery allocation is freed on all paths" in text
        assert "\n\nOrdering-constraints:\nlock A acquired before lock B" in text
