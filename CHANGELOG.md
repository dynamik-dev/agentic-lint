# Changelog
All notable changes documented here. Format per Keep a Changelog, semver adherence.

## [Unreleased]
### Planned
See docs/plan.md for the active improvement plan.

## [0.3.0] - 2026-04-21
### Added
- `bully validate --execute-dry-run` runs each script rule against `/dev/null` at config time, surfacing shell and regex syntax errors before a hook ever fires.
- `bully` shell wrapper at the repo root so plugin-installed users can alias or symlink it without `pip install`.
- New test suites covering YAML escape handling, recursive `**` globs, Python version gating, plugin-cache path resolution, and dry-run execution.
- `docs/rule-authoring.md` section documenting YAML escapes, `**` compatibility notes, and the `--explain` / `--execute-dry-run` flags.

### Changed
- `bully-init` Step 6 now runs trust, doctor, telemetry-dir setup, and per-rule smoke tests before handing off — previously it dropped users at a config that might silently fail.
- `doctor` resolves skills and the semantic-evaluator agent from either the legacy `~/.claude/skills/...` path or the plugin cache (`~/.claude/plugins/cache/*/bully/*/{skills,agents}/...`).
- `ruff-clean` rule in the dogfood config prefers `ruff` on `PATH` but now falls back to `.venv/bin/ruff` so Claude Code hooks (which don't inherit the activated venv) catch violations locally instead of only in CI.

### Fixed
- **YAML parser silently miscompiled escapes.** `_parse_scalar` now processes double-quoted escapes (`\\`, `\"`, `\n`, `\t`, `\r`, `\/`, `\0`) and single-quoted `''`. Previously `"\\."` stayed as two backslashes, so every shipped `examples/rules/*.yml` pattern exited 0 on grep's "parentheses not balanced" error instead of matching.
- `filter_rules` now handles `**` recursively on Python 3.10–3.12 via a custom `_scope_matches`. `PurePath.match` only gained recursive `**` in 3.13, so older versions were silently skipping deep paths.
- `doctor` actually compares `sys.version_info` against 3.10 instead of unconditionally printing `[OK] Python X.Y >= 3.10`.
- Three `ruff` SIM violations (`SIM110`, `SIM102`, `SIM108`) in `pipeline.py` that CI caught but the hook's `ruff-clean` rule missed because `ruff` wasn't on `PATH` in the hook env.
- `pipeline/tests/test_validate_cli.py` formatting to satisfy `ruff format --check` in CI.

## [0.2.0] - 2026-04-18
### Added
- `bully bench` command for measuring rule-suite performance: Mode A runs a fixture suite and writes per-run history, Mode B analyzes configured cost, `--compare` diffs the last two runs, and `--full` calls real `messages.create` to record output tokens and actual dollar cost.
- 8 bench fixtures covering script, ast, and semantic engines.
- `phase_timer` hook on `run_pipeline` so callers can observe per-phase latency without patching internals.
- `ruff-clean` rule in the dogfood `.bully.yml` (tolerates a missing `ruff` binary rather than erroring).
- CI runs on every push, not just PRs.

### Changed
- README tagline: "Bully doesn't" → "Bully enforces".
- `bully bench --config` and `--compare` are now mutually exclusive.
- Semantic-evaluator pipeline short-circuits token counting when no semantic rules match.
- Dogfooded new ast rules across the repo.

### Fixed
- ruff `F841` and formatting violations on P1 epic test files that were blocking CI.

## [0.1.0] - 2026-04-16
### Added
- Two-phase lint pipeline (script + semantic rules).
- PostToolUse hook integration for Claude Code.
- Four skills: bully, bully-init, bully-author, bully-review.
- Semantic evaluator subagent with strict VIOLATIONS/NO_VIOLATIONS output contract.
- Opt-in JSONL telemetry (`.bully/log.jsonl`).
- Laravel example rule pack.
- Dogfood config (`.bully.yml`) enforcing stdlib-only runtime, strict bash mode, and more.
