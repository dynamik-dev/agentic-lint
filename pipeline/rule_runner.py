"""Per-rule execution helpers for pipeline.py.

Extracted from the pipeline.py `_run_deterministic` closure so rule
evaluation can be parallelized via a ThreadPoolExecutor while keeping
the main-thread fold (violation/record collection) deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass


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
