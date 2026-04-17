---
name: bully-review
description: Reviews agentic-lint rule health from the telemetry log. Use when the user says "review my lint rules", "check rule health", "which lint rules are noisy", "find dead lint rules", "agentic-lint review", or asks for an audit of `.agentic-lint.yml`. Surfaces noisy, dead, and slow rules and suggests which to adjust, remove, or promote.
metadata:
  author: dynamik-dev
  version: 1.0.0
  category: workflow-automation
  tags: [linting, rule-health, telemetry, self-improvement]
---

# Agentic Lint Review

Audit `.agentic-lint.yml` using the telemetry log at `.agentic-lint/log.jsonl`. See `docs/telemetry.md` for log schema and scope.

## Prerequisites

- `.agentic-lint.yml` and `.agentic-lint/log.jsonl` both exist.
- If the log is empty, stop and tell the user to make a handful of edits first -- classifying an empty log flags every rule as dead.

## Known gap: semantic rules are not logged

Per `docs/telemetry.md` and `docs/plan.md` section 3.4, only script-rule verdicts are written to `log.jsonl` today. Semantic-rule outcomes are not yet captured, so:

- "Dead" classification applies to **script rules only**. A semantic rule that looks dead in the report may actually be firing.
- Do not recommend removing a semantic rule based on zero hits. Flag it as "not yet observable" instead.

## Step 1: Run the analyzer

```bash
python3 pipeline/analyzer.py --log .agentic-lint/log.jsonl
```

Add `--config .agentic-lint.yml --json` when you need structured output to reason over. Thresholds `--noisy-threshold` (default 0.5) and `--slow-threshold-ms` (default 500) are tunable.

## Step 2: Classify

The analyzer returns three buckets plus a `by_rule` table with `fires`, `passes`, `evaluate_requested`, `mean_latency_ms`, `files_touched`, and `violation_rate`.

- **noisy**: violation rate above threshold. Rule is too broad or the codebase is systemically at odds with it.
- **dead**: zero hits in the log window (script rules only -- see gap above).
- **slow**: mean latency above threshold. Usually external shell-outs (PHPStan, ESLint, Pint).

## Step 3: Recommend

| Finding | Action |
|---------|--------|
| Noisy script rule | Tighten pattern, narrow scope glob, or demote severity to `warning`. |
| Noisy semantic rule | Sharpen the description (description IS the prompt) or split into two rules. |
| Dead script rule | Check scope glob first; if correct, remove the rule. |
| Slow rule | Cache, narrow scope, or move to pre-commit/CI. |
| Semantic rule with high `evaluate_requested` and no downstream edits | Candidate for promotion to a `script` rule. |

## Step 4: Present findings

Lead with a short prioritized punch list:

```
[rule-id] — <action> — <why>
```

Follow with brief noisy / dead / slow sections. Do not dump `by_rule` unless asked.

## Step 5: Hand off

Do not edit `.agentic-lint.yml` directly. When the user confirms a recommendation, hand off to the `bully-author` skill to apply it -- that skill tests rules against fixtures before writing.
