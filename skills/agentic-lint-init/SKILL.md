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

Bootstrap an `.agentic-lint.yml` configuration by detecting the project's tech stack, migrating rules from existing linting tools, and generating sensible baseline rules.

## Instructions

### Step 1: Detect the Tech Stack

Scan the project root for manifest files using the Read tool. Check each of the following in order and report what was found.

| Manifest | Detects |
|---|---|
| `composer.json` | PHP version (from `require.php`), framework (Laravel if `laravel/framework`, Symfony if `symfony/framework-bundle`), package type |
| `package.json` | Node engine version, framework (React/Vue/Next/Svelte from dependencies), TypeScript (from `devDependencies.typescript` or `tsconfig.json`) |
| `Cargo.toml` | Rust edition, workspace members |
| `pyproject.toml` | Python version (from `requires-python`), framework (Django/FastAPI/Flask from dependencies) |
| `requirements.txt` | Python packages (look for Django, FastAPI, Flask, Ruff, Flake8) |
| `go.mod` | Go version, module path |
| `Gemfile` | Ruby version, framework (Rails from `gem 'rails'`, Sinatra from `gem 'sinatra'`) |

After scanning, present a summary to the user:

```
Stack detected:
- PHP 8.4 (Laravel 12) via composer.json
- No Node/TypeScript detected
- No Rust/Python/Go/Ruby detected
```

Wait for the user to confirm the detection is correct before proceeding to Step 2. If something is missing or wrong, adjust.

### Step 2: Scan for Existing Linting Configuration

Scan for existing tooling in two buckets: **rules to migrate** (things the pipeline can enforce natively) and **external linters** (things you may want to keep running but outside the per-edit pipeline).

**Default philosophy: agent-native.** The pipeline should not shell out to heavyweight linters on every Edit. They are slow and they require the binaries to be installed everywhere the agent runs. Prefer grep/awk script rules for greppable patterns, semantic rules for judgment, and reserve linter shell-outs for cases the user explicitly opts into.

**Migrate rules (not binaries) where possible:**

- `CLAUDE.md` or `AGENTS.md` -- scan for style rule sections (headings containing "style", "rules", "conventions", "guidelines"). Extract actionable statements as semantic rules.
- Pest architecture tests (`arch()` in `tests/`) -- migrate namespace and dependency constraints as semantic rules.
- ESLint / Biome / PHPStan / Ruff configs -- for each custom rule, ask whether it can be expressed as a grep/awk pattern (script) or a natural-language rule (semantic) rather than a shell-out. A rule like "no console.log" becomes `grep -n 'console.log' {file}`, not `npx eslint {file}`.
- PHPStan / mypy baseline files -- do not migrate. They are suppression lists, not rules.
- `.editorconfig` / `tsconfig.json` `strict: true` -- do not migrate. Formatting and type-checking compiler settings are not linting.

**External linter integration (opt-in, not default):**

Before adding a linter as a script rule, ask the user:

> I found `<linter>` configured in this project. Three options:
> (a) Migrate its rules into native script/semantic rules (recommended, pipeline stays fast).
> (b) Keep it running via the pipeline (adds N ms per edit, requires the binary installed).
> (c) Leave it outside the pipeline (run in CI / pre-commit only).

Only create a shell-out rule (`vendor/bin/pint --test {file}`, `npx eslint {file}`, etc.) if the user picks (b). Otherwise record option (a) or (c) in the summary and move on.

When you do add a linter shell-out, set `severity: warning` by default. Slow rules that block every edit become painful; warnings still surface the signal without halting the agent.

Present the migration report before proceeding:

```
Existing tooling found:
- CLAUDE.md style section -> 4 semantic rules migrated
- Pest arch() tests -> 2 semantic rules migrated
- PHPStan config -> SKIPPED per user choice (kept in CI)
- Pint -> SKIPPED per user choice (pre-commit only)

Could not migrate automatically:
- phpstan-baseline.neon (suppression list, not rules)
```

### Step 3: Generate Baseline Rules

