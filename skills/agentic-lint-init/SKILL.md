---
name: agentic-lint-init
description: Bootstraps a project's .agentic-lint.yml by detecting the tech stack from manifest files, migrating rules from existing linting tools, and generating a baseline config. Use when user says "init agentic lint", "set up agentic lint", "bootstrap lint config", "create lint rules", "agentic-lint init", "initialize agentic lint", or asks to create or generate an agentic lint configuration.
metadata:
  author: dynamik-dev
  version: 1.0.0
  category: workflow-automation
  tags: [linting, code-quality, config-generation, stack-detection]
---

# Agentic Lint Init

Generate a baseline `.agentic-lint.yml` by detecting the stack, migrating existing linter rules, and extending shared rule packs.

## Step 1: Detect the stack

Read manifest files in the project root and map them to rule packs:

| Manifest | Pack candidates |
|---|---|
| `composer.json` | `php`, `laravel` (if `laravel/framework`), `symfony` (if `symfony/framework-bundle`) |
| `package.json` | `node`, `typescript` (if `tsconfig.json` or `devDependencies.typescript`), `react`, `vue`, `next`, `svelte` |
| `pyproject.toml` / `requirements.txt` | `python`, `django`, `fastapi`, `flask` |
| `Cargo.toml` | `rust` |
| `go.mod` | `go` |
| `Gemfile` | `ruby`, `rails` (if `gem 'rails'`) |

Present what was detected and wait for confirmation before continuing.

## Step 2: Migrate existing linter config

Scan for `CLAUDE.md`/`AGENTS.md` style sections, Pest `arch()` tests, and configs from ESLint, Biome, PHPStan, Ruff, RuboCop. For each custom rule, prefer migrating to a native script rule (grep/awk) or a semantic rule over shelling out to the linter binary on every edit.

For each external linter found, ask:

> I found `<linter>`. (a) Migrate its rules into native script/semantic rules (recommended). (b) Keep it running via the pipeline (adds latency, requires binary). (c) Leave it outside the pipeline (CI/pre-commit only).

If the user picks (b), generate a shell-out rule with `severity: warning`.

## Step 3: Ask setup questions

Before writing, ask:

- Default severity for new rules (`error` or `warning`)?
- Enable telemetry directory (`.agentic-lint/telemetry/`) for rule-health review?
- Any globs to exclude (e.g. `vendor/`, `node_modules/`, generated code)?

## Step 4: Extend rule packs

Rather than inlining baseline rules, reference the shared packs in `examples/packs/`. A typical generated config uses `extends:` to pull in a curated pack for the detected stack — for example `extends: ["@agentic-lint/react-ts", "@agentic-lint/node"]` — so the per-project config stays short and updates propagate when the pack is updated. Add project-specific overrides below the `extends` line.

See `examples/packs/` for the available pack IDs and the rules each one contributes.

## Step 5: Write `.agentic-lint.yml`

Write to the project root. The parser expects 2-space indentation for rule IDs under `rules:` and 4-space indentation for each rule's fields. Scope is an inline list.

```yaml
extends:
  - "@agentic-lint/react-ts"

rules:
  rule-id:
    description: "What the rule enforces"
    engine: script        # or semantic
    scope: ["*.ts", "*.tsx"]
    severity: error       # or warning
    script: "command {file}"   # script engine only
```

For multi-line descriptions use a folded scalar (`description: >`). Quote all script values with double quotes. Use `{file}` as the target file placeholder. Formatters use `severity: warning`; correctness rules use `severity: error`.

## Step 6: Summarize and hand off

After writing, print:

```
.agentic-lint.yml generated.

Stack: <detected>
Extends: <packs>
Migrated: <count> rules from <sources>
Overrides: <count>
Excluded globs: <list>
```

Tell the user: "To add project-specific rules, use `/agentic-lint-author`. To audit rule health later, use `/agentic-lint-review`."

## Troubleshooting

- **No manifests found**: Ask the user for the stack and extend the matching pack.
- **Existing `.agentic-lint.yml`**: Offer overwrite, merge (append new rules only), or abort.
- **Binary referenced by a shell-out rule missing**: Write the rule anyway and note the install command in the summary.
