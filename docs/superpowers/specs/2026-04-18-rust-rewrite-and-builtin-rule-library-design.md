# Bully v0.3: Rust Rewrite + Builtin Rule Library

**Status:** Draft
**Date:** 2026-04-18
**Author:** Chris Arter + Claude (brainstorm)

## Summary

Two coupled bets for bully's next major version:

1. **Rewrite the pipeline in Rust** so ast-grep ships bundled as a crate dep (no external install step), startup is ~10× faster, and distribution is a single static binary.
2. **Ship a first-class library of individually-addressable built-in rules**, namespaced by language (`ts.no-any`, `php.no-compact`, `py.no-print`), resolved by a four-line dictionary lookup in the existing `.bully.yml` schema. No separate "packs" concept. Users compose their own rule set by opting in to what they want, with field-level overrides.

These are shipped together because the rule library is the headline feature and the Rust rewrite removes the last external-install friction (ast-grep) before we ask users to adopt it broadly.

## Motivation

The current design doc explicitly says **"Bully does not ship blessed packs"** — `examples/rules/*.yml` is a browseable catalog, not a consumable library. That was the right call when bully was proving out the pipeline. It is now the wrong call: the pipeline works, the engines work, and the biggest friction to adoption is not "I don't understand the config format" — it's "I have to author every rule from scratch."

Every serious linter solves this the same way: ship rules, let users opt in. Biome has ~280 lint rules, ESLint core has ~230, Ruff has ~800. Bully's three engines (script / ast / semantic) can express the *rules* of all of them, plus a class of judgment rules (`inline-single-use-vars`, `extract-complex-logic`) that no AST-only linter can check.

The Rust question is downstream of this. If we're going to ship a library heavy on `engine: ast`, then (a) ast-grep being optional-and-silently-skipped becomes dangerous, and (b) the per-rule subprocess cost compounds. Linking ast-grep's core as a Rust crate fixes both.

## Non-goals

- **Codemods / auto-fix.** Bully describes violations; the agent applies fixes. This doesn't change. Rules that "want" auto-fix behavior (formatters) either stay as shell-outs or are out of scope.
- **Full type inference.** ast-grep is syntactic. Cross-file type analysis (PHPStan level 9, tsc --strict) stays a shell-out via `engine: script`.
- **Replacing Biome/ESLint/Ruff as runtime tools.** Bully ports their *rules*; the canonical tools still have a place in pre-commit and CI. Bully's lane is "agent inner-loop enforcement."
- **Runtime rule fetching from a registry.** Built-in rules are bundled with the binary. A remote/community registry is a later decision, out of scope for v0.3.
- **Multi-file analysis.** Pipeline still sees one file per Edit. Changing that is a separate design.

## Architecture

### Language and runtime

Bully's pipeline becomes a single Rust binary. Key dependencies:

- `ast-grep-core` — bundled, called as a library. No subprocess overhead.
- `serde_yaml` — replaces the hand-rolled YAML subset parser.
- `similar` — unified diff construction (current Python uses `difflib`).
- `globset` — scope matching.
- `serde_json` — payload serialization.
- `clap` — CLI subcommands (`validate`, `lint`, `doctor`, `baseline-init`, `bench`, etc.).
- `rayon` — parallel rule evaluation (enabled in bulk modes; not in the hot PostToolUse path).

The hook entry point stays a small bash wrapper (`pipeline/hook.sh`) for backward-compat, but its only job is to locate `.bully.yml` and exec the binary. The binary handles the full pipeline, including the walk-up search — `hook.sh` shrinks to `exec bully --hook "$@"`.

### Distribution

The plugin ships a platform-specific binary in its cache directory. Supported targets for v0.3:

- `aarch64-apple-darwin` (macOS Apple Silicon)
- `x86_64-apple-darwin` (macOS Intel)
- `x86_64-unknown-linux-gnu` (Linux x86_64)
- `aarch64-unknown-linux-gnu` (Linux ARM)
- `x86_64-pc-windows-msvc` (Windows, best-effort — Claude Code support permitting)

The plugin install path detects arch at `/plugin install` time and places the right binary in `~/.claude/plugins/cache/.../bully/bin/bully`. The hook prepends that directory to `PATH`. If a user's plugin install flow cannot run arch detection, `hook.sh` falls back to `uname`-based selection on first invocation and caches the choice.

Releases: GitHub Actions builds + signs binaries for each tag. Plugin install fetches from the release assets.

### Config schema — what changes

The **only schema change** is how rule IDs are resolved. Everything else (`schema_version`, `extends`, `skip`, `engine`, `scope`, `severity`, `script`, `pattern`, `language`, `fix_hint`) is unchanged.