For each detected stack, add baseline rules that are not already covered by migrated rules. Keep it minimal: 5-10 rules total, not per language. All baselines are agent-native: they use grep/awk primitives or semantic rules. No baselines shell out to installed linters -- that is reserved for the opt-in flow in Step 2.

**PHP baselines:**
- `strict-types`: All PHP files must declare `strict_types=1`
  `script: "head -5 {file} | grep -q 'declare(strict_types=1)' || exit 1"`
- `no-compact`: Do not use `compact()`
  `script: "grep -n 'compact(' {file} && exit 1 || exit 0"`
- `full-type-hints`: Every method must have full type hints and return types (semantic)

**Laravel-specific baselines (when Laravel detected):**
- `no-db-facade`: Do not use `DB::` facade, use `Model::query()`
  `script: "grep -n 'DB::' {file} && exit 1 || exit 0"`
- `no-event-helper`: Do not use `event()` helper, use `Event::dispatch()`
  `script: "grep -nP '(?<![a-zA-Z_])event\\(' {file} && exit 1 || exit 0"`

**TypeScript baselines:**
- `no-any`: Do not use `any` type
  `script: "grep -nE ':\\s*any\\b' {file} && exit 1 || exit 0"`
- `no-ts-ignore`: Do not use `@ts-ignore` (use `@ts-expect-error` with an explanation)
  `script: "grep -n '@ts-ignore' {file} && exit 1 || exit 0"`
- `type-imports`: Imports used only for types should use `import type` (semantic)

**JavaScript baselines:**
- `no-console-log`: No `console.log` in production code
  `script: "grep -nE 'console\\.log\\(' {file} && exit 1 || exit 0"`
- `no-debugger`: No `debugger` statements
  `script: "grep -n 'debugger;' {file} && exit 1 || exit 0"`

**Python baselines:**
- `no-print-debug`: No bare `print()` calls in non-test code (use logging)
  `script: "grep -nE '^[[:space:]]*print\\(' {file} && exit 1 || exit 0"`
- `type-hints`: All functions should have type annotations (semantic)

**Rust baselines:**
- `no-unwrap`: Avoid `.unwrap()` and `.expect()` in non-test code (semantic)
- `no-todo-macro`: No `todo!()` or `unimplemented!()` left in source
  `script: "grep -nE '(todo|unimplemented)!\\(' {file} && exit 1 || exit 0"`

**Go baselines:**
- `errcheck`: Check error return values are handled (semantic)
- `no-fmt-println`: No `fmt.Println` in non-test code (use structured logging)
  `script: "grep -n 'fmt.Println' {file} && exit 1 || exit 0"`

**Cross-language baselines (always add):**
- `no-orchestration-labels`: No sprint/wave/task/phase/v1/v2 labels in source code (semantic)
- `no-todo-without-ticket`: `TODO` and `FIXME` comments must reference a ticket id
  `script: "grep -nE '(TODO|FIXME)(?!.*(#|[A-Z]+-)[0-9]+)' {file} && exit 1 || exit 0"` (severity: warning)

Do not add a baseline rule if a migrated rule already covers the same concern. Prefer narrower, greppable rules over broad ones -- a rule that fires on every edit is noise the pipeline will report as noisy in rule-health reviews.

### Step 4: Write the Configuration

Write `.agentic-lint.yml` to the project root. Every rule follows this format:

```yaml
rules:
  rule-id:
    description: "What the rule enforces"
    engine: script  # or semantic
    scope: "*.php"  # file glob
    severity: error  # or warning
    script: "command {file}"  # script engine only, omit for semantic
```

Rules for formatting tools (Pint, ESLint --fix, Ruff format) should use `severity: warning`. Rules for correctness (type errors, banned patterns, architecture violations) should use `severity: error`.

For multi-line descriptions, use YAML folded scalars:

```yaml
  rule-id:
    description: >
      Multi-line description that gets folded
      into a single line by the YAML parser.
    engine: semantic
    scope: "*.php"
    severity: error
```

