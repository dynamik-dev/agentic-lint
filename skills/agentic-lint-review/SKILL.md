---
name: agentic-lint-review
description: Reviews agentic-lint rule health from the telemetry log. Use when the user says "review my lint rules", "check rule health", "which lint rules are noisy", "find dead lint rules", "agentic-lint review", or asks for an audit of `.agentic-lint.yml`. Surfaces noisy, dead, and slow rules and suggests which to adjust, remove, or promote.
metadata:
  author: dynamik-dev
  version: 1.0.0
  category: workflow-automation
  tags: [linting, rule-health, telemetry, self-improvement]
---

# Agentic Lint Review

Audit the health of `.agentic-lint.yml` rules using the telemetry log at `.agentic-lint/log.jsonl`. Highlights noisy rules (that fire too often), dead rules (that never fire), and slow rules (that cost time), then recommends concrete actions.

## Prerequisites

- `.agentic-lint.yml` exists at the project root.
- `.agentic-lint/log.jsonl` exists (the pipeline writes to it automatically when the `.agentic-lint/` directory is present).

If telemetry is not enabled, tell the user to create the `.agentic-lint/` directory so the pipeline can start logging. Do not run the analyzer on an empty log -- the report will say "dead" for every rule, which is not useful.

## Instructions

### Step 1: Locate the pipeline analyzer

The analyzer lives at `pipeline/analyzer.py` in this project. Run it in JSON mode so you can reason about the data:

```bash
python3 pipeline/analyzer.py \
  --log .agentic-lint/log.jsonl \
  --config .agentic-lint.yml \
  --json
```

If the paths differ in the user's repo, adjust. The script is stdlib-only and has no install step.

### Step 2: Classify the findings

The analyzer returns:
- `noisy`: rules with violation rate above the threshold (default 50%). Firing on most edits usually means the rule is too broad or the codebase is systematically at odds with it.
- `dead`: rules that never appeared in any log entry. Either the scope glob is wrong, the rule is obsolete, or the codebase has simply stopped triggering it.
- `slow`: rules whose mean latency is above the threshold (default 500 ms). Usually external shell-outs (PHPStan, ESLint) -- worth isolating.
- `by_rule`: per-rule counters -- `fires`, `passes`, `evaluate_requested`, `mean_latency_ms`, `files_touched`, `violation_rate`.

### Step 3: Recommend actions

For each class of finding, produce a concrete recommendation. Do not just list the raw numbers.

| Finding | Typical action |
|---------|----------------|
| Noisy script rule | Tighten the pattern, narrow the scope glob, or demote severity to `warning`. |
| Noisy semantic rule | Sharpen the description (the description IS the prompt) or split it into two rules. |
| Dead rule | Check the scope glob first -- it may be misconfigured. If the scope is right, consider removing the rule. |
| Slow rule | If it shells out to an external tool, either cache output, narrow scope, or drop it. |
| Semantic rule with stable high `evaluate_requested` and no downstream edits | Candidate for promotion to a `script` rule. |

### Step 4: Present a prioritized punch list

Format the final response as:

```
Rule health (N edits analyzed, window <first> → <last>)

Top recommendations:
1. [rule-id] — <what to do> — <why>
2. ...

Detailed findings:
- Noisy: ...
- Dead: ...
- Slow: ...
```

Keep the top recommendations short and actionable. Do not dump the full `by_rule` table unless the user asks for it.

### Step 5: Offer follow-up

End by offering to:
- Apply a specific fix (adjust a scope, remove a dead rule, lower a severity)
- Re-run the analyzer with different thresholds
- Export the JSON report for review

Do not modify `.agentic-lint.yml` without explicit user confirmation. Rule config is a shared, human-owned artifact.

## Examples

### Example 1: Fresh project, empty log

```
Rule health (0 edits analyzed)

Telemetry log is empty -- no edits have been recorded yet.

Make sure `.agentic-lint/` exists at the project root so the pipeline
can log. Come back after you've made a handful of edits.
```

### Example 2: Mature project

```
Rule health (284 edits analyzed, window 2026-03-01 → 2026-04-16)

Top recommendations:
1. [no-db-facade] — tighten regex or demote to warning. Fires on 62% of edits; many are false positives in docblocks.
2. [pint-formatting] — it's the slowest rule (mean 1.4s). Consider running Pint only in pre-commit, not on every edit.
3. [deprecated-carbon] — dead in the last 284 edits. The Carbon migration is finished; safe to remove.

Detailed findings:
- Noisy: no-db-facade (62%), no-event-helper (58%)
- Dead: deprecated-carbon, no-old-helpers
- Slow: pint-formatting (1412 ms), phpstan-check (892 ms)
```

## Troubleshooting

### Every rule shows as dead

Cause: Log file is empty or very recent. Analyzer needs data to classify anything.
Solution: Make sure `.agentic-lint/` directory exists so the pipeline can write. Do a handful of edits, then re-run.

### Noisy rule that the user does not want to relax

Cause: The rule is catching real violations, the codebase is legitimately at odds with it, and the user wants to fix the code, not the rule.
Solution: Offer to generate a task list of files that most frequently trigger the rule (join by file in the log) so the user can plan the cleanup.

### Slow rule that cannot be narrowed

Cause: External tool that inherently takes time (PHPStan full analysis).
Solution: Recommend moving the rule out of the per-edit pipeline into a pre-commit or CI step. Leave a warning-severity version in place if the user wants the signal in the edit loop.

## Performance Notes

- The analyzer is O(log_size) and stdlib-only. Fine on multi-MB logs.
- Thresholds (`--noisy-threshold`, `--slow-threshold-ms`) are tunable. Default noisy=0.5, slow=500ms.
- The analyzer only reads the log; it never modifies config. Changes to `.agentic-lint.yml` require a subsequent edit with user confirmation.