Resolution (in `resolve_rules`):

```rust
for (rule_id, overrides) in config.rules.iter() {
    if let Some(builtin) = BUILTINS.get(rule_id) {
        merged.insert(rule_id.clone(), merge(builtin, overrides));
    } else {
        merged.insert(rule_id.clone(), validate_full_rule(rule_id, overrides)?);
    }
}
```

Two cases, no branching on ID syntax:

1. **Rule ID exists in the builtin library** → that rule's definition is the base; user-provided fields in the config override it field-by-field.
2. **Rule ID does not exist in the builtin library** → user's entry is validated as a complete rule (all required fields must be present).

No `builtin:` prefix. No dot-detection. No new top-level keys. The `rules:` dict absorbs everything.

#### Example `.bully.yml` after the change

```yaml
schema_version: 1

rules:
  # Opt into a builtin, use its defaults.
  ts.no-any: {}

  # Opt into a builtin, override a field.
  ts.no-console:
    severity: warning

  # Opt into a builtin, narrow its scope.
  php.no-compact:
    scope: ["src/**/*.php"]

  # Local rule, fully self-contained. No ID collision with any builtin.
  no-internal-url-in-tests:
    description: "No production URLs hard-coded in test files"
    engine: script
    scope: "tests/**/*.py"
    severity: error
    script: "grep -nE 'https?://(api|app)\\.' {file} && exit 1 || exit 0"
```

#### Override semantics

