"""Tests for the skill eval harness's pure logic (`bench/run_skill_evals.py`).

The skill-eval driver lives in `bench/` (added to pytest `pythonpath`). These
cover the P0 statistics + aggregation fixes — multi-epoch confidence intervals,
errored-run exclusion (an infra failure must NOT be scored as 0%), and the
baseline paired delta — none of which touch the `claude` subprocess, so they
run fast and offline.
"""

from __future__ import annotations

import math
import statistics

import run_skill_evals as rse

_Z95 = 1.959963984540054


# ----- mean_ci ----------------------------------------------------------------


def test_mean_ci_reports_mean_sem_and_95_ci():
    xs = [0.8, 1.0, 0.6, 1.0, 0.8]
    s = rse.mean_ci(xs)
    assert s["n"] == 5
    assert abs(s["mean"] - 0.84) < 1e-9
    sd = statistics.stdev(xs)
    assert abs(s["stddev"] - sd) < 1e-9
    assert abs(s["sem"] - sd / math.sqrt(5)) < 1e-9
    # 95% CI half-width is 1.96 * SEM, symmetric around the mean.
    assert abs((s["ci_high"] - s["mean"]) - _Z95 * s["sem"]) < 1e-9
    assert abs((s["mean"] - s["ci_low"]) - _Z95 * s["sem"]) < 1e-9


def test_mean_ci_single_value_has_zero_width_ci():
    s = rse.mean_ci([0.5])
    assert s["n"] == 1
    assert s["mean"] == 0.5
    assert s["sem"] == 0.0
    assert s["ci_low"] == 0.5 and s["ci_high"] == 0.5


def test_mean_ci_empty_returns_none_mean_not_zero():
    # The crux of the P0-C bug: an absent measurement is None, never 0.0.
    s = rse.mean_ci([])
    assert s["n"] == 0
    assert s["mean"] is None


def test_mean_ci_ignores_none_entries():
    s = rse.mean_ci([1.0, None, 1.0])
    assert s["n"] == 2
    assert s["mean"] == 1.0


# ----- execution_plan ---------------------------------------------------------


def test_execution_plan_single_config_is_n_epochs():
    assert rse.execution_plan(epochs=3, baseline=False) == [
        ("with_skill", 1),
        ("with_skill", 2),
        ("with_skill", 3),
    ]


def test_execution_plan_baseline_adds_without_skill_arm():
    assert rse.execution_plan(epochs=2, baseline=True) == [
        ("with_skill", 1),
        ("with_skill", 2),
        ("without_skill", 1),
        ("without_skill", 2),
    ]


# ----- _seed_workspace --------------------------------------------------------


def test_seed_workspace_uses_configuration_and_run_index(tmp_path):
    skill = tmp_path / "skills" / "demo"
    (skill / "evals" / "files").mkdir(parents=True)
    (skill / "evals" / "files" / "x.txt").write_text("hi")
    eval_dir = tmp_path / "eval-1"
    ws = rse._seed_workspace(
        eval_dir,
        skill,
        ["evals/files/x.txt"],
        configuration="without_skill",
        run_index=2,
    )
    assert ws == eval_dir / "without_skill" / "run-2"
    assert (ws / "outputs" / "evals" / "files" / "x.txt").read_text() == "hi"


# ----- aggregate --------------------------------------------------------------


def _run(eval_id, config, pass_rate, *, quality=None, time_s=1.0, name="e"):
    """A minimal per-(eval, config, epoch) summary as cmd_execute appends."""
    return {
        "eval_id": eval_id,
        "eval_name": name,
        "configuration": config,
        "mode": "single-turn",
        "result": {
            "pass_rate": pass_rate,
            "quality_overall": quality,
            "time_seconds": time_s,
        },
    }


def test_aggregate_multi_epoch_pass_rate_has_ci():
    runs = [
        _run(1, "with_skill", 1.0),
        _run(1, "with_skill", 0.5),
        _run(1, "with_skill", 1.0),
    ]
    b = rse.aggregate("s", "exec", "grader", runs, epochs=3)
    pe = next(p for p in b["per_eval"] if p["eval_id"] == 1)
    assert abs(pe["pass_rate"]["mean"] - (2.5 / 3)) < 1e-9
    assert pe["pass_rate"]["n"] == 3
    assert pe["epochs"] == 3
    assert pe["errored_epochs"] == 0
    assert "with_skill" in b["run_summary"]


def test_aggregate_excludes_errored_epoch_from_rate():
    # One graded epoch (1.0) + one grader failure (None) -> mean is 1.0, not 0.5.
    runs = [_run(1, "with_skill", 1.0), _run(1, "with_skill", None)]
    b = rse.aggregate("s", "exec", "grader", runs, epochs=2)
    pe = next(p for p in b["per_eval"] if p["eval_id"] == 1)
    assert pe["pass_rate"]["mean"] == 1.0
    assert pe["pass_rate"]["n"] == 1
    assert pe["errored_epochs"] == 1


def test_aggregate_all_errored_eval_is_none_not_zero():
    runs = [_run(1, "with_skill", None), _run(1, "with_skill", None)]
    b = rse.aggregate("s", "exec", "grader", runs, epochs=2)
    pe = next(p for p in b["per_eval"] if p["eval_id"] == 1)
    assert pe["pass_rate"]["mean"] is None
    assert pe["errored_epochs"] == 2
    # The suite number must not silently absorb the failure as a 0.0.
    assert b["run_summary"]["with_skill"]["pass_rate"]["mean"] is None
    assert b["run_summary"]["with_skill"]["evals_scored"] == 0
    assert b["run_summary"]["with_skill"]["errored_runs"] == 2


def test_aggregate_suite_clusters_on_eval_not_epochs():
    # Two evals, one epoch each: suite mean is over 2 evals (clustered), not 2 rows.
    runs = [
        _run(1, "with_skill", 1.0, name="a"),
        _run(2, "with_skill", 0.0, name="b"),
    ]
    b = rse.aggregate("s", "exec", "grader", runs, epochs=1)
    suite = b["run_summary"]["with_skill"]["pass_rate"]
    assert abs(suite["mean"] - 0.5) < 1e-9
    assert suite["n"] == 2


def test_aggregate_baseline_reports_paired_delta():
    runs = [
        _run(1, "with_skill", 1.0, name="a"),
        _run(2, "with_skill", 1.0, name="b"),
        _run(1, "without_skill", 0.0, name="a"),
        _run(2, "without_skill", 0.5, name="b"),
    ]
    b = rse.aggregate("s", "exec", "grader", runs, epochs=1)
    delta = b["baseline_delta"]["pass_rate"]
    # Per-eval deltas [1.0, 0.5] -> mean uplift 0.75 over n=2 paired evals.
    assert abs(delta["mean"] - 0.75) < 1e-9
    assert delta["n"] == 2
    assert b["metadata"]["configurations"] == ["with_skill", "without_skill"]


def test_aggregate_no_baseline_block_without_control_arm():
    b = rse.aggregate("s", "exec", "grader", [_run(1, "with_skill", 1.0)], epochs=1)
    assert b["baseline_delta"] is None
