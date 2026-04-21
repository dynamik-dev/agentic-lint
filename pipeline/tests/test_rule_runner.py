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


from rule_runner import evaluate_rule

from pipeline import Rule, Violation


def _make_rule(rid="r1", severity="error", fix_hint=None):
    return Rule(
        id=rid,
        description="test rule",
        engine="script",
        scope="*",
        severity=severity,
        script="true",
        fix_hint=fix_hint,
    )


def test_evaluate_rule_pass_path():
    rule = _make_rule()
    ctx = RuleContext(file_path="f.py", diff="", baseline={}, config_path=None)
    result = evaluate_rule(rule, ctx, "script", executor_fn=lambda r, c: [])
    assert result.rule_id == "r1"
    assert result.violations == []
    assert result.record["id"] == "r1"
    assert result.record["engine"] == "script"
    assert result.record["verdict"] == "pass"
    assert result.record["severity"] == "error"
    assert isinstance(result.record["latency_ms"], int)
    assert result.internal_error is False


def test_evaluate_rule_violation_path():
    rule = _make_rule()
    ctx = RuleContext(file_path="f.py", diff="", baseline={}, config_path=None)
    violation = Violation(
        rule="r1", engine="script", severity="error", line=12, description="bad"
    )
    result = evaluate_rule(rule, ctx, "script", executor_fn=lambda r, c: [violation])
    assert len(result.violations) == 1
    assert result.violations[0].line == 12
    assert result.record["verdict"] == "violation"
    assert result.record["line"] == 12


def test_evaluate_rule_propagates_fix_hint():
    rule = _make_rule(fix_hint="use foo() instead")
    ctx = RuleContext(file_path="f.py", diff="", baseline={}, config_path=None)
    violation = Violation(
        rule="r1", engine="script", severity="error", line=5, description="bad"
    )
    result = evaluate_rule(rule, ctx, "script", executor_fn=lambda r, c: [violation])
    assert result.violations[0].suggestion == "use foo() instead"


def test_evaluate_rule_isolates_exceptions_as_blocking_violation():
    rule = _make_rule(severity="warning")  # prove severity gets overridden to error

    def boom(r, c):
        raise RuntimeError("kaboom")

    ctx = RuleContext(file_path="f.py", diff="", baseline={}, config_path=None)
    result = evaluate_rule(rule, ctx, "script", executor_fn=boom)

    assert result.internal_error is True
    assert len(result.violations) == 1
    v = result.violations[0]
    assert v.rule == "r1"
    assert v.engine == "script"
    assert v.severity == "error"  # blocking, regardless of rule.severity
    assert v.description.startswith("internal error: RuntimeError")
    assert "kaboom" in v.description
    assert result.record["verdict"] == "violation"
    assert result.record["error"] is True


def test_evaluate_rule_truncates_long_exception_messages_to_500_chars():
    rule = _make_rule()

    def boom(r, c):
        raise RuntimeError("x" * 600)

    ctx = RuleContext(file_path="f.py", diff="", baseline={}, config_path=None)
    result = evaluate_rule(rule, ctx, "script", executor_fn=boom)

    assert len(result.violations) == 1
    description = result.violations[0].description
    assert len(description) == 500
    assert description.startswith("internal error: RuntimeError:")