- **Patchable fields**: `description`, `scope`, `severity`, `fix_hint`, `script` (for script rules), `pattern` (for ast rules), `language` (for ast rules). User's value replaces the builtin's value for that field.
- **Non-patchable**: `id` (it's the key), `engine` (changing the engine effectively creates a new rule — the user should author a local rule in that case).
- **Merge granularity**: field-level replacement, not deep merge. If a builtin's `scope` is `["**/*.ts", "**/*.tsx"]` and the user writes `scope: "src/**/*.ts"`, the user's value wins entirely (no union).
- **Bare opt-in**: `ts.no-any: {}` or `ts.no-any: null` both mean "include with all defaults." YAML bare nil is sufficient.

#### Disabling a builtin after extending

The existing `extends:` merge order (local-wins-over-inherited) handles most cases. For the rare case where a user wants to inherit a team config but suppress a single builtin it pulled in, we add a `disabled: true` flag at the rule level:

```yaml
extends: ["../team/shared.yml"]
rules:
  ts.no-any:
    disabled: true
```

Disabled rules are dropped from the evaluation set before scope matching. This is a new field but trivial to add.

### Builtin library organization

Built-in rules live inside the binary, not on disk. At compile time, `build.rs` embeds every YAML file under `packs/` into a single `BUILTINS: &[(&str, &str)]` array (rule ID → YAML body), parsed lazily on first config load.

Directory layout in the repo:

```
packs/
  ts/
    no-any.yml
    no-console.yml
    prefer-const.yml
    ...
  py/
    no-print.yml
    no-mutable-default-arg.yml
    ...
  php/
    no-compact.yml
    strict-types.yml
    ...
  common/
    no-trailing-ws.yml
    no-tabs-in-indentation.yml
    no-todo-without-author.yml
    ...
```

One file per rule. Each file's YAML body is a single rule definition:

```yaml
# packs/ts/no-any.yml
description: "No `as any` casts -- use a precise type or `unknown` plus narrowing."
engine: ast
scope: ["**/*.ts", "**/*.tsx"]
severity: error
pattern: "$EXPR as any"
```

The rule ID is derived from the file path (`packs/ts/no-any.yml` → `ts.no-any`). No `id:` field inside the file; the path is the source of truth. This makes adding a rule a single-file operation with no duplicated identifier.

#### Taxonomy

Purely a documentation convention. Recommended namespaces:

- `ts.` — TypeScript (also catches .tsx by default scope)
- `js.` — JavaScript-only rules that don't make sense under TS (rare)
- `py.` — Python
- `php.` — PHP
- `rust.` — Rust
- `go.` — Go
- `rb.` — Ruby
- `react.` — React (applies across TS/JS, default scope handles .tsx/.jsx)
- `next.` — Next.js-specific (framework conventions, e.g., no `<img>`, prefer `<Image>`)
- `laravel.` — Laravel-specific
- `common.` — language-agnostic (whitespace, TODOs, commit-ability checks)

Framework namespaces are peers of language namespaces, not nested under them. A Tailwind rule would be `tailwind.x`, not `ts.tailwind.x` — frameworks aren't 1:1 with a language, and nesting rots the moment a rule applies to more than one language.

None of this is enforced by the schema. The parser treats IDs as opaque dict keys. Taxonomy is documented in `docs/rule-authoring.md`.

### Fixture-based rule verification

Each rule ships with a fixtures directory proving it works:

```
packs/ts/no-any.yml
packs/ts/no-any.fixtures/
  pass.ts          # code that should NOT trigger the rule
  fail.ts          # code that SHOULD trigger the rule
  fail.expected.json  # expected violations (line numbers, rule id)
```

The binary's test harness loads each builtin rule, runs it against its fixtures, and asserts:

- `pass.*` produces zero violations for that rule.
- `fail.*` produces at least one violation, and each expected violation in `fail.expected.json` matches (rule ID + line number).

This replaces the current ad-hoc dogfooding and is the load-bearing verification for LLM-assisted rule porting (see Build-out Strategy below).

CI runs the fixture suite on every PR. A builtin rule without fixtures fails CI.

### Pipeline behavior — unchanged

The core pipeline contract is preserved. Same phases, same payloads, same exit codes, same stdin/stdout/stderr conventions. What changes internally:

- **Config parse**: `serde_yaml` instead of hand-rolled. Same validation errors, same line-numbered messages for unknown keys / tab indentation / missing required fields.
- **ast rule execution**: direct `ast_grep_core` crate calls instead of `std::process::Command::new("ast-grep")`. ast-grep is always present (it's statically linked).
- **Script rule execution**: unchanged — `std::process::Command`, `{file}` substitution, stdin diff, 30s timeout per rule.
- **Diff construction**: `similar` crate (`TextDiff::from_lines`), five lines of context, same synthetic-fallback behavior when `new_string` isn't found on disk (with `line_anchors: "synthetic"` in the payload, same stderr warning, same telemetry record).
- **Baseline + disables**: same file formats (`.bully/baseline.json`, `# bully-disable:` comments), same parsing rules.
- **Telemetry**: same JSONL record shape in `.bully/log.jsonl`.
- **Exit codes**: same contract (`0` pass/evaluate, `2` blocked).
- **Short-circuit**: same `SKIP_PATTERNS` + `~/.bully-ignore` + project `skip:` merge.

A Python user dropping in the Rust binary should see no behavior change on their existing `.bully.yml`, other than ast rules running faster and ast-grep never being missing.

### ast-grep is now required

The "ast-grep optional at runtime" clause in the current design is removed. The binary contains ast-grep; it is never absent. `bully doctor`'s ast-grep check is removed (it's a compile-time guarantee now). The silent-skip-with-hint fallback in `pipeline.py` is deleted.

## Build-out strategy — how the library actually gets built

Writing 200-800 rules is the real work. Approach:

### Phase 1: Hand-seeded canon (v0.3.0 ship)

Author 50-100 rules by hand, covering:

- All three engines (script / ast / semantic) so the loader and fixture harness are exercised.
- Rules that showcase bully's unique lane (semantic judgment rules no other linter has).
- Obvious cross-language rules (no-trailing-ws, no-todo-without-author, no-console).
- Enough TypeScript coverage that a typical TS project gets real value (15-25 rules).

These are the "this is what a great bully rule looks like" reference set. Every subsequent batch is checked against this quality bar.

### Phase 2: LLM-assisted porting (v0.3.x — v0.4.0)

Target the three canonical rule sources in order:

1. **Biome recommended** (~280 rules) — well-documented, has test fixtures, rules are small.
2. **ESLint core** (~230 rules) — older, more variance in quality; skip deprecated.
3. **Ruff default set** (~50 high-value rules, not all 800) — Python coverage.

The porting loop, per rule:

1. Fetch the source rule's description + test fixtures (pass/fail examples) from the upstream repo.
2. Claude generates a candidate `packs/<lang>/<name>.yml` + fixtures + expected violations.
3. Fixture harness runs the candidate against the upstream's fixtures: does our bully rule produce the same pass/fail verdicts?
4. Human reviews anything that doesn't match and either adjusts the pattern or abandons the port (some ESLint rules depend on type info we don't have).

Target pace: batches of 20-30 rules per session. Realistic cadence to ship Biome-recommended-equivalent coverage in 2-4 weeks of part-time work.

### Phase 3: Long tail via community (post-v0.4)

Open a `packs/` contributions path with a PR template requiring fixtures. Bully core maintainers gate on quality, not volume. No promise of completeness; focus on signal.

### What we are NOT porting

