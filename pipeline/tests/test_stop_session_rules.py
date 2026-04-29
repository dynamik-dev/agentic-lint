"""Tests for session-scope rules and the Stop hook driver."""

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PIPELINE = REPO_ROOT / "pipeline" / "pipeline.py"

sys.path.insert(0, str(REPO_ROOT / "pipeline"))

from pipeline import parse_config  # noqa: E402


def _run(args: list[str], cwd: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PIPELINE), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=env,
    )


def _write_session(bully_dir: Path, files: list[str]) -> None:
    bully_dir.mkdir(exist_ok=True)
    lines = "".join(json.dumps({"file": f}) + "\n" for f in files)
    (bully_dir / "session.jsonl").write_text(lines)


def test_session_engine_rule_parses(tmp_path):
    cfg = tmp_path / ".bully.yml"
    cfg.write_text(
        """
rules:
  auth-needs-tests:
    description: Auth changed without tests
    severity: error
    engine: session
    when:
      changed_any: ['src/auth/**']
    require:
      changed_any: ['tests/**/*auth*']
"""
    )
    rules = parse_config(str(cfg))
    rule = next(r for r in rules if r.id == "auth-needs-tests")
    assert rule.engine == "session"
    assert rule.when == {"changed_any": ["src/auth/**"]}
    assert rule.require == {"changed_any": ["tests/**/*auth*"]}


def test_stop_blocks_when_required_files_absent(tmp_path):
    cfg = tmp_path / ".bully.yml"
    cfg.write_text(
        """
rules:
  auth-needs-tests:
    description: Auth changed without tests
    severity: error
    engine: session
    when:
      changed_any: ['src/auth/**']
    require:
      changed_any: ['tests/**/*auth*']
"""
    )
    _write_session(tmp_path / ".bully", ["src/auth/login.py"])
    p = _run(["stop"], tmp_path)
    assert p.returncode == 2, (p.stdout, p.stderr)
    assert "auth-needs-tests" in p.stderr


def test_stop_passes_when_required_files_present(tmp_path):
    cfg = tmp_path / ".bully.yml"
    cfg.write_text(
        """
rules:
  auth-needs-tests:
    description: Auth changed without tests
    severity: error
    engine: session
    when:
      changed_any: ['src/auth/**']
    require:
      changed_any: ['tests/**/*auth*']
"""
    )
    _write_session(tmp_path / ".bully", ["src/auth/login.py", "tests/test_auth_login.py"])
    p = _run(["stop"], tmp_path)
    assert p.returncode == 0


def test_stop_no_session_file_passes(tmp_path):
    cfg = tmp_path / ".bully.yml"
    cfg.write_text(
        """
rules:
  any-rule:
    description: x
    severity: error
    engine: session
    when:
      changed_any: ['**']
    require:
      changed_any: ['tests/**']
"""
    )
    p = _run(["stop"], tmp_path)
    assert p.returncode == 0


def test_session_record_appends_changed_path(tmp_path):
    cfg = tmp_path / ".bully.yml"
    cfg.write_text("rules: {}\n")
    p = _run(["session-record", "--file", "src/foo.py"], tmp_path)
    assert p.returncode == 0
    lines = (tmp_path / ".bully" / "session.jsonl").read_text().strip().splitlines()
    recorded = [json.loads(line)["file"] for line in lines]
    assert "src/foo.py" in recorded


def test_stop_warning_severity_returns_zero_but_prints(tmp_path):
    cfg = tmp_path / ".bully.yml"
    cfg.write_text(
        """
rules:
  auth-tests-warning:
    description: Auth changed without tests (warning only)
    severity: warning
    engine: session
    when:
      changed_any: ['src/auth/**']
    require:
      changed_any: ['tests/**/*auth*']
"""
    )
    _write_session(tmp_path / ".bully", ["src/auth/login.py"])
    p = _run(["stop"], tmp_path)
    assert p.returncode == 0, (p.stdout, p.stderr)
    # Warning still surfaces in stderr (visible to the user) but doesn't block.
    assert "auth-tests-warning" in p.stderr
