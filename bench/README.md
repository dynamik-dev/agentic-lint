# Skill eval harness

Evaluates the four local skills (`bully`, `bully-author`, `bully-init`, `bully-review`) on two axes:

1. **Triggering** — does Claude consult the skill given a query, and stay quiet on decoys
2. **Execution quality** — once triggered, is the output correct (assertions against fixtures, not vibes)

Schemas and workflow follow Anthropic's `skill-creator` conventions so the resulting `evals.json`, `grading.json`, and `benchmark.json` files are compatible with the upstream eval-viewer.

## Layout

```
bench/
├── run_skill_evals.py       # driver
├── grader_prompt.md         # grader subagent prompt
└── eval-runs/               # workspace (gitignored)

skills/<name>/evals/
├── triggers.json            # triggering eval set
├── evals.json               # execution-quality eval set (skill-creator schema)
└── files/                   # fixtures
```

## Models (pinned)

- Executor: `claude-sonnet-4-6`
- Grader: `claude-opus-4-7`

Override via `--executor-model` / `--grader-model`.

## Running

```bash
# Triggering eval
python bench/run_skill_evals.py triggers --skill skills/bully-init

# Execution-quality eval (all evals)
python bench/run_skill_evals.py execute --skill skills/bully-author

# Single eval by id
python bench/run_skill_evals.py execute --skill skills/bully-init --only 1

# Different model
python bench/run_skill_evals.py --executor-model claude-haiku-4-5-20251001 \
    triggers --skill skills/bully-review

# Error bars: run N epochs per eval -> every rate carries a 95% CI
python bench/run_skill_evals.py execute --skill skills/bully-author --epochs 5

# Control arm: also run without_skill -> paired per-eval pass_rate delta
python bench/run_skill_evals.py execute --skill skills/bully-author --epochs 5 --baseline
```

LLM runs (executor and graders) are stochastic, so a single run is a point
estimate with unknown variance. `--epochs N` repeats each eval N times and
reports `mean [95% CI]`; default is `1` (legacy) but use `>=5` for any number
you intend to compare or trust. `--baseline` adds a `without_skill` arm so the
benchmark can attribute an effect to the skill rather than the base model.

Each invocation creates `bench/eval-runs/<skill>/iteration-<N>/` and writes:

- `triggers.json` — triggering results (per-query pass/fail, trigger rate, false-positive rate)
- `eval-<id>-<slug>/<configuration>/run-<epoch>/` — one dir per epoch;
  `<configuration>` is `with_skill` (and `without_skill` under `--baseline`)
  - `outputs/` — files the executor wrote (the eval prompts reference paths under here)
  - `transcript.md` — readable conversation log
  - `stream.jsonl` — raw `claude -p --output-format stream-json` output
  - `eval_metadata.json` — prompt, expectations, model, configuration, run index, timestamp
  - `timing.json` — executor + grader durations
  - `grading.json` — grader's verdicts (skill-creator schema)
- `benchmark.json` / `benchmark.md` — aggregate stats across the iteration:
  per-eval and suite-level pass_rate as **mean [95% CI]** (two-stage — epochs
  reduced per eval, then clustered across evals so N epochs don't pose as N
  independent samples), an `errored_runs` count (grader failures are excluded
  from rates, never scored as 0%), and a paired `baseline_delta` under `--baseline`.
  Git SHA + executor/grader models are stamped into `metadata` for provenance.

## Fixture pollution gotcha

The bully PostToolUse hook appends a record to `.bully/log.jsonl` whenever it sees an Edit/Write to a file under a directory that has a `.bully/` sibling. To keep fixture log files clean, fixtures store telemetry under `bully-state/` (not `.bully/`). The eval prompts pass `--log <fixture>/bully-state/log.jsonl` explicitly so the skill reads from the fixture path rather than the magic `.bully/` location.

## Reviewing results

The output workspace is structurally compatible with skill-creator's `eval-viewer/generate_review.py`. If you have skill-creator installed locally:

```bash
python /path/to/skill-creator/eval-viewer/generate_review.py \
    bench/eval-runs/<skill>/iteration-1/ \
    --skill-name <skill> \
    --benchmark bench/eval-runs/<skill>/iteration-1/benchmark.json
```

## Caveats / known limits

- **`--baseline` disables *all* skills, not just the target.** The control arm passes `--disallowedTools Skill` to the executor, which blocks every skill (the plugin is globally installed, so there's no clean per-skill unload). The paired delta therefore measures "this skill vs. no skills" — a slight over-attribution if another skill would also have helped. Fine for the skill-vs-no-skill signal; tighten if a specific skill is a known confound.
- **Default `--epochs 1` gives no error bars.** A single run reports `mean (n=1)` with a zero-width interval. That's a point estimate, not a measurement — pass `--epochs >=5` before comparing iterations or trusting a delta.
- **Triggering detection is heuristic.** We look for the skill name in any tool call's serialized form. Claude Code's exact Skill-tool invocation shape may vary; if false negatives appear, refine `_detect_skill_invocation` in the driver.
- **Grader is itself an LLM.** The grader can be wrong. For deterministic checks (exit codes, YAML key sets), encode them into the expectation text so the grader will shell out and verify.
