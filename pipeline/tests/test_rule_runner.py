"""Tests for pipeline.rule_runner — per-rule execution + thread pool driver."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rule_runner import RuleContext, RuleResult


def test_rule_context_carries_expected_fields():
    ctx = RuleContext(file_path="f.py", diff="", baseline={}, config_path="/tmp/.bully.yml")
    assert ctx.file_path == "f.py"
    assert ctx.diff == ""
    assert ctx.baseline == {}
    assert ctx.config_path == "/tmp/.bully.yml"


def test_rule_result_defaults():
    result = RuleResult(rule_id="r1", violations=[], record={"id": "r1"})
    assert result.rule_id == "r1"
    assert result.violations == []
    assert result.record == {"id": "r1"}
    assert result.internal_error is False
