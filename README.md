# agentic-lint

An agent-native lint pipeline for Claude Code. One config file (`.agentic-lint.yml`), one enforcement point (`PostToolUse` hook), one violation format. Works for any language — rules are scoped by file glob, not by language declaration.

## What it does

Every time an agent edits a file, the hook runs a two-phase evaluation:

1. **Script phase** — deterministic checks (grep, awk, or shell-out to a linter). Fast. Fails the tool call on error-severity violations via exit code 2.
2. **Semantic phase** — if the script phase passes, the pipeline hands a unified diff plus rule descriptions to the agent for judgment-based evaluation (e.g. "inline single-use variables").

Violations block the agent's tool call until fixed. Passes are silent.

```
Edit/Write tool call
        |
        v
  find .agentic-lint.yml
        |
        v
  filter rules by scope glob
        |
        +--- Phase 1: script rules
        |       |
        |       +--- error? exit 2, violations on stderr (blocks)
        |       |
        |       +--- pass? continue
        |
        +--- Phase 2: semantic payload
                |
                +--- injected as additionalContext
                     for the agent to evaluate
```

## Why

Traditional linters fragment across tools (PHPStan, Pint, ESLint, Pest arch tests, CLAUDE.md prose). Each has its own config, its own violation format, its own trigger. Agents have to understand all of them.

`agentic-lint` collapses that into a single config the agent actually reads as part of its tool loop. Deterministic rules stay deterministic. Judgment rules live in natural language where the agent reads them directly.

## Install

```bash
pip install -e ".[dev]"
```

Pulls `pytest`, `ruff`, `shellcheck-py` (bundled binary), and `pre-commit`. The runtime itself is stdlib-only and needs no install.

## Quick start

### 1. Bootstrap a config

In a project you want to lint:

```
> /agentic-lint-init
```

The init skill detects your stack, scans for existing linter configs, asks whether to migrate them as shell-outs or keep them in CI, and writes a baseline `.agentic-lint.yml`.

### 2. Wire up the hook

In `.claude/settings.json`:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          { "type": "command", "command": "/path/to/agentic-lint/pipeline/hook.sh" }
        ]
      }
    ]
  }
}
```

### 3. Enable telemetry (optional)

```bash
mkdir .agentic-lint
```

The pipeline appends one JSONL record per run to `.agentic-lint/log.jsonl`. Removing the directory turns logging off.

### 4. Review rule health

After a few hundred edits:

```
> /agentic-lint-review
```

Surfaces noisy rules (fire on most edits), dead rules (never fire), and slow rules. Recommends concrete adjustments.

### 5. Author, modify, or remove rules

To evolve the config without hand-editing YAML:

```
> add a lint rule that bans var_dump() in PHP
> tighten no-db-facade — it's noisy
> apply the recommendations from the last review
> remove deprecated-carbon
```

The `agentic-lint-author` skill walks through engine choice, drafts a rule, tests it against fixtures, and only then writes it to `.agentic-lint.yml`.

## Manual invocation

For authoring and debugging rules without triggering an Edit:

```bash
# Run the full pipeline against a file
python3 pipeline/pipeline.py --config .agentic-lint.yml --file src/foo.php

# Run just one rule
python3 pipeline/pipeline.py --config .agentic-lint.yml --file src/foo.php --rule no-compact

# See the semantic prompt that would be sent to the LLM
python3 pipeline/pipeline.py --config .agentic-lint.yml --file src/foo.php --print-prompt
```

## Tooling

- `scripts/lint.sh` — run all quality checks: ruff, shellcheck, pytest, dogfood.
- `scripts/dogfood.sh` — run the pipeline against every source file in this repo.
- `.github/workflows/ci.yml` — the same checks on every PR.
- `.pre-commit-config.yaml` — optional: `pre-commit install` to run checks before every commit.

## Docs

- [Design](docs/design.md) — architecture, data flow, decisions, trade-offs.
- [Rule authoring](docs/rule-authoring.md) — how to write script and semantic rules, how to test them.
- [Telemetry](docs/telemetry.md) — log format, analyzer usage, self-improvement workflow.

## Layout

```
agentic-lint/
├── pipeline/
│   ├── pipeline.py      # two-phase lint engine
│   ├── analyzer.py      # rule-health analyzer
│   ├── hook.sh          # PostToolUse hook entry point
│   └── tests/           # 66 tests, stdlib-only
├── skills/
│   ├── agentic-lint/          # interprets hook output
│   ├── agentic-lint-init/     # bootstraps .agentic-lint.yml
│   ├── agentic-lint-author/   # adds, modifies, removes rules
│   └── agentic-lint-review/   # audits rule health
├── scripts/             # lint.sh, dogfood.sh
├── examples/            # sample configs
└── .agentic-lint.yml    # this repo's own lint rules (dogfood)
```
