"""Tests for reasoner-facing formatting helpers in src.parser."""

from src.parser import format_info_for_reasoner


class TestFormatInfoForReasoner:
    def test_callee_without_optional_fields_unchanged(self):
        info = {
            "callees": [
                {
                    "name": "g",
                    "signature": "g(x)",
                    "pre_condition": "x > 0",
                    "post_condition": "returns x",
                }
            ]
        }
        text = str(format_info_for_reasoner(info))
        assert text == "g(x)\nPre-condition: x > 0\nPost-condition: returns x"

    def test_callee_property_fields_appended(self):
        info = {
            "callees": [
                {
                    "name": "g",
                    "signature": "g(x)",
                    "pre_condition": "x > 0",
                    "post_condition": "returns x",
                    "invariants": "queue size <= capacity",
                    "resources": "caller frees the returned buffer",
                    "ordering": "caller holds lock A while calling",
                }
            ]
        }
        text = str(format_info_for_reasoner(info))
        assert "Invariants: queue size <= capacity" in text
        assert "Resource-contracts: caller frees the returned buffer" in text
        assert "Ordering-constraints: caller holds lock A while calling" in text
