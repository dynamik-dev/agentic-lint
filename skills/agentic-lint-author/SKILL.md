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

Interactive authoring for `.agentic-lint.yml`. Every proposed rule is tested against a fixture before being written.

If no `.agentic-lint.yml` exists, stop and tell the user to run `/agentic-lint-init` first.

See `docs/rule-authoring.md` for full field reference and the rule quality checklist.

## Triggers

- "Add a lint rule for X" / "Ban Y"
- "Tighten `<rule-id>`" / "Make `<rule-id>` a warning" / "Promote `<rule-id>` to error"
- "Convert `<rule-id>` to semantic" (or vice versa)
- "Change the scope of `<rule-id>`"
- "Remove `<rule-id>`"
- "Apply the `/agentic-lint-review` recommendations"

Not triggered by bootstrap (`agentic-lint-init`), audit (`agentic-lint-review`), or hook-output interpretation (`agentic-lint`).

## Engine choice

- `script` -- greppable: banned names, banned imports, required headers, forbidden strings, formatting shell-outs.
- `semantic` -- judgment-based: "inline single-use vars", "extract complex logic", "prefer contracts over concretes".

If unsure, ask the user. Do not auto-promote semantic to script without confirmation.

## Scope globs

- `PurePath.match` is right-anchored. `*.ts` matches `foo.ts` and `src/foo.ts`. `src/*.ts` is single-level only. `**/foo.ts` for deep matches.
- Use the narrowest glob that covers the target files.
- List form for multiple extensions: `["*.php", "*.blade.php"]`.

## Severity

- `warning` for new or trial rules.
- `error` only when confidence is high and a false positive is acceptable as a block.

## Fixture-testing protocol (MANDATORY)

Never write a rule to `.agentic-lint.yml` without running this protocol first.

1. Create two fixture files with the Write tool:
   - `/tmp/agentic-lint-probe-violating.<ext>` -- must trigger the rule.
   - `/tmp/agentic-lint-probe-clean.<ext>` -- must not trigger.
2. Copy the current config to a draft:
   ```bash
   cp .agentic-lint.yml /tmp/agentic-lint-draft.yml
   ```
3. Edit `/tmp/agentic-lint-draft.yml` to append the proposed rule.
4. Run the pipeline with `--rule` against each fixture:
   ```bash
   # Script rule -- violating must exit 2, clean must exit 0
   python3 pipeline/pipeline.py \
     --config /tmp/agentic-lint-draft.yml \
     --file /tmp/agentic-lint-probe-violating.<ext> \
     --rule <new-rule-id>

   python3 pipeline/pipeline.py \
     --config /tmp/agentic-lint-draft.yml \
     --file /tmp/agentic-lint-probe-clean.<ext> \
     --rule <new-rule-id>
   ```
5. For **semantic rules**, use `--print-prompt` instead of asserting exit codes. Read the rendered prompt and confirm it would correctly judge both fixtures. If unclear, sharpen the description and re-test.
6. Only on pass, proceed to the write step.
7. Clean up: `rm -f /tmp/agentic-lint-probe-*.* /tmp/agentic-lint-draft.yml`.

Invariants: fixtures exist before testing; both violating and compliant fixtures (or `--print-prompt`) are exercised; the draft config is used, not the real one; exit codes match expectations before writing.

## YAML edit pattern for `.agentic-lint.yml`

The parser is fixed-indent. Do not reformat the file.

```yaml
  rule-id:          # 2-space indent, trailing colon
    description: … # 4-space indent
    engine: script | semantic
    scope: "*.ext" # or ["*.a", "*.b"]
    severity: warning | error
    script: "…{file}… && exit 1 || exit 0"   # script rules only
```

- 2-space indent for rule ids, 4-space for fields, 6+ for folded scalar continuations.
- Double-quote script values containing special chars.
- Inline comments allowed.
- Append new rules to the end of the `rules:` block.
- Only touch lines belonging to the rule being added, modified, or removed.

## Adding a new rule

1. Classify (script vs semantic).
2. Collect `id` (kebab-case, unique), `description`, `engine`, `scope`, `severity`, and `script` if applicable.
3. Run the fixture-testing protocol.
4. Edit `.agentic-lint.yml` to append the rule.
5. Sanity-check against 2-3 existing project files:
   ```bash
   python3 pipeline/pipeline.py --config .agentic-lint.yml --file <existing-file> --rule <new-rule-id>
   ```
   In this repo, also run `bash scripts/dogfood.sh`. If the rule mass-flags the codebase, narrow it or treat the flags as real cleanup.
6. Report and invite the user to review before committing.

## Modifying an existing rule

1. Use Read to locate the `  <rule-id>:` block (runs to the next `  <next-id>:` or EOF).
2. Apply the change:
   - Severity: swap `severity: error` / `severity: warning`.
   - Scope: replace the `scope:` line.
   - Script: replace the `script:` line; keep `{file}` as the placeholder.
   - Description: replace the `description:` line (or the indented continuation for folded scalars).
   - Engine switch: change `engine:` and add/remove the `script:` line; rewrite the description accordingly.
3. Rerun the fixture-testing protocol against fresh fixtures. Cosmetic-looking changes can shift behavior.
4. Sanity-check and report.

## Removing a rule

1. Confirm it is genuinely unused:
   ```bash
   grep '"id": "<rule-id>"' .agentic-lint/log.jsonl | tail -10
   ```
   Noisy != dead. If the rule has fired recently, challenge the removal and propose tightening.
2. Delete from `  <rule-id>:` through the last field line of that block.
3. Sanity-check:
   ```bash
   bash scripts/dogfood.sh
   # or
   python3 pipeline/pipeline.py --config .agentic-lint.yml --file <existing-file>
   ```

## Applying review recommendations

Apply one recommendation at a time. Test each before moving on. Never batch.

| Finding | Action |
|---|---|
| Noisy script rule | Tighten regex (word boundaries, exclude docblocks). Re-test. |
| Noisy semantic rule | Sharpen the description; add an example. Re-test with `--print-prompt`. |
| Dead rule, scope wrong | Broaden the scope; if still dead, propose removal. |
| Dead rule, obsolete | Remove. |
| Slow rule | Demote to `warning` or move to CI. |
| Semantic rule with stable mechanical fix | Draft an equivalent script rule, test, layer it alongside -- do not replace. |

## Troubleshooting

- **Rule id collision**: propose a semantic alternative (not a version suffix), or treat as a modification.
- **Pattern matches too much**: add `[^a-zA-Z_]` guards, anchor at line start, exclude comments via `grep -v`.
- **Pattern does not match**: try `grep -E` or `-P`; test the raw pattern against the fixture before wrapping in `&& exit 1 || exit 0`.
- **Scope mismatches**: test in Python -- `PurePath(path).match(glob)`.
- **Editing `.agentic-lint.yml` triggers the hook**: harmless unless a `*.yml`-scoped rule flags the config itself; fix the scope.
