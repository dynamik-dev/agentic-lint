"""Tests for --doctor diagnostic output."""

import json
import subprocess
import sys
from pathlib import Path

PIPELINE = Path(__file__).resolve().parent.parent / "pipeline.py"


def _run_doctor(cwd: Path, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    import os

    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(PIPELINE), "--doctor"],
        capture_output=True,
        text=True,
        timeout=10,
        cwd=str(cwd),
        env=env,
    )


def test_doctor_all_pass(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / ".agentic-lint.yml").write_text(
        "rules:\n"
        "  r1:\n"
        '    description: "desc"\n'
        "    engine: script\n"
        '    scope: "*.py"\n'
        "    severity: error\n"
        '    script: "exit 0"\n'
    )

    # Per-project settings contain the hook
    (project / ".claude").mkdir()
    (project / ".claude" / "settings.json").write_text(
        json.dumps({"hooks": {"PostToolUse": [{"hooks": [{"command": "/path/to/hook.sh"}]}]}})
    )

    # Fake HOME with required skills + agent
    home = tmp_path / "home"
    home.mkdir()
    skills = home / ".claude" / "skills"
    for suffix in (
        "agentic-lint",
        "agentic-lint-init",
        "agentic-lint-author",
        "agentic-lint-review",
    ):
        (skills / suffix).mkdir(parents=True)
        (skills / suffix / "SKILL.md").write_text("# skill\n")
    agents = home / ".claude" / "agents"
    agents.mkdir(parents=True)
    (agents / "agentic-lint-evaluator.md").write_text("# eval\n")

    r = _run_doctor(
        project,
        env_extra={
            "HOME": str(home),
            "CLAUDE_HOME": str(home / ".claude"),
        },
    )
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert "[OK] Python" in r.stdout
    assert "[OK] config present" in r.stdout
    assert "[OK] config parses" in r.stdout
    assert "[OK] PostToolUse hook wired" in r.stdout
    assert "[OK] evaluator agent" in r.stdout
    assert "[OK] skill agentic-lint present" in r.stdout


def test_doctor_missing_config_fails(tmp_path):
    # No .agentic-lint.yml in project
    project = tmp_path / "project"
    project.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    r = _run_doctor(
        project,
        env_extra={
            "HOME": str(home),
            "CLAUDE_HOME": str(home / ".claude"),
        },
    )
    assert r.returncode == 1
    assert "[FAIL] no .agentic-lint.yml" in r.stdout


def test_doctor_missing_hook_fails(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / ".agentic-lint.yml").write_text(
        "rules:\n"
        "  r1:\n"
        '    description: "d"\n'
        "    engine: script\n"
        '    scope: "*"\n'
        "    severity: error\n"
        '    script: "exit 0"\n'
    )
    home = tmp_path / "home"
    home.mkdir()
    r = _run_doctor(
        project,
        env_extra={
            "HOME": str(home),
            "CLAUDE_HOME": str(home / ".claude"),
        },
    )
    assert r.returncode == 1
    assert "[FAIL] no PostToolUse hook" in r.stdout


def test_doctor_missing_evaluator_agent_fails(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / ".agentic-lint.yml").write_text(
        "rules:\n"
        "  r1:\n"
        '    description: "d"\n'
        "    engine: script\n"
        '    scope: "*"\n'
        "    severity: error\n"
        '    script: "exit 0"\n'
    )
    # Provide the hook entry so we isolate the agent-missing case.
    (project / ".claude").mkdir()
    (project / ".claude" / "settings.json").write_text(
        json.dumps({"hooks": {"PostToolUse": [{"hooks": [{"command": "hook.sh"}]}]}})
    )
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    r = _run_doctor(
        project,
        env_extra={
            "HOME": str(home),
            "CLAUDE_HOME": str(home / ".claude"),
        },
    )
    assert r.returncode == 1
    assert "[FAIL] evaluator agent missing" in r.stdout


def test_doctor_malformed_config_fails(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / ".agentic-lint.yml").write_text(
        "rules:\n"
        "\tbad-tabs:\n"  # tab indent -> parse error
        '    description: "x"\n'
        "    engine: script\n"
        '    scope: "*"\n'
        "    severity: error\n"
        '    script: "exit 0"\n'
    )
    home = tmp_path / "home"
    home.mkdir()
    r = _run_doctor(
        project,
        env_extra={
            "HOME": str(home),
            "CLAUDE_HOME": str(home / ".claude"),
        },
    )
    assert r.returncode == 1
    assert "[FAIL] config parse error" in r.stdout
