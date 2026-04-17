# agentic-lint

An agent-native lint pipeline for Claude Code. One config file (`.agentic-lint.yml`), one enforcement point (`PostToolUse` hook), one violation format. Works for any language -- rules are scoped by file glob, not by language declaration.

## What actually happens

```
$ # Claude edits app.ts and adds a console.log.
$ # The PostToolUse hook runs .agentic-lint.yml against the edit.
$ # no-console-log (script rule) fires -- exit code 2.
$ # Claude's Edit tool call is blocked; the violation text is fed back.
$ # Claude removes the console.log and re-edits. Hook passes. Done.
```

No extra prompt, no reminder in CLAUDE.md, no "please remember to". The rule fired, the tool call blocked, the agent adjusted.

## The config

A `.agentic-lint.yml` is a flat list of rules. Each rule says what to check, where it applies, how bad it is, and which engine runs it -- `script` (deterministic shell command) or `semantic` (natural-language rule the agent evaluates against the diff):

```yaml
schema_version: 1

rules:
  no-console-log:
    description: "No `console.log` in committed source -- use the project logger."
    engine: script
    scope: ["src/**/*.ts", "src/**/*.tsx"]
    severity: error
    script: "grep -nE 'console\\.log\\(' {file} && exit 1 || exit 0"

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

The first rule runs a grep on every edited `.ts`/`.tsx`; the second ships the diff to the agent with the description as the evaluation prompt. No plugins, no DSL -- just globs, shell, and prose.

Starter packs for common stacks live in [`examples/packs/`](examples/packs/) (react-ts, nextjs, django, fastapi, go, rails, rust-cli). Pull one in as a baseline:

```yaml
schema_version: 1
extends: ["@agentic-lint/react-ts"]

rules:
  # your project-specific rules here
```

Local rules override pack rules of the same id.

## How it works

Every `Edit` / `Write` tool call triggers the hook, which runs two phases:

1. **Script phase** -- deterministic checks (grep, awk, shell-out to a linter). Fast. Fails the tool call on error-severity violations via exit code 2.
2. **Semantic phase** -- if the script phase passes, the pipeline hands a unified diff plus rule descriptions to the evaluator subagent. Structured verdicts come back; the parent session surfaces them.

Violations block the tool call until fixed. Passes are silent. Same trigger, same output format, same fix loop -- across every language in the repo. Deterministic rules stay as shell. Judgment rules ("inline single-use variables", "don't derive state with `useEffect`") live as plain English the agent evaluates against the diff.

## Prerequisites

- [Claude Code](https://claude.com/claude-code)
- Python 3.10+ (`python3 --version`)

The pipeline is stdlib-only Python and the hook is a five-line bash wrapper. You do **not** `pip install` anything to use it.

## Install

### 1. Clone somewhere stable

```bash
git clone https://github.com/dynamik-dev/agentic-lint.git ~/.agentic-lint
```

The path has to be stable so Claude Code finds the hook every time. Anywhere works (`~/.agentic-lint`, `~/code/agentic-lint`, `/opt/agentic-lint`) -- use the same path in step 2.

### 2. Symlink skills and the evaluator agent

```bash
mkdir -p ~/.claude/skills ~/.claude/agents
for s in bully bully-init bully-author bully-review; do
  ln -sf ~/.agentic-lint/skills/$s ~/.claude/skills/$s
done
ln -sf ~/.agentic-lint/agents/bully-evaluator.md ~/.claude/agents/bully-evaluator.md
```

Project scope: symlink into `.claude/skills` / `.claude/agents` at your project root so the skills only activate there. To change the evaluator model, edit `model:` in `~/.agentic-lint/agents/bully-evaluator.md` (default is `sonnet`).

### 3. Register the PostToolUse hook

Add this block to `~/.claude/settings.json` (or `.claude/settings.json` in a project):

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          { "type": "command", "command": "$HOME/.agentic-lint/pipeline/hook.sh" }
        ]
      }
    ]
  }
}
```

Restart Claude Code so it picks up the new skills, agent, and hook.

### Verify the install

```bash
python3 ~/.agentic-lint/pipeline/pipeline.py --doctor
```

`--doctor` checks Python version, config presence and parse-ability, hook wiring in `settings.json`, evaluator-agent registration, and each skill symlink. One line per check, `[OK]` or `[FAIL]`. All `[OK]` means you're done. A one-line installer (`curl -sSL .../install.sh | bash`) is on the roadmap.

## Quick start (per project)

### 1. Bootstrap a config

```
> /bully-init
```

The init skill detects your stack, scans for existing linter configs, asks a couple of questions, and writes a baseline `.agentic-lint.yml`. If a starter pack matches your stack, it wires up `extends:` for you. Review, tweak, commit.

### 2. Adopting in a repo with existing violations

A fresh rule across an existing codebase lights up every pre-existing problem. Baseline the current state so only *new* violations block edits:

```bash
python3 ~/.agentic-lint/pipeline/pipeline.py --baseline-init --glob "src/**/*.ts"
```

That writes `.agentic-lint/baseline.json`. Future runs ignore anything recorded there. See [docs/design.md](docs/design.md) for the contract.

### 3. Silencing a specific line

When a rule is right in general but wrong on one line:

```ts
eval(expr); // agentic-lint-disable: no-eval reason: sandboxed input
```

Use sparingly. Telemetry tracks disables so noisy rules surface in `/bully-review`.

### 4. Telemetry (optional)

```bash
mkdir .agentic-lint
```

One JSONL record per pipeline run lands in `.agentic-lint/log.jsonl`. Already in `.gitignore` -- per-developer data. After a few hundred edits, run `/bully-review` for noisy / dead / slow rule analysis.

### 5. Evolve the config

```
> add a lint rule that bans var_dump() in PHP
> tighten no-db-facade -- it's noisy
> apply the recommendations from the last review
```

The `bully-author` skill walks through engine choice, drafts the rule, tests it against fixtures, and only then writes to `.agentic-lint.yml`.

## Manual invocation

For authoring and debugging rules without triggering an Edit:

```bash
PIPE=~/.agentic-lint/pipeline/pipeline.py

python3 "$PIPE" --validate                                   # parse + enum checks
python3 "$PIPE" --file src/foo.php                           # full pipeline on a file
python3 "$PIPE" --file src/foo.php --rule no-compact         # isolate one rule
python3 "$PIPE" --file src/foo.php --print-prompt            # see the semantic prompt
python3 "$PIPE" --show-resolved-config                       # rules after extends:
```

## Uninstall

```bash
rm ~/.claude/skills/bully{,-init,-author,-review}
rm ~/.claude/agents/bully-evaluator.md
# Then remove the PostToolUse block from ~/.claude/settings.json
rm -rf ~/.agentic-lint
```

## Development

```bash
cd ~/.agentic-lint
pip install -e ".[dev]"   # ruff, shellcheck-py, pytest, pre-commit
bash scripts/lint.sh      # ruff + shellcheck + pytest + dogfood
```

`scripts/dogfood.sh` runs the pipeline against every source file in this repo. `.github/workflows/ci.yml` runs the same checks on every PR.

## Docs

- [Design](docs/design.md) -- architecture, data flow, baseline contract, trade-offs.
- [Rule authoring](docs/rule-authoring.md) -- script and semantic rules, testing.
- [Telemetry](docs/telemetry.md) -- log format, analyzer, self-improvement workflow.

## License

MIT. See [LICENSE](LICENSE).

## Contributing

Issues and PRs welcome. Please read [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) before participating, [SECURITY.md](SECURITY.md) for how to report vulnerabilities, and [CHANGELOG.md](CHANGELOG.md) for release notes.
