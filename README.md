<p align="center">
  <img src="bully.png" alt="Bully" width="500" />
</p>

<h1 align="center">Bully: Lint Rules Claude Code Can't Ignore</h1>

<p align="center">
  <strong>The edit doesn't land until your lint rules pass.</strong>
</p>

<p align="center">
  <a href="https://github.com/dynamik-dev/bully/actions/workflows/ci.yml"><img src="https://github.com/dynamik-dev/bully/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <a href="https://github.com/dynamik-dev/bully/releases/latest"><img src="https://img.shields.io/github/v/release/dynamik-dev/bully?label=release" alt="Latest release" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache_2.0-green" alt="Apache 2.0" /></a>
  <img src="https://img.shields.io/badge/python-3.10+-blue" alt="Python 3.10+" />
  <img src="https://img.shields.io/badge/Claude_Code-plugin-5A67D8" alt="Claude Code plugin" />
</p>

<p align="center">
  <a href="#install">Install</a> ·
  <a href="#quick-start">Quick start</a> ·
  <a href="#configuration">Configuration</a> ·
  <a href="#architecture">Architecture</a> ·
  <a href="docs/design.md">Design</a> ·
  <a href="docs/rule-authoring.md">Rule authoring</a> ·
  <a href="docs/telemetry.md">Telemetry</a>
</p>

---

Bully is a `PostToolUse` hook for Claude Code. On every `Edit` and `Write`, it runs your linters (ruff, tsc, eslint, biome, phpstan, clippy, …) and uses an LLM to evaluate plain-English rules against the diff. If anything fails, Claude can't land the edit. Each block feeds the rule back to the agent, so your rules improve its behavior without manual coaching.

Read the [Design doc](docs/design.md) for the architecture, data flow, and baseline contract.

## Install

```text
/plugin marketplace add https://github.com/dynamik-dev/bully
/plugin install bully
```

Restart Claude Code. Then in a project:

```text
> /bully-init
```

`/bully-init` detects your stack, wires your existing linters as passthrough rules, and creates `.bully/` for telemetry. Review the generated `.bully.yml`, tweak, commit.

