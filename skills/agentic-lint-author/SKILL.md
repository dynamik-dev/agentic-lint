---
name: agentic-lint-author
description: Authors, modifies, or removes rules in `.agentic-lint.yml`. Use when the user says "add a lint rule for X", "ban Y", "tighten <rule-id>", "make <rule-id> a warning", "convert <rule-id> to semantic", "remove <rule-id>", "change the scope of <rule-id>", or asks to apply recommendations from `/agentic-lint-review`. Always tests a rule against a fixture before writing it to the config.
metadata:
  author: dynamik-dev
  version: 1.0.0
  category: workflow-automation
  tags: [linting, rule-authoring, config-editing, self-improvement]
---

# Agentic Lint Author

Interactive authoring for `.agentic-lint.yml`. Add, modify, or remove rules after the project has been bootstrapped. Every proposed rule is tested against a fixture before being written.

## When to use

Triggered by:

- "Add a lint rule for X" / "Ban Y in the codebase"
- "Tighten `<rule-id>` -- it's noisy"
- "Make `<rule-id>` a warning" / "Promote `<rule-id>` to error"
- "Convert `<rule-id>` to a semantic rule" (or vice versa)
- "Change the scope of `<rule-id>` to Y"
- "Remove `<rule-id>`"
- "Apply the `/agentic-lint-review` recommendations"
- "Add the rule the review suggested"

Not triggered by:

- Initial bootstrap -- that's `agentic-lint-init`.
- Auditing rule health -- that's `agentic-lint-review`.
- Interpreting hook output during an edit -- that's `agentic-lint`.

If the project has no `.agentic-lint.yml` yet, stop and tell the user to run `/agentic-lint-init` first. Authoring assumes a config exists.

## Workflow selector

Identify which operation the user is asking for, then jump to that section.