- **Formatter rules** (Prettier, Biome format, Black, Pint). These are rewrite-oriented; bully is a violation reporter. The agent applies the fix. Formatters stay in pre-commit/CI for non-agent paths.
- **Type-info-dependent ESLint rules** (e.g., `@typescript-eslint/no-unsafe-*`). ast-grep is syntactic. Either accept the loss or shell out to `tsc` via `engine: script`.
- **Deprecated rules** from any source. We're not recreating history.

## Migration from v0.2

Existing bully users (Python plugin, per-project `.bully.yml` with custom rules) should see a seamless upgrade:

- `/plugin update bully` pulls the new plugin version. The plugin cache directory now contains the Rust binary instead of the Python package.
- Existing `.bully.yml` files work unchanged. No rule needs rewriting.
- `bully doctor` still works — same checks, minus the ast-grep presence check (now compile-time).
- Telemetry, baseline, and disable files are format-compatible; no migration needed.
- Users who opted into ast-grep rules via `pip install ast-grep-cli` can remove that — the binary bundles ast-grep.

The Python package (`pyproject.toml`, `pipeline/*.py`) stays in the repo for one release as a fallback (users who can't run the binary on their platform can still `pip install -e .`). It is not the blessed distribution; docs point at the binary. It gets deleted in v0.4.

## Testing

- **Rust unit tests**: every module (config parser, scope matcher, diff builder, script runner, ast runner, baseline filter, disable parser) has focused tests covering the Python pipeline's current behavior case-by-case. Port the Python `pipeline/tests/` suite first (ideally as `tests/fixtures/` + `tests/*.rs` integration tests using the same YAML and JSON fixtures).
- **Builtin rule fixture suite**: every rule under `packs/` has pass/fail fixtures; CI runs them all.
- **End-to-end hook tests**: a shell-driven suite that invokes the binary with synthetic `PostToolUse` payloads and asserts exit codes, stdout, stderr.
- **Bench**: port `pipeline/bench.py` to a Rust subcommand (`bully bench`). Keep `bench/history.jsonl` format compatible so existing history carries over.
- **Dogfood**: `.bully.yml` at the project root runs every Edit, as today.

## Risks and mitigations

- **Subtle regressions from port**: the Python pipeline has accumulated edge cases (synthetic-diff fallback, extends cycles, tab rejection, script output adapters). Mitigation: port tests before shipping, require test-green to tag v0.3.
- **Windows support**: not a current target, but the move to a compiled binary at least makes it tractable later. Tracking only.
- **Binary size**: static-linked Rust + ast-grep-core is probably 15-25 MB. Larger than a Python script but fine for plugin distribution. Compare: Biome's binary is ~20 MB, Ruff ~10 MB.
- **LLM-porting quality drift**: the fixture harness is the safety net — a rule that doesn't match upstream fixtures doesn't ship. If fixture match rates drop below ~85% for a given source, we slow down and re-audit rather than accumulate debt.
- **Contribution slowdown**: Rust is a narrower contributor pool than Python. Mitigation: the *rules* are YAML, and that's where community work happens. Pipeline changes stay a core-maintainer concern.

## Deliverables for v0.3.0

1. Rust binary with feature parity vs v0.2.0 Python pipeline, passing a ported test suite.
2. `packs/` directory with 50-100 hand-seeded rules, each with fixtures.
3. Plugin install updated to fetch the right binary per arch from GH release assets.
4. `bully doctor` updated (no ast-grep check; version reports the bundled ast-grep-core version).
5. `README.md` and `docs/design.md` updated to reflect the new architecture and the builtin library.
6. Migration note in `CHANGELOG.md`.

Out of scope for v0.3.0, tracked for v0.3.x / v0.4:

- Biome-recommended port.
- ESLint-core port.
- Ruff-default port.
- Community contribution docs / PR template.
- `packs/` browse / search CLI (`bully rules list | grep ts.`).

## Open questions

- **Hook wrapper**: keep `hook.sh` as the `PostToolUse` entry, or have the plugin point the hook directly at the binary? Keeping `hook.sh` is one more level of indirection but lets us preserve the walk-up search in a scriptable place if we need to change it without re-signing binaries. Probably keep it, document it as a thin wrapper.
- **Plugin binary fetch**: do we pull binaries on `/plugin install` or lazily on first hook invocation? Install-time is cleaner UX (no latency on first edit) but requires the plugin system to support download hooks. If it doesn't, first-invocation fetch with a "downloading bully binary..." stderr line is acceptable.
- **Semantic engine changes**: no change planned, but worth noting — the semantic phase still hands a diff + rule descriptions to the evaluator subagent. The Rust binary builds the payload; the agent evaluates it. Nothing crosses a language boundary here that we need to think about.