Manual install, `bully doctor`, model overrides, and uninstall live in [Reference](#reference).

## Quick start

```text
> /bully-init                  # bootstrap a config from your stack
> /bully-author                # add a rule (engine routing + fixture test)
> /bully-review                # prune noisy and dead rules from telemetry
```

```bash
bully baseline-init --glob "src/**/*.ts"   # ignore pre-existing violations
bully guide src/foo.ts                     # which rules apply before editing
bully lint src/foo.ts --print-prompt       # debug the semantic prompt
```

Silence one line when a rule is right in general but wrong here:

```ts
eval(expr); // bully-disable: no-eval reason: sandboxed input
```

## What Bully does

- **Linter passthrough.** `engine: script` rules call your existing linters as subprocesses (`ruff check --quiet {file}`, `tsc --noEmit`). The same checks CI runs, blocking on every edit.
- **Structural patterns.** `engine: ast` rules use [ast-grep](https://ast-grep.github.io/) to match shape, not text. Comments, strings, and formatting variants don't fool them.
- **Prose rules.** `engine: semantic` rules are plain English ("don't derive state with `useEffect`"). The `bully-evaluator` subagent has no `Read` / `Grep` / `Glob` and only sees the diff, so adversarial content can't redirect it.
- **Session rules.** `engine: session` fires at `Stop` over the cumulative changed-set: "auth changed without tests", "migration without rollback", "API changed without changelog". Catches things no per-edit lint can see.
- **Trust + capabilities.** bully won't run any rule until you `bully trust` the config. Per-rule `capabilities:` (`network: false`, `writes: cwd-only`) further gate what scripts can do.
- **Telemetry + review.** Every run appends a JSONL record to `.bully/log.jsonl`. `/bully-review` flags noisy and dead rules; the `bully-scheduler` agent can run on cron and open small PRs to retire them.
- **Authoring + feedforward.** `/bully-init` bootstraps a config. `/bully-author` adds rules with engine routing and fixture testing. `bully guide <file>` lists rules in scope before the agent edits.

## Configuration

One YAML file at `.bully.yml` in your repo root. A flat list of rules; each names what to check, where it applies, severity, and which engine runs it.

```yaml
schema_version: 1

rules:
  ruff-check:
    description: "Code must pass ruff check."
    engine: script
    scope: ["*.py"]
    severity: error
    script: "ruff check --quiet {file}"

  no-any-cast:
    description: "No `as any` casts. Use a precise type or `unknown` plus narrowing."
    engine: ast
    scope: ["src/**/*.ts", "src/**/*.tsx"]
    severity: error
    pattern: "$EXPR as any"

  prefer-derived-state:
    description: >
      React components should not use `useEffect` to derive state from
      props. Compute the value directly during render (or with `useMemo`
      if expensive). Effect-based derivation causes unnecessary renders
      and stale reads.
    engine: semantic
    scope: "src/**/*.tsx"
    severity: warning
```

`/bully-author` routes new rules in priority order: linter passthrough → `engine: ast` → `engine: script` → `engine: semantic`. Sharpest tool first.

Sharing rules across repos:

```yaml
schema_version: 1
extends: ["../shared/bully-base.yml"]

rules:
  # project-specific overrides + additions
```

Local rules override inherited rules of the same id. Full schema and authoring patterns: [Rule authoring](docs/rule-authoring.md).

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                Edit / Write tool call                        │
│                         ↓                                    │
│                  PostToolUse hook                            │
│                         ↓                                    │
│         ┌────────────────────────────────────┐               │
│         │     Phase 1: deterministic         │               │
│         │  script rules    │   ast rules     │               │
│         │  (your linters)  │  (ast-grep)     │               │
│         └────────────────────────────────────┘               │
│                         ↓ pass                               │
│         ┌────────────────────────────────────┐               │
│         │     Phase 2: semantic              │               │
│         │   bully-evaluator subagent         │               │
│         │   (diff only, no Read/Grep/Glob)   │               │
│         └────────────────────────────────────┘               │
│                         ↓                                    │
│             exit 0 (pass)  or  exit 2 (block)                │
└──────────────────────────────────────────────────────────────┘
```

Phase 1 fails fast: deterministic rules block before bully spends a token on the evaluator. Phase 2 only runs when phase 1 passes. Session rules (`engine: session`) live outside this loop; they fire at `Stop` over the cumulative changed-set.

Detail: [Design doc](docs/design.md) · flow image: [`bully-flow.png`](bully-flow.png).

## Reference

<details>
<summary>Prerequisites</summary>

- [Claude Code](https://claude.com/claude-code)
- Python 3.10+ (`python3 --version`)
- For `engine: ast` rules: `ast-grep` on `$PATH` (`brew install ast-grep`, `cargo install ast-grep`, or `pip install ast-grep-cli`). If missing, ast rules skip at runtime with a one-line stderr hint and `bully doctor` flags it.

The pipeline is stdlib-only Python and the hook is a five-line bash wrapper. You don't `pip install` anything to use it.
</details>

<details>
<summary>Verify the install (`bully doctor`)</summary>

```bash
bully doctor
```

Checks Python version, config presence and parse-ability, hook wiring, evaluator-agent registration, and each skill. One line per check, `[OK]` or `[FAIL]`.

If `bully` isn't on `$PATH`, call the pipeline directly:

```bash
python3 "$(ls -d ~/.claude/plugins/cache/*/bully/*/ | tail -1)pipeline/pipeline.py" --doctor
```
</details>

<details>
<summary>Manual install (no plugin)</summary>

```bash
git clone https://github.com/dynamik-dev/bully.git ~/.bully
mkdir -p ~/.claude/skills ~/.claude/agents
for s in bully bully-init bully-author bully-review; do
  ln -sf ~/.bully/skills/$s ~/.claude/skills/$s
done
ln -sf ~/.bully/agents/bully-evaluator.md ~/.claude/agents/bully-evaluator.md
```

Then add to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "$HOME/.bully/pipeline/hook.sh"
          }
        ]
      }
    ]
  }
}
```
</details>

<details>
<summary>Manual invocation</summary>

```bash
bully validate                                  # parse + enum checks
bully lint src/foo.php                          # full pipeline on a file
bully lint src/foo.php --rule no-compact        # isolate one rule
bully lint src/foo.php --print-prompt           # see the semantic prompt
bully show-resolved-config                      # rules after extends:
bully guide src/foo.php                         # rules in scope before editing
bully explain src/foo.php                       # which rules match and why
bully session-start                             # banner for SessionStart hook
```

`bully` is the console script installed by `pip install -e .`. Without that, call the pipeline directly: `python3 ~/.bully/pipeline/pipeline.py --validate` (or with `--file`, `--show-resolved-config`, etc.).
</details>

<details>
<summary>Changing the evaluator model</summary>

Default is `sonnet`. Set the plugin's agent override or edit `model:` in `agents/bully-evaluator.md` in your local plugin cache.
</details>

<details>
<summary>Parallelism</summary>

bully evaluates script and AST rules concurrently within a single file, defaulting to `min(8, os.cpu_count() or 4)` workers. Override via config:

```yaml
execution:
  max_workers: 4
```

Or env (wins over config):

```bash
BULLY_MAX_WORKERS=2 git commit
```

Set `max_workers: 1` to restore serial execution if a rule script needs exclusive access to a resource. Files matching only one rule skip the pool and run inline.
</details>

<details>
<summary>Internal-error handling</summary>

If a rule's evaluator raises a Python exception (not just a non-zero shell exit), bully catches it and emits a blocking `severity=error` violation labeled `internal error: <ExcType>: <msg>`. Other rules in the phase still run, so one bad rule can't take down the whole check.
</details>

<details>
<summary>Telemetry</summary>

`/bully-init` creates `.bully/` and adds it to `.gitignore` (per-developer data, never committed). Each pipeline run appends a JSONL record to `.bully/log.jsonl`. If you opted out during init, `mkdir .bully` later to start recording.

Format and analyzer details: [Telemetry doc](docs/telemetry.md).
</details>

<details>
<summary>Test bench</summary>

bully ships with a local bench for tracking its own speed and input-token cost over time.

**Fixture suite:**

```bash
bully bench                    # run all bench/fixtures/, append bench/history.jsonl
bully bench --compare          # diff the last two runs
bully bench --no-tokens        # skip Anthropic API call, use char-count proxy
bully bench --json             # emit raw run record on stdout
```

Commit a fresh run alongside changes that touch `pipeline/pipeline.py` to make speed/token impact visible in PRs.

**Config cost analysis:**

```bash
bully bench --config path/to/.bully.yml
```

Reports input-token cost: floor tokens, per-rule marginal cost (sorted), diff scaling at 1/10/100/1000 added lines, and per-scope grouping.

Both modes use Anthropic's `messages/count_tokens` endpoint when `ANTHROPIC_API_KEY` is set and the optional `anthropic` SDK is installed (`pip install -e ".[bench]"`). Without either, both fall back to a `len(json.dumps(payload))` proxy and tag output `method: proxy`. By default the bench only calls `count_tokens` (free); pass `--full` to dispatch real evaluator runs against fixtures (uses `messages.create`, opt-in only).
</details>

<details>
<summary>Development</summary>

```bash
cd ~/.bully
pip install -e ".[dev]"   # ruff, shellcheck-py, pytest, pre-commit
bash scripts/lint.sh      # ruff + shellcheck + pytest + dogfood
```

`scripts/dogfood.sh` runs the pipeline against every source file in this repo. `.github/workflows/ci.yml` runs the same checks on every PR.
</details>

<details>
<summary>Uninstall</summary>

Plugin install:

```text
/plugin uninstall bully
/plugin marketplace remove bully-marketplace
```

Manual install:

```bash
rm ~/.claude/skills/bully{,-init,-author,-review}
rm ~/.claude/agents/bully-evaluator.md
# Then remove the PostToolUse block from ~/.claude/settings.json
rm -rf ~/.bully
```
</details>

## Contributing

Issues and PRs welcome. Good places to start:

- New rule pack → `examples/`
- New `engine: ast` pattern → `pipeline/ast_engine.py`
- New skill or evaluator behavior → `skills/` and `agents/bully-evaluator.md`
- Docs → `docs/`

Before contributing read [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md), [SECURITY.md](SECURITY.md), and [CHANGELOG.md](CHANGELOG.md).

## License

Apache 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
