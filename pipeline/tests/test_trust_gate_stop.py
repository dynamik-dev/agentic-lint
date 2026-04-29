"""Tests for the trust gate on `_cmd_session_record` and `_cmd_stop`.

The PostToolUse hook calls `_cmd_session_record` BEFORE `run_pipeline` (which
is where the trust gate normally fires), and `bully stop` is its own
subcommand. Both must enforce the trust boundary themselves: an untrusted
or mismatched config must NOT create `.bully/`, append to `session.jsonl`,
parse rules, or return a blocking exit code.

These tests override the global conftest BULLY_TRUST_ALL=1 bypass.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import (  # noqa: E402
    _cmd_session_record,
    _cmd_stop,
    _cmd_trust,
)


def _write_config_with_session_rule(tmp_path: Path) -> Path:
    """A config with a session rule that would block (exit 2) if rules ran."""
    p = tmp_path / ".bully.yml"
    p.write_text(
        "schema_version: 1\n"
        "rules:\n"
        "  auth-needs-tests:\n"
        "    description: Auth changed without tests\n"
        "    severity: error\n"
        "    engine: session\n"
        "    when:\n"
        "      changed_any: ['src/auth/**']\n"
        "    require:\n"
        "      changed_any: ['tests/**/*auth*']\n"
    )
    return p


@pytest.fixture
def isolated_trust_store(tmp_path, monkeypatch):
    """Redirect the trust store to a test-local file and drop BULLY_TRUST_ALL."""
    store = tmp_path / "bully-trust.json"
    monkeypatch.setenv("BULLY_TRUST_STORE", str(store))
    monkeypatch.delenv("BULLY_TRUST_ALL", raising=False)
    return store


# ---- _cmd_session_record ------------------------------------------------


def test_session_record_untrusted_does_not_create_bully_dir(tmp_path, isolated_trust_store):
    """An untrusted config must not cause .bully/ to be created."""
    cfg = _write_config_with_session_rule(tmp_path)

    rc = _cmd_session_record(str(cfg), "src/auth/login.py")

    assert rc == 0
    assert not (tmp_path / ".bully").exists()
    assert not (tmp_path / ".bully" / "session.jsonl").exists()


def test_session_record_untrusted_does_not_append(tmp_path, isolated_trust_store):
    """Even if .bully/ already exists, untrusted must not write session.jsonl."""
    cfg = _write_config_with_session_rule(tmp_path)
    # Pre-create the bully dir to prove the gate isn't relying on dir absence.
    (tmp_path / ".bully").mkdir()

    rc = _cmd_session_record(str(cfg), "src/auth/login.py")

    assert rc == 0
    assert not (tmp_path / ".bully" / "session.jsonl").exists()


def test_session_record_writes_after_trust(tmp_path, isolated_trust_store):
    """Sanity: once trusted, session-record resumes its normal behavior."""
    cfg = _write_config_with_session_rule(tmp_path)
    _cmd_trust(str(cfg), refresh=False)

    rc = _cmd_session_record(str(cfg), "src/auth/login.py")

    assert rc == 0
    session_file = tmp_path / ".bully" / "session.jsonl"
    assert session_file.exists()
    assert "src/auth/login.py" in session_file.read_text()


def test_session_record_mismatch_does_not_write(tmp_path, isolated_trust_store):
    """A trust-then-mutate config is 'mismatch' and must also be gated out."""
    cfg = _write_config_with_session_rule(tmp_path)
    _cmd_trust(str(cfg), refresh=False)
    cfg.write_text(cfg.read_text() + "# mutated\n")

    # Make sure no .bully/ exists from prior writes.
    bully_dir = tmp_path / ".bully"
    if bully_dir.exists():
        for f in bully_dir.iterdir():
            f.unlink()
        bully_dir.rmdir()

    rc = _cmd_session_record(str(cfg), "src/auth/login.py")

    assert rc == 0
    assert not bully_dir.exists()


# ---- _cmd_stop ----------------------------------------------------------


def test_stop_untrusted_returns_zero_not_two(tmp_path, isolated_trust_store, capsys):
    """Untrusted config with violations that would otherwise block must exit 0."""
    cfg = _write_config_with_session_rule(tmp_path)
    # Seed a session.jsonl that would trigger the auth-needs-tests rule
    # (which is severity: error and would normally yield exit 2).
    bully_dir = tmp_path / ".bully"
    bully_dir.mkdir()
    (bully_dir / "session.jsonl").write_text('{"file": "src/auth/login.py"}\n')

    rc = _cmd_stop(str(cfg))

    assert rc == 0
    captured = capsys.readouterr()
    # The standard untrusted message must reach stderr.
    assert "not trusted" in captured.err
    assert "bully trust" in captured.err
    # The session-rule failure message must NOT appear -- rules never parsed.
    assert "auth-needs-tests" not in captured.err
    assert "session check failed" not in captured.err


def test_stop_untrusted_does_not_delete_session_file(tmp_path, isolated_trust_store):
    """Trust gate fires before any session.jsonl handling, including cleanup."""
    cfg = _write_config_with_session_rule(tmp_path)
    bully_dir = tmp_path / ".bully"
    bully_dir.mkdir()
    session_file = bully_dir / "session.jsonl"
    session_file.write_text('{"file": "src/auth/login.py"}\n')

    rc = _cmd_stop(str(cfg))

    assert rc == 0
    # The session file should be untouched: the gate aborts before
    # reaching the success-path unlink and before any rule eval.
    assert session_file.exists()
    assert "src/auth/login.py" in session_file.read_text()


def test_stop_mismatch_emits_mismatch_message(tmp_path, isolated_trust_store, capsys):
    """A 'mismatch' (trusted then mutated) config also takes the gated path."""
    cfg = _write_config_with_session_rule(tmp_path)
    _cmd_trust(str(cfg), refresh=False)
    cfg.write_text(cfg.read_text() + "# mutated\n")

    bully_dir = tmp_path / ".bully"
    bully_dir.mkdir()
    (bully_dir / "session.jsonl").write_text('{"file": "src/auth/login.py"}\n')

    rc = _cmd_stop(str(cfg))

    assert rc == 0
    captured = capsys.readouterr()
    assert "changed since last trust" in captured.err
    assert "bully trust --refresh" in captured.err


def test_stop_runs_normally_after_trust(tmp_path, isolated_trust_store, capsys):
    """Sanity: once trusted, stop blocks on session-rule violations as designed."""
    cfg = _write_config_with_session_rule(tmp_path)
    _cmd_trust(str(cfg), refresh=False)

    bully_dir = tmp_path / ".bully"
    bully_dir.mkdir()
    (bully_dir / "session.jsonl").write_text('{"file": "src/auth/login.py"}\n')

    rc = _cmd_stop(str(cfg))

    # With trust granted, the auth-needs-tests rule fires and blocks.
    assert rc == 2
    captured = capsys.readouterr()
    assert "auth-needs-tests" in captured.err
