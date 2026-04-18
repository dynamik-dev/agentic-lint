# Changelog
All notable changes documented here. Format per Keep a Changelog, semver adherence.

## [Unreleased]
### Planned
See docs/plan.md for the active improvement plan.

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
