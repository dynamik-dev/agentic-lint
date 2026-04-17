# Changelog
All notable changes documented here. Format per Keep a Changelog, semver adherence.

## [Unreleased]
### Planned
See docs/plan.md for the active improvement plan.

## [0.1.0] - 2026-04-16
### Added
- Two-phase lint pipeline (script + semantic rules).
- PostToolUse hook integration for Claude Code.
- Four skills: agentic-lint, agentic-lint-init, agentic-lint-author, agentic-lint-review.
- Semantic evaluator subagent with strict VIOLATIONS/NO_VIOLATIONS output contract.
- Opt-in JSONL telemetry (`.agentic-lint/log.jsonl`).
- Laravel example rule pack.
- Dogfood config (`.agentic-lint.yml`) enforcing stdlib-only runtime, strict bash mode, and more.
