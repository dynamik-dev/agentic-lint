"""Tests for the SessionStart-driven banner output."""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PIPELINE = REPO_ROOT / "pipeline" / "pipeline.py"


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PIPELINE), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def test_session_start_prints_rule_count(tmp_path):
    cfg = tmp_path / ".bully.yml"
    cfg.write_text(
        """
rules:
  a:
    description: A
    severity: error
    engine: script
    scope: ['**']
    script: 'true'
  b:
    description: B
    severity: warning
    engine: script
    scope: ['**']
    script: 'true'
"""
    )
    p = _run(["session-start"], tmp_path)
    assert p.returncode == 0
    assert "bully active" in p.stdout
    assert "2 rules" in p.stdout
    assert "bully guide" in p.stdout


def test_session_start_with_no_config_is_silent(tmp_path):
    p = _run(["session-start"], tmp_path)
    assert p.returncode == 0
    assert p.stdout == ""
