"""Tests for capability-scoped script execution."""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import _capability_env, parse_config

REPO_ROOT = Path(__file__).resolve().parents[2]
PIPELINE = REPO_ROOT / "pipeline" / "pipeline.py"


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PIPELINE), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def test_capabilities_field_parses(tmp_path):
    cfg = tmp_path / ".bully.yml"
    cfg.write_text(
        """
rules:
  net-rule:
    description: x
    severity: error
    engine: script
    scope: ['**']
    script: 'true'
    capabilities:
      network: false
      writes: cwd-only
"""
    )
    rules = parse_config(str(cfg))
    rule = next(r for r in rules if r.id == "net-rule")
    assert rule.capabilities == {"network": False, "writes": "cwd-only"}


def test_capabilities_network_false_strips_proxy_env():
    """When network: false is declared, the script subprocess should not see HTTP_PROXY etc."""
    base_env = {
        "HTTP_PROXY": "http://x",
        "HTTPS_PROXY": "http://y",
        "ALL_PROXY": "http://z",
        "PATH": "/usr/bin",
    }
    out = _capability_env(base_env, {"network": False, "writes": "cwd-only"})
    assert "HTTP_PROXY" not in out
    assert "HTTPS_PROXY" not in out
    assert "ALL_PROXY" not in out
    assert out["NO_PROXY"] == "*"
    assert out["PATH"] == "/usr/bin"


def test_capabilities_default_is_unrestricted():
    base_env = {"HTTP_PROXY": "http://x", "PATH": "/usr/bin"}
    out = _capability_env(base_env, None)
    assert out == base_env
