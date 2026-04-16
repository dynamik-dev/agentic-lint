# Telemetry and self-improvement

Every pipeline run can append a record to a telemetry log. The `agentic-lint-review` skill reads that log and classifies rule health so the config can evolve with the codebase.

## Enabling

Telemetry is opt-in. Create the log directory next to `.agentic-lint.yml`:

```bash
mkdir .agentic-lint
```

From that point on, every pipeline run appends one line to `.agentic-lint/log.jsonl`. Removing the directory turns logging off.

The pipeline never auto-creates the directory. This is deliberate — a repo with no `.agentic-lint/` is an explicit "do not write here" signal.

## What gets logged

One JSONL record per pipeline run. Each record captures the overall result plus a per-rule breakdown.

```json
{
  "ts": "2026-04-16T18:00:00Z",
  "file": "src/Stores/EloquentRoleStore.php",
  "status": "blocked",
  "latency_ms": 20,
  "rules": [
    {
      "id": "no-compact",
      "engine": "script",
      "verdict": "violation",
      "severity": "error",
      "line": 42,
      "latency_ms": 9
    },
    {
      "id": "no-db-facade",
      "engine": "script",
      "verdict": "pass",
      "severity": "error",
      "latency_ms": 6
    },
    {
      "id": "inline-single-use-vars",
      "engine": "semantic",
      "verdict": "evaluate_requested",
      "severity": "error"
    }
  ]
}
```

### Fields

Record-level:

| Field | Description |
|-------|-------------|
| `ts` | ISO-8601 UTC timestamp (second precision). |
| `file` | File the pipeline ran against. |
| `status` | `pass`, `evaluate`, or `blocked`. |
| `latency_ms` | Total pipeline wall-clock time. |
| `rules` | Per-rule breakdown. |

Per-rule:

| Field | Description |
|-------|-------------|
| `id` | Rule id from `.agentic-lint.yml`. |
| `engine` | `script` or `semantic`. |
| `verdict` | `pass`, `violation`, or `evaluate_requested`. |
| `severity` | `error` or `warning`. |
| `line` | Line number of the first violation (script rules only). |
| `latency_ms` | Per-rule latency (script rules only). |

### Verdict meanings

- **`pass`** — script rule ran and returned exit 0.
- **`violation`** — script rule ran and returned non-zero.
- **`evaluate_requested`** — semantic rule was included in the payload sent to the agent. The pipeline does not see the agent's eventual verdict; the telemetry captures only that judgment was requested.

The asymmetry for semantic rules is a known limitation. Future work: an agent-side callback that records the judgment outcome so semantic rules can be classified as noisy/dead with the same precision as script rules.

## Running the analyzer

```bash
python3 pipeline/analyzer.py \
  --log .agentic-lint/log.jsonl \
  --config .agentic-lint.yml
```

Output:

```
Rule health report
==================
Total edits analyzed: 284
Window: 2026-03-01T12:00:00Z → 2026-04-16T18:00:00Z

Noisy rules (2): fire on most edits -- consider relaxing or splitting.
  - no-db-facade  fires=176 passes=108 requested=0 rate=62% avg_ms=6
  - no-event-helper  fires=164 passes=120 requested=0 rate=58% avg_ms=5

Dead rules (1): never invoked in this window -- consider removing or widening scope.
  - deprecated-carbon  fires=0 passes=0 requested=0 rate=0% avg_ms=0

Slow rules (2): mean latency is high -- consider simplifying or caching.
  - pint-formatting  fires=68 passes=216 requested=0 rate=24% avg_ms=1412
  - phpstan-check  fires=42 passes=242 requested=0 rate=15% avg_ms=892

All rules:
  - ... (per-rule table)
```

### Options

```
--json                   Emit machine-readable JSON instead of formatted text.
--noisy-threshold 0.5    Violation rate above which a rule is flagged noisy (default 0.5).
--slow-threshold-ms 500  Mean latency ms above which a rule is flagged slow (default 500).
```

### Classification rules

- **Noisy** — `violation_rate = fires / (fires + passes)` exceeds the noisy threshold. Defaults to 50%. A rule that fires on most edits is either too broad or flagging systemic problems — either way it warrants attention.
- **Dead** — the rule is configured but never appeared in any log entry's `rules` list. Either the scope glob is misconfigured, or the rule is obsolete.
- **Slow** — mean per-run latency exceeds the slow threshold. Defaults to 500 ms. Usually external shell-outs. Candidates for demotion from the per-edit pipeline to pre-commit or CI.

## Using the review skill

The `agentic-lint-review` skill wraps the analyzer and produces a prioritized punch list instead of a raw table:

```
> /agentic-lint-review
```

The skill runs the analyzer, interprets the findings in context, and recommends concrete actions. It never modifies `.agentic-lint.yml` without your confirmation.

## Workflow: introducing a new rule

1. Add the rule to `.agentic-lint.yml` with `severity: warning`.
2. Let it run across a few hundred edits.
3. `/agentic-lint-review`.
4. If the rule is noisy, sharpen its pattern or description before promoting.
5. If the rule is quiet with clean fixes, promote to `severity: error`.
6. If the rule never fires, check the scope glob first; if scope is right, consider removing.

## Workflow: removing a rule

1. `/agentic-lint-review` identifies a dead rule.
2. Verify the scope isn't misconfigured. (A common cause: rule scoped `src/*.ts` when the project uses `packages/*/src/*.ts`.)
3. If the rule is genuinely unused, remove it from `.agentic-lint.yml`.
4. The telemetry log retains history; removed rules simply stop appearing in future records.

## Privacy and log hygiene

- The log contains file paths and rule outcomes — no file contents, no diffs, no code.
- Log lines are append-only. The pipeline never rewrites or truncates.
- Rotate manually when the log grows beyond your tolerance. `jq` over multi-MB JSONL is cheap; the analyzer has no pagination built in yet.
- Gitignore `.agentic-lint/` if you don't want telemetry in version control. It's per-developer data, not project config.

## What telemetry does not do (yet)

The substrate is in place; the autonomous improvements are not:

- **Semantic verdict capture** — the pipeline logs that the LLM was asked; it doesn't yet log what the LLM decided. That requires an agent-side callback.
- **Semantic-to-script promotion** — once the pipeline knows a semantic rule fires with identical mechanical fixes N times in a row, it could draft the equivalent script rule. Not wired.
- **Rule discovery from unflagged fixes** — when the agent edits the same pattern repeatedly without any rule firing, that could suggest a new rule. Not wired.

These are the logical next features if the substrate proves useful. Deferred deliberately — they need real usage data to be meaningful rather than speculative.
