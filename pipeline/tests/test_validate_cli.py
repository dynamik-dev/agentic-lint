"""Tests for the --validate subcommand."""

import subprocess
import sys
from pathlib import Path

PIPELINE = Path(__file__).resolve().parent.parent / "pipeline.py"
FIXTURES = Path(__file__).parent / "fixtures"


def _run(args, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PIPELINE), *args],
        capture_output=True,
        text=True,
        timeout=10,
        cwd=str(cwd) if cwd else None,
    )


def test_validate_clean_config_returns_zero():
    r = _run(["--validate", "--config", str(FIXTURES / "basic-config.yml")])
    assert r.returncode == 0, f"stderr={r.stderr}"
    assert "[OK]" in r.stdout
    assert "rule" in r.stdout.lower()


def test_validate_malformed_config_returns_one(tmp_path):
    bad = tmp_path / ".agentic-lint.yml"
    bad.write_text(
        "rules:\n"
        "\tbad-tabs:\n"
        '    description: "x"\n'
        "    engine: script\n"
        '    scope: "*"\n'
        "    severity: error\n"
        '    script: "exit 0"\n'
    )
    r = _run(["--validate", "--config", str(bad)])
    assert r.returncode == 1
    # ConfigError text should be on stderr
    assert "tab" in r.stderr.lower() or "line" in r.stderr.lower()


def test_validate_unknown_field_fails(tmp_path):
    bad = tmp_path / ".agentic-lint.yml"
    bad.write_text(
        "rules:\n"
        "  r1:\n"
        '    description: "x"\n'
        "    engine: script\n"
        '    scope: "*"\n'
        "    severity: error\n"
        '    script: "exit 0"\n'
        "    frobnicate: nope\n"
    )
    r = _run(["--validate", "--config", str(bad)])
    assert r.returncode == 1
    assert "frobnicate" in r.stderr


def test_validate_missing_file_fails(tmp_path):
    r = _run(["--validate", "--config", str(tmp_path / "does-not-exist.yml")])
    assert r.returncode == 1
    assert "not found" in r.stderr


def test_validate_default_config_path_when_absent(tmp_path):
    # No config, no --config flag: defaults to ./.agentic-lint.yml
    r = _run(["--validate"], cwd=tmp_path)
    assert r.returncode == 1
    assert ".agentic-lint.yml" in r.stderr


def test_validate_invalid_severity_fails(tmp_path):
    bad = tmp_path / ".agentic-lint.yml"
    bad.write_text(
        "rules:\n"
        "  r1:\n"
        '    description: "x"\n'
        "    engine: script\n"
        '    scope: "*"\n'
        "    severity: wild-severity\n"
        '    script: "exit 0"\n'
    )
    r = _run(["--validate", "--config", str(bad)])
    assert r.returncode == 1
    assert "severity" in r.stderr.lower()
