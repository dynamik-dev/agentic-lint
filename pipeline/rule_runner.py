"""Per-rule execution helpers for pipeline.py.

Extracted from the pipeline.py `_run_deterministic` closure so rule
evaluation can be parallelized via a ThreadPoolExecutor while keeping
the main-thread fold (violation/record collection) deterministic.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, replace

from pipeline import Rule, Violation, _is_baselined, _line_has_disable


@dataclass(frozen=True)
class RuleContext:
    """Per-file context passed to every rule evaluator.

    Intentionally frozen + immutable so it is safe to share across worker
    threads. Nothing inside should be mutated.
    """

    file_path: str
    diff: str
    baseline: dict  # keys are (rule_id, rel_path, line, checksum) tuples
    config_path: str | None


@dataclass
class RuleResult:
    """Output of a single rule evaluation, ready for main-thread fold."""

    rule_id: str
    violations: list  # list[Violation] — typed loosely to avoid import cycle
    record: dict
    internal_error: bool = False


def evaluate_rule(
    rule: Rule,
    ctx: RuleContext,
    engine: str,
    executor_fn: Callable[[Rule, RuleContext], list[Violation]],
) -> RuleResult:
    """Run one rule against one file and return a ready-to-fold RuleResult.

    `executor_fn` is the engine-specific runner (e.g. a lambda wrapping
    execute_script_rule or execute_ast_rule). It is called with the rule
    and ctx; it returns raw Violations. This helper then applies
    fix_hint, line-disable filtering, and baseline filtering, and builds
    the rule_records entry matching pipeline.py's historical shape.
    """
    start = time.perf_counter()
    violations = executor_fn(rule, ctx)
    latency_ms = int((time.perf_counter() - start) * 1000)

    if rule.fix_hint:
        violations = [
            replace(v, suggestion=v.suggestion or rule.fix_hint) for v in violations
        ]

    filtered: list[Violation] = []
    for v in violations:
        if _line_has_disable(ctx.file_path, v.line, rule.id):
            continue
        if _is_baselined(ctx.baseline, rule.id, ctx.config_path, ctx.file_path, v.line):
            continue
        filtered.append(v)

    if filtered:
        record = {
            "id": rule.id,
            "engine": engine,
            "verdict": "violation",
            "severity": rule.severity,
            "line": filtered[0].line,
            "latency_ms": latency_ms,
        }
    else:
        record = {
            "id": rule.id,
            "engine": engine,
            "verdict": "pass",
            "severity": rule.severity,
            "latency_ms": latency_ms,
        }

    return RuleResult(rule_id=rule.id, violations=filtered, record=record)