Quote all script values with double quotes. Use `{file}` as the placeholder for the target file path.

### Step 5: Print Summary

After writing the file, print a structured summary:

```
.agentic-lint.yml generated with N rules:

Stack: PHP 8.4 (Laravel 12)

Migrated rules (M):
  - phpstan-check (script, from phpstan.neon)
  - pint-formatting (script, from pint)
  - no-compact (semantic, from CLAUDE.md)
  - full-type-hints (semantic, from CLAUDE.md)

Baseline rules (B):
  - strict-types (script)
  - no-db-facade (script)
  - no-event-helper (script)
  - no-orchestration-labels (semantic)

Not migrated:
  - phpstan-baseline.neon (suppression list)

Review the generated config and let me know if you want to adjust
any rules before committing.
```

### Step 6: Ask for Review

Do not commit the file. Tell the user to review it and ask if they want any changes. Common adjustments:
- Changing severity (error vs warning)
- Adjusting scope globs
- Adding or removing rules
- Tweaking script commands
- Converting between script and semantic engines

Apply requested changes and regenerate the summary.

## Examples

### Example 1: PHP/Laravel Project

User says: "init agentic lint"

Actions:
1. Scan project root. Find `composer.json` with `laravel/framework` and PHP 8.4.
2. Find `phpstan.neon`, default Pint config, `CLAUDE.md` with style rules.
3. Ask the user whether to migrate PHPStan/Pint as script shell-outs or keep them in CI/pre-commit. Migrate CLAUDE.md style section as 4 semantic rules either way.
4. Add baselines: `strict-types`, `no-compact`, `no-db-facade`, `no-event-helper`, `no-orchestration-labels`.
5. Write `.agentic-lint.yml` with the agreed rule set.
6. Print summary and ask user to review.

### Example 2: TypeScript/React Project

User says: "set up agentic lint for this project"

Actions:
1. Scan project root. Find `package.json` with React, TypeScript, and `tsconfig.json`.
2. Find `eslint.config.js` and `biome.json`.
3. Ask whether to shell out to ESLint/Biome from the pipeline. Default recommendation: keep them in CI, use agent-native rules per-edit.
4. Add baselines: `no-any`, `no-ts-ignore`, `no-console-log`, `no-debugger`, `no-orchestration-labels`.
5. Write `.agentic-lint.yml`.
6. Print summary and ask user to review.

### Example 3: Multi-Language Project

User says: "bootstrap lint config"

Actions:
1. Scan project root. Find `composer.json` (PHP 8.3, no framework) and `package.json` (TypeScript, Vue).
2. Find `phpstan.neon`, `.eslintrc.json`.
3. Ask the user per-linter whether to include it in the per-edit pipeline. Default to leaving them in CI.
4. Add baselines per language. PHP: `strict-types`, `no-compact`. TS: `no-any`, `no-ts-ignore`. Cross: `no-orchestration-labels`, `no-todo-without-ticket`.
5. Write `.agentic-lint.yml`.
6. Print summary and ask user to review.

## Troubleshooting

### Error: No manifest files found

Cause: The project root has no recognized manifest files.
Solution: Ask the user what language and framework they use, then skip to Step 3 and generate baselines for the stated stack. Note in the summary that stack was manually specified.

### Error: Existing .agentic-lint.yml already exists

Cause: The project already has an agentic lint config.
Solution: Ask the user if they want to overwrite it, merge new rules into it, or abort. If merging, read the existing config, identify rules not already present, and append only new rules.

### Error: Linting tool binary not found

Cause: A script rule references a tool that is not installed (e.g., `vendor/bin/pint` missing).
Solution: Still generate the rule but add a YAML comment noting the tool needs to be installed. Suggest the install command in the summary.

## Performance Notes

- Read manifest files directly rather than running language-specific tooling for detection.
- Scan for config files using Glob, not recursive shell find commands.
- Keep the generated config compact. Prefer fewer well-chosen rules over exhaustive coverage.
- The init skill generates the config once. The agentic-lint hook skill handles ongoing enforcement.