| User request | Section |
|---|---|
| Add a rule (any phrasing) | [Adding a new rule](#adding-a-new-rule) |
| Tighten / loosen / change the pattern or description | [Modifying an existing rule](#modifying-an-existing-rule) |
| Change severity or scope | [Modifying an existing rule](#modifying-an-existing-rule) |
| Convert engine (script ↔ semantic) | [Modifying an existing rule](#modifying-an-existing-rule) |
| Remove a rule | [Removing a rule](#removing-a-rule) |
| Apply review recommendations | [Applying review recommendations](#applying-review-recommendations) |

If the request is ambiguous, ask one clarifying question before proceeding.

## Adding a new rule

### Step 1: Classify the rule

Ask yourself, then confirm with the user if uncertain:

- **Greppable**? Can the violation be matched by a regex or simple text search? → `script` rule.
- **Judgment-based**? Does it depend on how the code is used elsewhere, or on semantic intent? → `semantic` rule.

Rules of thumb:
- Banned function names, banned imports, required headers, forbidden strings → script.
- "Inline variables used once", "extract complex logic", "prefer contracts over concretes" → semantic.
- Formatting and style preferences that a linter already handles → shell out to the linter as a script rule, or keep it in CI.

### Step 2: Gather the fields

Collect:
- `id` -- kebab-case, unique, 2-4 words. Check `.agentic-lint.yml` for collisions.
- `description` -- one sentence for script rules; a prescriptive prompt with an example violation and compliant alternative for semantic rules.
- `engine` -- `script` or `semantic`.
- `scope` -- narrowest glob that covers the target files. Use a list if multiple globs are genuinely needed.
- `severity` -- `warning` for new rules you're trialing; `error` only when confident.
- `script` (script rules only) -- the command, with `{file}` as the path placeholder.

### Step 3: Test the rule before writing (MANDATORY)

Never write a rule to `.agentic-lint.yml` without running it through the testing protocol below. A rule that looks right but doesn't actually fire is worse than no rule.

Use the Write tool to create two fixture files -- one that must trigger the rule, one that must not:

```bash
# Violating fixture -- must produce exit 2
/tmp/agentic-lint-probe-violating.<ext>

# Compliant fixture -- must produce exit 0
/tmp/agentic-lint-probe-clean.<ext>
```

Use the Bash tool to create a draft config (existing config + proposed rule):

```bash
cp .agentic-lint.yml /tmp/agentic-lint-draft.yml
```

Use the Edit tool on `/tmp/agentic-lint-draft.yml` to append the proposed rule.

Run the pipeline with `--rule` to isolate the new rule:

```bash
# Must exit 2 (blocked)
python3 pipeline/pipeline.py \
  --config /tmp/agentic-lint-draft.yml \
  --file /tmp/agentic-lint-probe-violating.<ext> \
  --rule <new-rule-id>

# Must exit 0 (pass) -- no false positives on compliant code
python3 pipeline/pipeline.py \
  --config /tmp/agentic-lint-draft.yml \
  --file /tmp/agentic-lint-probe-clean.<ext> \
  --rule <new-rule-id>
```

For **script rules**: both exits must match expectations. If violating exits 0, the pattern is wrong. If clean exits 2, the pattern has false positives.

For **semantic rules**: run `--print-prompt` instead of asserting exit codes:

```bash
python3 pipeline/pipeline.py \
  --config /tmp/agentic-lint-draft.yml \
  --file /tmp/agentic-lint-probe-violating.<ext> \
  --rule <new-rule-id> \
  --print-prompt
```

Read the rendered prompt, then mentally evaluate it against both fixtures. If the prompt is unclear or would miss obvious violations, rewrite the description and re-test.

### Step 4: Write the rule to the real config

Only after Step 3 passes, use the Edit tool to append the rule to `.agentic-lint.yml`. Append to the end of the `rules:` block -- preserves existing formatting and comments.

Keep the indentation consistent with surrounding rules (2-space rule id, 4-space field, 6+ space for folded scalars).

### Step 5: Sanity-check

Run the pipeline against 2-3 existing project files to make sure the new rule does not mass-flag the codebase:

```bash
python3 pipeline/pipeline.py --config .agentic-lint.yml --file <existing-file> --rule <new-rule-id>
```

If this repo is the project (dogfood), also run:

```bash
bash scripts/dogfood.sh
```

If dogfood fails or the new rule flags a long list of existing files, the rule is probably too broad. Decide: either narrow the rule, or treat the flag as a real code cleanup task before committing.

### Step 6: Clean up fixtures

```bash
rm -f /tmp/agentic-lint-probe-*.* /tmp/agentic-lint-draft.yml
```

Report what you did and invite the user to review the config before committing.

## Modifying an existing rule

Same testing discipline applies. The only difference is Step 4 edits an existing block instead of appending.

### Locating the rule block

The YAML format is fixed-indent:

```yaml
  rule-id:          # 2-space indent, trailing colon
    description: … # 4-space indent
    engine: …
    scope: …
    severity: …
    script: …
```

Use the Read tool on `.agentic-lint.yml`, find the block for `<rule-id>`. It runs from `  <rule-id>:` through the last field line before the next `  <next-id>:` or end-of-file.

### Common modifications

| Change | Edit |
|---|---|
| Severity | Replace `severity: error` with `severity: warning` (or vice versa) on that line. |
| Scope | Replace the `scope: …` line. Use list form `["*.php", "*.blade.php"]` when multiple globs are needed. |
| Script pattern | Replace the `script: …` line. Keep `{file}` as the placeholder. |
| Description | Replace the `description: …` line, or if using folded scalar (`>`), replace the indented lines that follow. |
| Engine switch | Replace `engine: script` with `engine: semantic` and delete the `script:` line. Going the other direction, add a `script:` line and rewrite the description to be mechanical. |

### Always re-test after modification

A change that seems cosmetic often affects behavior (e.g. narrowing a regex can miss a valid match). Rerun Step 3 of [Adding a new rule](#adding-a-new-rule) against fresh fixtures before writing.

## Removing a rule

### Step 1: Confirm the rule is genuinely unused

Check the telemetry log for recent usage if available:

```bash
grep '"id": "<rule-id>"' .agentic-lint/log.jsonl | tail -10
```

If the rule has fired recently, challenge the removal. "Noisy" and "dead" are different outcomes -- a noisy rule usually wants tightening, not removal.

### Step 2: Locate and delete

Use the Read tool to locate the block. Use the Edit tool to delete from `  <rule-id>:` through the last field line of that rule.

### Step 3: Sanity-check

```bash
bash scripts/dogfood.sh  # if in this repo
# or
python3 pipeline/pipeline.py --config .agentic-lint.yml --file <existing-file>
```

Confirm the config still parses and the remaining rules still fire as expected.

## Applying review recommendations

When the user has just run `/agentic-lint-review` and asks to apply the recommendations, treat each recommendation as a targeted modification.

### Typical mappings

| Review finding | Modification |
|---|---|
| "Noisy script rule" | Tighten the regex (word boundaries, exclude comments / docblocks). Re-test. |
| "Noisy semantic rule" | Sharpen the description (the description IS the prompt). Add an example. Re-test with `--print-prompt`. |
| "Dead rule, scope probably wrong" | Try broadening the scope; if still dead after a check, propose removal. |
| "Dead rule, genuinely obsolete" | Remove. |
| "Slow rule" | If it's a linter shell-out, demote to `warning` or remove from the pipeline and recommend CI/pre-commit. |
| "Semantic rule with stable mechanical fix" | Draft an equivalent `script` rule, test it, replace. Keep the semantic rule as fallback if the mechanics are not fully deterministic. |

Apply one recommendation at a time. Test each one before moving to the next. Never batch several rule changes into a single edit -- if something breaks you want to know which change broke it.

## Testing discipline (mandatory)

The non-negotiable invariants for any authoring operation:

1. Fixtures are created before the rule is tested.
2. Both a violating and a compliant fixture exist (or `--print-prompt` is used for semantic rules).
3. The draft rule is tested in a temp config, not the real config.
4. Exit codes match expectations before the rule is written to `.agentic-lint.yml`.
5. After writing, the config is sanity-checked against at least one existing file.
6. Temp fixtures and draft configs are removed at the end.

If any of these cannot be satisfied -- for example, you cannot construct a plausible fixture -- the rule is probably over- or under-specified. Rework it before writing.

## YAML editing discipline

The pipeline's YAML parser is deliberately constrained. Stay inside what it handles:

- 2-space indent for rule ids.
- 4-space indent for fields.
- 6+ space indent for folded scalar continuation lines.
- Quote script values with double quotes when they contain special characters.
- Inline comments are allowed (the parser strips them).
- List form `["*.php", "*.ts"]` is supported for scope; use it when a rule applies to multiple extensions.

Never reformat the whole file during authoring. Only touch the lines that belong to the rule being added, modified, or removed. Preserving formatting preserves git history.

## Rule quality checks

Before writing any rule, verify:

- [ ] The description reads as a clear instruction, not as project documentation.
- [ ] The scope is as narrow as possible.
- [ ] Script rules exit 0 on clean and non-zero on violating fixtures.
- [ ] Semantic rules include at least one violation example and one compliant example in the description.
- [ ] The id is unique in the config and uses kebab-case.
- [ ] The severity matches intent (error blocks; warning reports).
- [ ] New rules default to `severity: warning` unless confidence is high.

Duplicate of the checklist in `docs/rule-authoring.md` -- kept here so the skill is self-contained.

## Examples

### Example 1: add a simple script rule

User: "add a rule that bans var_dump() in PHP files"

Actions:

1. Classify: greppable → script.
2. Draft:
   ```yaml
   no-var-dump:
     description: "Do not use var_dump() -- use logging or proper assertions."
     engine: script
     scope: "*.php"
     severity: error
     script: "grep -nE '(^|[^a-zA-Z_])var_dump\\(' {file} && exit 1 || exit 0"
   ```
3. Fixtures:
   ```php
   <!-- /tmp/agentic-lint-probe-violating.php -->
   <?php var_dump($x);
   ```
   ```php
   <!-- /tmp/agentic-lint-probe-clean.php -->
   <?php $prefix_var_dump = 1;  // word-boundary should prevent match
   ```
4. Test against draft config:
   ```
   violating: exit 2  ✓
   clean:     exit 0  ✓
   ```
5. Append rule to `.agentic-lint.yml`. Sanity-check against `src/Foo.php`. Clean up fixtures. Done.

### Example 2: tighten a noisy rule

User: "the review said no-db-facade is noisy, tighten it"

Current rule:
```yaml
no-db-facade:
  script: "grep -n 'DB::' {file} && exit 1 || exit 0"
```

Problem: matches `DB::` inside docblocks and string literals.

Proposal: exclude lines that start with `*` (docblock continuation) and lines where `DB::` is inside quotes.

Quick win: require `DB::` to follow whitespace or `(` (i.e. it's a real identifier start):

```yaml
no-db-facade:
  script: "grep -nE '(^|[^a-zA-Z_>])DB::' {file} | grep -vE '^\\s*\\*' && exit 1 || exit 0"
```

Test against:
- Violating: `$users = DB::table('users')->get();` → exit 2.
- Clean docblock: ` * See DB:: in the old docs.` → exit 0.
- Clean method: `->myDB::foo()` → exit 0 (preceded by letter).

On pass, Edit the script line of the existing rule. Sanity-check, report.

### Example 3: convert a semantic rule to a script rule

User: "the review says inline-single-use-vars produces the same fix over and over -- make it a script rule"

Caution: semantic rules are semantic for a reason. Check whether the "same fix over and over" holds across all edits or just a subset. If a subset, a script rule would only cover that subset and the semantic rule should stay.

If the mechanical pattern is truly universal (e.g. "any assignment-then-immediate-return is a violation"), a script rule like:

```yaml
no-assign-then-return:
  script: "awk '/^\\s*\\$[a-zA-Z_][a-zA-Z0-9_]*\\s*=.*;\\s*$/ {var=$0; next} var && /^\\s*return\\s+\\$[a-zA-Z_][a-zA-Z0-9_]*\\s*;/ {print NR\": assign-then-return\"; exit 1} {var=\"\"}' {file}"
```

can catch the easy cases. Keep the semantic rule to catch the cases this misses. Don't replace -- layer.

Test, write, re-run the review in a few hundred edits to see whether the semantic rule is now quiet.

### Example 4: remove a genuinely dead rule

User: "remove deprecated-carbon, the review says it hasn't fired in 500 edits"

Actions:
1. Confirm: `grep '"deprecated-carbon"' .agentic-lint/log.jsonl | wc -l` → 0.
2. Read `.agentic-lint.yml`, locate the `deprecated-carbon:` block.
3. Edit the file to delete those lines.
4. Sanity-check the remaining config parses: `python3 pipeline/pipeline.py --config .agentic-lint.yml --file src/Foo.php`.
5. Report. User commits.

## Troubleshooting

### Rule id collision

If the proposed id already exists in the config, either:
- Propose a different id (e.g. `no-var-dump-v2` → but never use version labels in ids; pick a semantic alternative like `no-var-dump-strict`).
- Ask the user whether to replace the existing rule. If replacing, treat as a modification operation.

### Pattern matches more than expected

The most common script-rule bug. Causes:
- Missing word boundaries.
- Not anchoring at start of line when the rule is line-oriented.
- Matching inside strings, comments, or docblocks.

Fix by narrowing. Use `grep -E` with `[^a-zA-Z_]` guards, or pipe through `grep -v` to exclude comment lines.

### Pattern does not match when it should

Causes:
- Greedy regex needs escaping.
- Using `grep` features that need `-E` (extended) or `-P` (PCRE, including lookahead/lookbehind).
- File has trailing whitespace that breaks an anchored pattern.

Test the pattern in isolation first:

```bash
grep -nE 'your-pattern' /tmp/agentic-lint-probe-violating.<ext>
```

before wrapping it in the `&& exit 1 || exit 0` idiom.

### Rule id is fine but scope matches unexpected files

`PurePath.match` is right-anchored. `*.ts` matches `foo.ts` and `src/foo.ts`. It does not match a glob with a different shape. If the scope doesn't match what you expect, test in Python:

```python
from pathlib import PurePath
PurePath("src/app/foo.ts").match("*.ts")   # True
PurePath("src/app/foo.ts").match("src/*.ts")  # False (single level)
PurePath("src/app/foo.ts").match("**/foo.ts") # True
```

### Editing .agentic-lint.yml triggers the hook

If the hook is active and you edit `.agentic-lint.yml`, the pipeline runs against the config file itself. Harmless unless you have a rule scoped to `*.yml` that flags its own content. If a rule does flag the config, that rule is probably over-broad -- fix the scope.

## What this skill does not do

- Bootstrap a new `.agentic-lint.yml` (use `agentic-lint-init`).
- Audit rule health (use `agentic-lint-review`).
- Commit changes to git. You write the file; the user commits.
- Edit rules across multiple projects in one pass. One config at a time.
- Auto-promote semantic rules to script rules without user confirmation.

## Performance notes

- Every test runs `pipeline.py` once per fixture, typically under 50 ms.
- The draft config sits in `/tmp` and is removed at the end. The real `.agentic-lint.yml` is touched only once per authoring operation.
- If the test loop takes more than a minute, you're probably re-running the full suite instead of using `--rule`. Use `--rule` to isolate the rule under test.
