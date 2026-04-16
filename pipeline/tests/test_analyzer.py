"""Tests for the rule-health analyzer that reads telemetry logs."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analyzer import analyze, format_report

FIXTURES = Path(__file__).parent / "fixtures"


def _write_log(path: Path, records: list[dict]) -> None:
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def test_empty_log_produces_empty_report(tmp_path):
    log = tmp_path / "log.jsonl"
    log.write_text("")
    report = analyze(str(log), str(FIXTURES / "basic-config.yml"))
    assert report["total_edits"] == 0
    # All configured rules appear with zero counts and are classified as dead.
    assert set(report["dead"]) == {"no-compact", "inline-single-use-vars"}
    assert all(row["invocations"] == 0 for row in report["by_rule"].values())


def test_dead_rules_are_identified(tmp_path):
    log = tmp_path / "log.jsonl"
    # Log mentions only one rule; the config has 2.
    _write_log(
        log,
        [
            {
                "ts": "2026-04-16T12:00:00Z",
                "file": "f.php",
                "status": "pass",
                "latency_ms": 5,
                "rules": [
                    {
                        "id": "no-compact",
                        "engine": "script",
                        "verdict": "pass",
                        "severity": "error",
                        "latency_ms": 3,
                    }
                ],
            }
        ],
    )
    report = analyze(str(log), str(FIXTURES / "basic-config.yml"))
    assert "inline-single-use-vars" in report["dead"]
    assert "no-compact" not in report["dead"]


def test_noisy_rules_identified(tmp_path):
    log = tmp_path / "log.jsonl"
    # no-compact fails 4 of 5 edits -> noisy
    records = []
    for i in range(5):
        verdict = "violation" if i < 4 else "pass"
        records.append(
            {
                "ts": f"2026-04-16T12:0{i}:00Z",
                "file": "f.php",
                "status": "blocked" if verdict == "violation" else "pass",
                "latency_ms": 5,
                "rules": [
                    {
                        "id": "no-compact",
                        "engine": "script",
                        "verdict": verdict,
                        "severity": "error",
                        "latency_ms": 3,
                    }
                ],
            }
        )
    _write_log(log, records)
    report = analyze(str(log), str(FIXTURES / "basic-config.yml"), noisy_threshold=0.3)
    assert "no-compact" in report["noisy"]


def test_slow_rules_identified(tmp_path):
    log = tmp_path / "log.jsonl"
    records = [
        {
            "ts": "2026-04-16T12:00:00Z",
            "file": "f.php",
            "status": "pass",
            "latency_ms": 2000,
            "rules": [
                {
                    "id": "no-compact",
                    "engine": "script",
                    "verdict": "pass",
                    "severity": "error",
                    "latency_ms": 1500,
                }
            ],
        }
        for _ in range(5)
    ]
    _write_log(log, records)
    report = analyze(str(log), str(FIXTURES / "basic-config.yml"), slow_threshold_ms=1000)
    assert "no-compact" in report["slow"]


def test_by_rule_aggregates_counts(tmp_path):
    log = tmp_path / "log.jsonl"
    _write_log(
        log,
        [
            {
                "ts": "2026-04-16T12:00:00Z",
                "file": "f.php",
                "status": "blocked",
                "latency_ms": 5,
                "rules": [
                    {
                        "id": "no-compact",
                        "engine": "script",
                        "verdict": "violation",
                        "severity": "error",
                        "latency_ms": 3,
                    },
                    {
                        "id": "no-compact",  # same rule, second file pretend
                        "engine": "script",
                        "verdict": "pass",
                        "severity": "error",
                        "latency_ms": 3,
                    },
                ],
            }
        ],
    )
    report = analyze(str(log), str(FIXTURES / "basic-config.yml"))
    assert report["by_rule"]["no-compact"]["fires"] == 1
    assert report["by_rule"]["no-compact"]["passes"] == 1


def test_format_report_produces_readable_text(tmp_path):
    log = tmp_path / "log.jsonl"
    log.write_text("")
    report = analyze(str(log), str(FIXTURES / "basic-config.yml"))
    text = format_report(report)
    assert "Rule health" in text or "rule health" in text.lower()
