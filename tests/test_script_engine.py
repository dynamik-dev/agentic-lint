"""Tests for script-engine cwd anchoring.

When a script rule runs, its subprocess cwd and `writes: cwd-only`
HOME/TMPDIR confinement should be anchored to the directory containing
`.bully.yml` (the config root), NOT whatever directory the bully process
happens to be in. The PostToolUse hook always chdir's to the config root
first, so the bug is invisible there. But `bully lint /path/to/file
--config /elsewhere/.bully.yml` invoked from a third directory used to
run scripts in that third directory and break (or worse, write to it).

These tests pin the cwd anchoring so any future regression that drops
the `cwd=` kwarg from `subprocess.run` or reverts `capability_env` to
`os.getcwd()` fails loudly.
"""

import os

from bully import capability_env, run_pipeline


def test_run_pipeline_runs_script_with_cwd_at_config_root(tmp_path, monkeypatch):
    """Script subprocess must run with cwd = directory containing .bully.yml.

    Sets up a project at `tmp_path/repo`, then chdirs into an unrelated
    `tmp_path/elsewhere` before invoking `run_pipeline`. The rule's
    script asserts `pwd` matches the project root; if cwd was inherited
    from elsewhere, the script returns non-zero and the pipeline blocks.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    # The project root we expect the script to run in. We resolve() because
    # subprocess.run on macOS passes /private/var/... while tmp_path may
    # surface as /var/... — the realpath comparison must match what
    # subprocess sees.
    expected_cwd = str(repo.resolve())

    cfg = repo / ".bully.yml"
    # Script: `pwd -P` resolves symlinks (matches Path.resolve()), then we
    # compare to the expected value. Exit 1 with a diagnostic if it
    # doesn't match — the violation message will surface the actual cwd.
    cfg.write_text(
        f"""
rules:
  cwd-anchor:
    description: subprocess cwd must equal the config root
    severity: error
    engine: script
    scope: ['**/*.py']
    script: 'actual="$(pwd -P)"; expected="{expected_cwd}"; [ "$actual" = "$expected" ] || {{ echo "cwd mismatch: actual=$actual expected=$expected" >&2; exit 1; }}'
"""
    )
    target = repo / "x.py"
    target.write_text("print('hi')\n")

    # Move our process into a totally unrelated directory. Without the
    # fix, the script subprocess would inherit this cwd and the [ ... = ... ]
    # check would fail.
    monkeypatch.chdir(elsewhere)
    assert os.getcwd() == str(elsewhere.resolve()) or os.getcwd().endswith(
        os.path.basename(str(elsewhere))
    )

    result = run_pipeline(str(cfg), str(target.resolve()), "")
    assert result["status"] == "pass", (
        f"expected pass with cwd={expected_cwd!r}, got {result!r}. "
        f"This means subprocess inherited cwd from os.getcwd() instead "
        f"of being anchored to the config root."
    )


def test_capability_env_cwd_only_uses_passed_cwd_not_os_getcwd(tmp_path, monkeypatch):
    """`writes: cwd-only` must base HOME/TMPDIR on the passed cwd, NOT os.getcwd().

    Anchors the env at `tmp_path/repo` while the bully process runs from
    `tmp_path/elsewhere`. Asserts HOME = repo and TMPDIR = repo/.bully/tmp,
    and that `.bully/tmp` was created under repo (not elsewhere).
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    monkeypatch.chdir(elsewhere)

    env = capability_env(
        {"PATH": "/usr/bin"},
        {"writes": "cwd-only"},
        cwd=str(repo),
    )

    assert env["HOME"] == str(repo)
    assert env["TMPDIR"] == str(repo / ".bully" / "tmp")
    # The tmp dir must exist under repo, not under elsewhere.
    assert (repo / ".bully" / "tmp").is_dir()
    assert not (elsewhere / ".bully").exists()


def test_run_pipeline_writes_cwd_only_lands_under_config_root(tmp_path, monkeypatch):
    """End-to-end: `writes: cwd-only` from run_pipeline puts .bully/tmp under config root.

    Sets up a project at `tmp_path/repo`, chdirs the bully process into
    `tmp_path/elsewhere`, then runs a rule with `writes: cwd-only` that
    asserts `$TMPDIR` lives inside the project root. If the env was
    anchored to os.getcwd() instead of the config root, TMPDIR would
    point at `tmp_path/elsewhere/.bully/tmp` and the rule would fail.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    expected_root = str(repo.resolve())

    cfg = repo / ".bully.yml"
    # The script asserts TMPDIR starts with the expected project root.
    cfg.write_text(
        f"""
rules:
  tmpdir-anchor:
    description: TMPDIR must be inside the config root
    severity: error
    engine: script
    scope: ['**/*.py']
    script: 'case "$TMPDIR" in "{expected_root}"/*) exit 0 ;; *) echo "TMPDIR not anchored: $TMPDIR" >&2; exit 1 ;; esac'
    capabilities:
      writes: cwd-only
"""
    )
    target = repo / "x.py"
    target.write_text("print('hi')\n")

    monkeypatch.chdir(elsewhere)

    result = run_pipeline(str(cfg), str(target.resolve()), "")
    assert result["status"] == "pass", (
        f"expected pass with TMPDIR under {expected_root!r}, got {result!r}. "
        f"This means capability_env used os.getcwd() instead of the config root."
    )
    # And the actual side-effect: .bully/tmp landed under the project, not elsewhere.
    assert (repo / ".bully" / "tmp").is_dir()
    assert not (elsewhere / ".bully").exists()
