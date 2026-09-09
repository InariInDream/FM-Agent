"""Tests for src.file_utils._terminal_validation_record_is_valid and _is_valid_spec_json."""

from src.file_utils import (
    _TERMINAL_VALIDATION_STRING_FIELDS,
    _is_valid_info_json,
    _is_valid_spec_json,
    _terminal_validation_record_is_valid,
)


def _valid_spec():
    return {
        "signature": "f(x)",
        "pre_condition": "x > 0",
        "post_condition": "returns x",
    }


def _valid_record():
    record = {field: "text" for field in _TERMINAL_VALIDATION_STRING_FIELDS}
    record.update(
        {
            "id": "bug-001",
            "confirmation_status": "confirmed",
            "attempts": 1,
        }
    )
    return record


class TestTerminalValidationRecordIsValid:
    def test_valid_confirmed_record(self):
        assert _terminal_validation_record_is_valid(_valid_record(), "bug-001") is True

    def test_error_status_is_terminal(self):
        record = _valid_record()
        record["confirmation_status"] = "error"
        assert _terminal_validation_record_is_valid(record, "bug-001") is True

    def test_not_confirmed_status_is_terminal(self):
        record = _valid_record()
        record["confirmation_status"] = "not_confirmed"
        assert _terminal_validation_record_is_valid(record, "bug-001") is True

    def test_non_dict_rejected(self):
        assert _terminal_validation_record_is_valid("nope", "bug-001") is False
        assert _terminal_validation_record_is_valid(None, "bug-001") is False

    def test_wrong_id_rejected(self):
        assert _terminal_validation_record_is_valid(_valid_record(), "bug-002") is False

    def test_empty_expected_bug_id_rejected(self):
        assert _terminal_validation_record_is_valid(_valid_record(), "") is False
        assert _terminal_validation_record_is_valid(_valid_record(), None) is False

    def test_non_terminal_status_rejected(self):
        record = _valid_record()
        record["confirmation_status"] = "pending"
        assert _terminal_validation_record_is_valid(record, "bug-001") is False

    def test_missing_string_field_rejected(self):
        record = _valid_record()
        del record["probe_script"]
        assert _terminal_validation_record_is_valid(record, "bug-001") is False

    def test_non_string_field_rejected(self):
        record = _valid_record()
        record["source_file"] = 123
        assert _terminal_validation_record_is_valid(record, "bug-001") is False

    def test_bool_attempts_rejected(self):
        record = _valid_record()
        record["attempts"] = True
        assert _terminal_validation_record_is_valid(record, "bug-001") is False

    def test_zero_attempts_rejected(self):
        record = _valid_record()
        record["attempts"] = 0
        assert _terminal_validation_record_is_valid(record, "bug-001") is False

    def test_larger_attempts_accepted(self):
        record = _valid_record()
        record["attempts"] = 3
        assert _terminal_validation_record_is_valid(record, "bug-001") is True


class TestIsValidSpecJson:
    def test_required_fields_only_accepted(self):
        assert _is_valid_spec_json(_valid_spec()) is True

    def test_optional_invariants_accepted(self):
        spec = _valid_spec()
        spec["invariants"] = "queue size <= capacity"
        assert _is_valid_spec_json(spec) is True

    def test_empty_invariants_accepted(self):
        spec = _valid_spec()
        spec["invariants"] = ""
        assert _is_valid_spec_json(spec) is True

    def test_non_string_invariants_rejected(self):
        spec = _valid_spec()
        spec["invariants"] = ["queue size <= capacity"]
        assert _is_valid_spec_json(spec) is False

    def test_optional_resources_and_ordering_accepted(self):
        spec = _valid_spec()
        spec["resources"] = "every allocation is freed on all paths"
        spec["ordering"] = "lock A acquired before lock B"
        assert _is_valid_spec_json(spec) is True

    def test_empty_resources_and_ordering_accepted(self):
        spec = _valid_spec()
        spec["resources"] = ""
        spec["ordering"] = ""
        assert _is_valid_spec_json(spec) is True

    def test_non_string_resources_rejected(self):
        spec = _valid_spec()
        spec["resources"] = {"rule": "no leaks"}
        assert _is_valid_spec_json(spec) is False

    def test_non_string_ordering_rejected(self):
        spec = _valid_spec()
        spec["ordering"] = ["A before B"]
        assert _is_valid_spec_json(spec) is False

    def test_unknown_field_still_rejected(self):
        spec = _valid_spec()
        spec["extra"] = "nope"
        assert _is_valid_spec_json(spec) is False

    def test_missing_required_field_rejected(self):
        spec = _valid_spec()
        del spec["post_condition"]
        assert _is_valid_spec_json(spec) is False

    def test_non_string_required_field_rejected(self):
        spec = _valid_spec()
        spec["pre_condition"] = 42
        assert _is_valid_spec_json(spec) is False

    def test_non_dict_rejected(self):
        assert _is_valid_spec_json("nope") is False
        assert _is_valid_spec_json(None) is False


def _valid_info():
    return {
        "callees": [
            {
                "name": "g",
                "signature": "g(x)",
                "pre_condition": "x > 0",
                "post_condition": "returns x",
            }
        ]
    }


class TestIsValidInfoJson:
    def test_required_fields_only_accepted(self):
        assert _is_valid_info_json(_valid_info()) is True

    def test_optional_property_fields_accepted(self):
        info = _valid_info()
        info["callees"][0]["invariants"] = "queue size <= capacity"
        info["callees"][0]["resources"] = "caller frees the returned buffer"
        info["callees"][0]["ordering"] = "caller holds lock A while calling"
        assert _is_valid_info_json(info) is True

    def test_empty_optional_fields_accepted(self):
        info = _valid_info()
        info["callees"][0]["ordering"] = ""
        assert _is_valid_info_json(info) is True

    def test_non_string_optional_field_rejected(self):
        info = _valid_info()
        info["callees"][0]["resources"] = ["caller frees the returned buffer"]
        assert _is_valid_info_json(info) is False

    def test_missing_required_callee_field_rejected(self):
        info = _valid_info()
        del info["callees"][0]["post_condition"]
        assert _is_valid_info_json(info) is False

    def test_unknown_callee_field_rejected(self):
        info = _valid_info()
        info["callees"][0]["extra"] = "nope"
        assert _is_valid_info_json(info) is False
