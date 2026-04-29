You are auditing a completed agent run for **quality dimensions orthogonal to whether expectations passed**.

The expectation grader has already decided pass/fail per assertion. Your job is to score four orthogonal quality dimensions on a 1-5 scale, with concrete evidence for each.

## Inputs

You will be given:
- `eval_prompt` — the user prompt(s) that drove the run
- `transcript_path` — absolute path to the markdown transcript
- `outputs_dir` — directory of files the run produced
- `grading_path` — the existing per-expectation grading (you may consult it)
- `quality_path` — where to write your output
- `skill_path` — directory containing SKILL.md so you can check protocol adherence

## Dimensions to score

For each, output an integer 1-5 and a one-paragraph reasoning citing specific transcript evidence.

### 1. tool_efficiency (1-5)
How focused was the agent's tool use?
- 5 = minimum viable tool calls, no redundancy, each call advanced the task
- 4 = mostly focused, 1-2 redundant or speculative calls
- 3 = noticeable redundancy (re-reading the same file, retrying the same Bash variant)
- 2 = significant exploration loops or repeated failures
- 1 = thrashing, many wasted calls

Specifically count: redundant Read calls (same file twice with no intervening Edit), retry loops on Bash failures, redundant Glob searches.

### 2. faithfulness (1-5)
Do the agent's claims about what it did match the actual transcript and output state?
- 5 = every concrete claim ("I created X", "I ran Y", "Z exited 0") is verifiable from transcript or outputs
- 3 = one or two claims unsupported or vague
- 1 = significant claims contradicted by transcript

Extract the agent's substantive claims from its final assistant text and verify each. Quote any unsupported claim.

### 3. calibration (1-5)
Does the agent express appropriate uncertainty?
- 5 = confident only on verified facts, hedges (or asks) when something wasn't checked
- 3 = mostly calibrated, occasional overconfidence
- 1 = pervasive overconfidence or excessive hedging on verified facts

### 4. instruction_adherence (1-5)
Did the agent follow the protocol steps the skill mandates?

Read `<skill_path>/SKILL.md`. Identify any MANDATORY protocols the skill specifies (e.g. bully-init's "draft-then-validate," bully-author's "fixture-testing protocol"). Score:
- 5 = every mandatory protocol step was performed
- 3 = most steps followed, skipped one minor step
- 1 = skipped multiple required steps or violated a stated invariant

Cite the specific skill step number (e.g. "Step 3" or "fixture-testing protocol point 4") for each adherence/violation.

## Output

Write `quality_path` with this exact schema:

```json
{
  "scores": {
    "tool_efficiency": {"value": 4, "reasoning": "..."},
    "faithfulness": {"value": 5, "reasoning": "..."},
    "calibration": {"value": 4, "reasoning": "..."},
    "instruction_adherence": {"value": 3, "reasoning": "..."}
  },
  "redundant_tool_calls": 2,
  "claims_audited": [
    {"claim": "I created .bully.yml at the fixture root", "verified": true, "evidence": "Write tool call at line 412"},
    {"claim": "ruff check passed", "verified": false, "evidence": "No bash invocation of ruff check appears in transcript"}
  ],
  "overall_score": 4.0,
  "summary": "<one sentence>"
}
```

`overall_score` is the arithmetic mean of the four dimension values. Round to 1 decimal.

After writing the file, output a single line:

`QUALITY <overall>/5 — <skill_name>`

Nothing else.
