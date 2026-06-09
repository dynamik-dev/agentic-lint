"""Skill eval harness for bully's local skills.

Runs two kinds of evals against skills in ./skills/:

1. triggers -- did Claude consult the skill given a user query?
   Reads <skill>/evals/triggers.json (a list of {query, should_trigger}).
   Invokes `claude -p` for each query and inspects the stream for skill
   invocation markers.

2. execute -- once triggered, is the output correct?
   Reads <skill>/evals/evals.json (skill-creator schema).
   For each eval, runs `claude -p` against the prompt in a workspace seeded
   with the eval's fixture files, captures the transcript, then dispatches
   a grader run (separate `claude -p` invocation) that judges the transcript
   + outputs against the expectations[] array.

Workspace layout (skill-creator-compatible):

  bench/eval-runs/<skill>/iteration-<N>/
    eval-<id>-<slug>/
      with_skill/
        run-1/
          outputs/                  # everything the executor wrote
          transcript.md             # rendered from stream-json
          eval_metadata.json        # prompt, fixture paths, model, ts
          timing.json               # executor + grader durations
          grading.json              # grader output (skill-creator schema)
    benchmark.json                  # aggregated stats
    benchmark.md                    # human-readable summary
    triggers.json                   # triggering eval results

Stdlib-only (subprocess + json + pathlib + argparse + shutil + time).
Requires `claude` on PATH.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import statistics
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Pinned models. Override via flags.
DEFAULT_EXECUTOR_MODEL = "claude-sonnet-4-6"
DEFAULT_GRADER_MODEL = "claude-opus-4-7"

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS_ROOT = REPO_ROOT / "bench" / "eval-runs"
GRADER_PROMPT_PATH = REPO_ROOT / "bench" / "grader_prompt.md"
QUALITY_PROMPT_PATH = REPO_ROOT / "bench" / "quality_prompt.md"


# ----- helpers -----------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _slug(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s.strip().lower()).strip("-")
    return s[:60] or "eval"


# 95% two-sided normal critical value. Evals are stochastic, so every reported
# rate gets a CLT-based error bar per Anthropic's "Adding Error Bars to Evals"
# (arXiv 2411.00640) rather than a bare point estimate.
_Z95 = 1.959963984540054


def mean_ci(xs: list[Any]) -> dict[str, Any]:
    """Mean + 95% normal-approximation confidence interval for a sample.

    Returns ``{n, mean, stddev, sem, ci_low, ci_high}``. ``None`` entries are
    dropped before computing. Distinguishes three regimes:

    - empty  -> ``mean`` is ``None`` (an *absent* measurement, never ``0.0`` --
      this is what keeps a grader/infra failure from being scored as 0%).
    - n == 1 -> zero-width CI (no variance information).
    - n >= 2 -> ``sem = stdev / sqrt(n)``; CI is ``mean +/- 1.96 * sem``.

    Values are returned at full precision; rounding is a rendering concern.
    """
    vals = [float(x) for x in xs if x is not None]
    n = len(vals)
    if n == 0:
        return {"n": 0, "mean": None, "stddev": 0.0, "sem": 0.0, "ci_low": None, "ci_high": None}
    mean = statistics.fmean(vals)
    if n < 2:
        return {"n": 1, "mean": mean, "stddev": 0.0, "sem": 0.0, "ci_low": mean, "ci_high": mean}
    sd = statistics.stdev(vals)
    sem = sd / math.sqrt(n)
    return {
        "n": n,
        "mean": mean,
        "stddev": sd,
        "sem": sem,
        "ci_low": mean - _Z95 * sem,
        "ci_high": mean + _Z95 * sem,
    }


def execution_plan(*, epochs: int, baseline: bool) -> list[tuple[str, int]]:
    """The ordered ``(configuration, run_index)`` pairs to execute per eval.

    Without ``baseline`` this is just ``epochs`` runs of ``with_skill``. With
    ``baseline`` each eval also runs ``without_skill`` (the skill disabled) so
    the harness can attribute the skill's effect via a paired delta -- the
    control arm Anthropic's skill-creator methodology treats as mandatory.
    """
    configs = ["with_skill", "without_skill"] if baseline else ["with_skill"]
    return [(cfg, i) for cfg in configs for i in range(1, epochs + 1)]


def _next_iteration_dir(skill_dir: Path) -> Path:
    skill_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(
        (p for p in skill_dir.iterdir() if p.is_dir() and p.name.startswith("iteration-")),
        key=lambda p: int(p.name.split("-", 1)[1]) if p.name.split("-", 1)[1].isdigit() else 0,
    )
    n = (int(existing[-1].name.split("-", 1)[1]) + 1) if existing else 1
    out = skill_dir / f"iteration-{n}"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _claude_cmd(
    prompt: str,
    *,
    model: str,
    cwd: Path | None,
    extra_args: list[str] | None = None,
    timeout_s: float | None = None,
) -> tuple[str, str, int]:
    """Run `claude -p <prompt>` and return (stdout, stderr, returncode).

    Uses --output-format stream-json so we can parse tool calls. Caller
    decides on permission mode via extra_args. timeout_s kills the
    subprocess after the deadline (returncode 124 to mimic `timeout`).
    """
    cmd = [
        "claude",
        "-p",
        prompt,
        "--model",
        model,
        "--output-format",
        "stream-json",
        "--verbose",
    ]
    if extra_args:
        cmd.extend(extra_args)
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_s,
        )
        return proc.stdout, proc.stderr, proc.returncode
    except subprocess.TimeoutExpired as exc:
        return (
            (exc.stdout or "") if isinstance(exc.stdout, str) else "",
            (exc.stderr or "") if isinstance(exc.stderr, str) else "",
            124,
        )


def _parse_stream_events(raw: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def _render_transcript(events: list[dict[str, Any]]) -> str:
    """Best-effort markdown rendering of a stream-json conversation."""
    lines: list[str] = []
    for ev in events:
        t = ev.get("type")
        if t == "user":
            lines.append("## User\n\n" + json.dumps(ev.get("message", ""), indent=2) + "\n")
        elif t == "assistant":
            msg = ev.get("message", {})
            content = msg.get("content", [])
            for block in content if isinstance(content, list) else []:
                btype = block.get("type") if isinstance(block, dict) else None
                if btype == "text":
                    lines.append("## Assistant (text)\n\n" + block.get("text", "") + "\n")
                elif btype == "tool_use":
                    name = block.get("name", "?")
                    inp = block.get("input", {})
                    lines.append(
                        f"## Tool call: {name}\n\n```json\n" + json.dumps(inp, indent=2) + "\n```\n"
                    )
                elif btype == "thinking":
                    lines.append("## (thinking)\n\n" + block.get("thinking", "") + "\n")
        elif t == "tool_result":
            content = ev.get("content", "")
            if not isinstance(content, str):
                content = json.dumps(content, indent=2)
            lines.append("## Tool result\n\n```\n" + content + "\n```\n")
        elif t == "result":
            lines.append("## Result\n\n" + json.dumps(ev, indent=2) + "\n")
    return "\n".join(lines) if lines else "(empty stream)"


def _count_tool_calls(events: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for ev in events:
        if ev.get("type") != "assistant":
            continue
        for block in ev.get("message", {}).get("content", []) or []:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                name = block.get("name", "?")
                counts[name] = counts.get(name, 0) + 1
    return counts


def _run_conversation(
    turns: list[dict[str, Any]],
    *,
    model: str,
    cwd: Path,
    extra_args: list[str],
    timeout_s: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str, list[dict[str, Any]]]:
    """Drive a multi-turn session with claude. Each turn is `{"user": str,
    "assistant_contains": [optional list of substrings]}`.

    Returns (all_events, per_turn_metadata, session_id, gate_results) where:
    - all_events: concatenated stream events across all turns
    - per_turn_metadata: list of {turn_index, elapsed_s, returncode, n_tool_calls}
    - session_id: the UUID we assigned
    - gate_results: per-turn `assistant_contains` checks
      [{turn_index, missing: [phrases not found], passed: bool}]
    """
    session_id = str(uuid.uuid4())
    all_events: list[dict[str, Any]] = []
    per_turn: list[dict[str, Any]] = []
    gate_results: list[dict[str, Any]] = []
    for i, turn in enumerate(turns):
        user_msg = turn["user"]
        session_args = ["--session-id", session_id] if i == 0 else ["--resume", session_id]
        t0 = time.perf_counter()
        stdout, stderr, rc = _claude_cmd(
            user_msg,
            model=model,
            cwd=cwd,
            extra_args=extra_args + session_args,
            timeout_s=timeout_s,
        )
        elapsed = time.perf_counter() - t0
        events = _parse_stream_events(stdout)
        all_events.extend(events)
        # Collect this turn's assistant text for gate check.
        turn_text = ""
        n_tool_calls = 0
        for ev in events:
            if ev.get("type") == "assistant":
                for b in ev.get("message", {}).get("content", []) or []:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "text":
                        turn_text += b.get("text", "") + "\n"
                    elif b.get("type") == "tool_use":
                        n_tool_calls += 1
        per_turn.append(
            {
                "turn_index": i,
                "user_msg_preview": user_msg[:120],
                "elapsed_seconds": round(elapsed, 2),
                "returncode": rc,
                "n_tool_calls": n_tool_calls,
            }
        )
        # Gate check.
        required = turn.get("assistant_contains") or []
        if required:
            missing = [p for p in required if p.lower() not in turn_text.lower()]
            gate_results.append(
                {
                    "turn_index": i,
                    "required": required,
                    "missing": missing,
                    "passed": not missing,
                }
            )
        if rc != 0 and rc != 124:
            # Hard error; stop the conversation.
            break
    return all_events, per_turn, session_id, gate_results


def _detect_skill_invocation(events: list[dict[str, Any]], skill_name: str) -> bool:
    """Returns True if any tool call references the skill (by name match)."""
    for ev in events:
        if ev.get("type") != "assistant":
            continue
        for block in ev.get("message", {}).get("content", []) or []:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name = block.get("name", "")
            inp = block.get("input", {})
            blob = json.dumps({"name": name, "input": inp})
            if skill_name in blob or f"plugin:{skill_name}" in blob:
                return True
    return False


# ----- triggers eval ----------------------------------------------------------


def cmd_triggers(args: argparse.Namespace) -> int:
    skill_path = Path(args.skill).resolve()
    skill_name = skill_path.name
    triggers_path = skill_path / "evals" / "triggers.json"
    if not triggers_path.exists():
        print(f"no triggers.json at {triggers_path}", file=sys.stderr)
        return 2
    cases: list[dict[str, Any]] = json.loads(triggers_path.read_text())
    iter_dir = _next_iteration_dir(RUNS_ROOT / skill_name)
    out_path = iter_dir / "triggers.json"

    results: list[dict[str, Any]] = []
    for i, case in enumerate(cases, 1):
        query = case["query"]
        expected = bool(case["should_trigger"])
        print(f"[triggers] {i}/{len(cases)}  expected={expected}  query={query!r}", flush=True)
        t0 = time.perf_counter()
        stdout, stderr, rc = _claude_cmd(
            query,
            model=args.executor_model,
            cwd=REPO_ROOT,
            # Allow only Skill so Claude either invokes the skill (signal) or
            # replies in text. AskUserQuestion is blocked to prevent hangs in -p.
            extra_args=[
                "--allowedTools",
                "Skill",
                "--disallowedTools",
                "AskUserQuestion",
            ],
            timeout_s=args.timeout_s,
        )
        elapsed = time.perf_counter() - t0
        events = _parse_stream_events(stdout)
        triggered = _detect_skill_invocation(events, skill_name)
        passed = triggered == expected
        # For debugging: capture which tool calls happened and a final-text snippet.
        tool_calls_seen: list[dict[str, Any]] = []
        final_text = ""
        for ev in events:
            if ev.get("type") == "assistant":
                for block in ev.get("message", {}).get("content", []) or []:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_use":
                        tool_calls_seen.append(
                            {
                                "name": block.get("name", ""),
                                "input_keys": list((block.get("input") or {}).keys()),
                                "input_preview": json.dumps(block.get("input") or {})[:200],
                            }
                        )
                    elif block.get("type") == "text":
                        final_text = block.get("text", "")[-400:]
        results.append(
            {
                "query": query,
                "should_trigger": expected,
                "triggered": triggered,
                "passed": passed,
                "elapsed_seconds": round(elapsed, 2),
                "claude_returncode": rc,
                "tool_calls_seen": tool_calls_seen,
                "final_assistant_text_tail": final_text,
                "stderr_tail": (stderr or "")[-400:],
            }
        )

    summary = {
        "skill_name": skill_name,
        "executor_model": args.executor_model,
        "timestamp": _now_iso(),
        "total": len(results),
        "passed": sum(1 for r in results if r["passed"]),
        "failed": sum(1 for r in results if not r["passed"]),
        "trigger_rate_when_expected": (
            sum(1 for r in results if r["should_trigger"] and r["triggered"])
            / max(1, sum(1 for r in results if r["should_trigger"]))
        ),
        "false_positive_rate": (
            sum(1 for r in results if not r["should_trigger"] and r["triggered"])
            / max(1, sum(1 for r in results if not r["should_trigger"]))
        ),
        "results": results,
    }
    out_path.write_text(json.dumps(summary, indent=2))
    print(f"\nwrote {out_path}")
    print(
        f"passed {summary['passed']}/{summary['total']}  "
        f"trigger_rate={summary['trigger_rate_when_expected']:.2f}  "
        f"fpr={summary['false_positive_rate']:.2f}"
    )
    return 0 if summary["failed"] == 0 else 1


# ----- execution eval ---------------------------------------------------------


def _seed_workspace(
    eval_dir: Path,
    skill_path: Path,
    files: list[str],
    *,
    configuration: str = "with_skill",
    run_index: int = 1,
) -> Path:
    """Copy fixture files into one run's working directory.

    The fixture root mirrors the skill's layout: relative paths under
    skill_path/<...> get copied to ws/<same path>. The skill's prompts
    reference paths like 'evals/files/<scenario>/...' so the workspace
    cwd must be the skill dir. ``configuration`` (with_skill / without_skill)
    and ``run_index`` (the epoch) keep each run's outputs isolated.
    """
    ws = eval_dir / configuration / f"run-{run_index}"
    outputs = ws / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    # Mirror the skill dir structure under outputs/ so the prompt's
    # relative paths resolve. The executor's cwd will be outputs/.
    for rel in files:
        src = skill_path / rel
        dst = outputs / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not src.exists():
            print(f"  WARN fixture missing: {src}", file=sys.stderr)
            continue
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)
    return ws


def _execute_one_run(
    ev: dict[str, Any],
    *,
    skill_path: Path,
    skill_name: str,
    eval_dir: Path,
    configuration: str,
    run_index: int,
    args: argparse.Namespace,
) -> dict[str, Any]:
    """Run one (eval, configuration, epoch): execute, grade, optionally score
    quality, and return the per-run summary. Writes all artifacts under the
    run's own ``<configuration>/run-<index>/`` directory so epochs and arms
    never clobber each other.

    For the ``without_skill`` control arm the Skill tool is disallowed so the
    base agent solves the task without the skill's guidance; the (skill-aware)
    quality grader is skipped there since its protocol-adherence dimension is
    only meaningful when the skill is loaded.
    """
    eid = ev["id"]
    is_multi_turn = bool(ev.get("turns"))
    ws = _seed_workspace(
        eval_dir,
        skill_path,
        ev.get("files", []),
        configuration=configuration,
        run_index=run_index,
    )
    outputs = ws / "outputs"
    transcript_path = ws / "transcript.md"
    grading_path = ws / "grading.json"

    (ws / "eval_metadata.json").write_text(
        json.dumps(
            {
                "eval_id": eid,
                "eval_name": ev.get("name"),
                "skill_name": skill_name,
                "configuration": configuration,
                "run_index": run_index,
                "prompt": ev.get("prompt"),
                "turns": ev.get("turns"),
                "mode": "multi-turn" if is_multi_turn else "single-turn",
                "files": ev.get("files", []),
                "expected_output": ev.get("expected_output"),
                "expectations": ev["expectations"],
                "executor_model": args.executor_model,
                "grader_model": args.grader_model,
                "timestamp": _now_iso(),
            },
            indent=2,
        )
    )

    print(f"  [{configuration} run-{run_index}] eval-{eid}", flush=True)
    # Control arm gets the Skill tool disabled; both arms block AskUserQuestion.
    disallowed = "AskUserQuestion,Skill" if configuration == "without_skill" else "AskUserQuestion"
    executor_extra = [
        "--permission-mode",
        args.executor_permission_mode,
        "--disallowedTools",
        disallowed,
    ]
    t0 = time.perf_counter()
    if is_multi_turn:
        events, per_turn, session_id, gate_results = _run_conversation(
            ev["turns"],
            model=args.executor_model,
            cwd=outputs,
            extra_args=executor_extra,
            timeout_s=args.executor_timeout_s,
        )
        (ws / "session_id.txt").write_text(session_id)
        (ws / "turns.json").write_text(
            json.dumps({"per_turn": per_turn, "gate_results": gate_results}, indent=2)
        )
        stdout = "\n".join(json.dumps(e) for e in events)
        stderr = ""
    else:
        stdout, stderr, _rc_exec = _claude_cmd(
            ev["prompt"],
            model=args.executor_model,
            cwd=outputs,
            extra_args=executor_extra,
            timeout_s=args.executor_timeout_s,
        )
        events = _parse_stream_events(stdout)
        gate_results = []
    exec_elapsed = time.perf_counter() - t0
    transcript_path.write_text(_render_transcript(events))
    (ws / "stream.jsonl").write_text(stdout)
    if stderr:
        (ws / "executor.stderr.log").write_text(stderr)

    # Grader: a separate `claude -p` that reads the transcript + outputs and
    # writes grading.json.
    grader_prompt = (
        GRADER_PROMPT_PATH.read_text()
        + "\n\n## Run inputs\n\n"
        + json.dumps(
            {
                "skill_name": skill_name,
                "eval_prompt": ev.get("prompt") or [t.get("user") for t in ev.get("turns", [])],
                "expectations": ev["expectations"],
                "transcript_path": str(transcript_path),
                "outputs_dir": str(outputs),
                "grading_path": str(grading_path),
            },
            indent=2,
        )
    )
    t1 = time.perf_counter()
    g_stdout, g_stderr, g_rc = _claude_cmd(
        grader_prompt,
        model=args.grader_model,
        cwd=REPO_ROOT,
        extra_args=[
            "--permission-mode",
            "bypassPermissions",
            "--disallowedTools",
            "AskUserQuestion",
        ],
        timeout_s=args.grader_timeout_s,
    )
    grader_elapsed = time.perf_counter() - t1
    if g_stderr:
        (ws / "grader.stderr.log").write_text(g_stderr)
    (ws / "grader.stream.jsonl").write_text(g_stdout)

    if grading_path.exists():
        grading = json.loads(grading_path.read_text())
        pr = grading.get("summary", {}).get("pass_rate", 0.0)
        print(f"    graded pass_rate={pr:.2f}  exec={exec_elapsed:.0f}s", flush=True)
    else:
        # No grading.json => grader infra failure. This run is ERRORED, not 0%:
        # pass_rate stays None so aggregate() excludes it instead of scoring it 0.
        print(
            f"    WARN no grading.json -- grader failed (rc={g_rc}); run marked errored", flush=True
        )
        grading = None

    # Quality grader (skill-aware; with_skill arm only).
    quality_path = ws / "quality.json"
    quality_elapsed = 0.0
    quality = None
    if configuration == "with_skill" and not args.skip_quality and grading is not None:
        quality_skill_path = REPO_ROOT / "skills" / skill_name
        quality_prompt = (
            QUALITY_PROMPT_PATH.read_text()
            + "\n\n## Run inputs\n\n"
            + json.dumps(
                {
                    "skill_name": skill_name,
                    "skill_path": str(quality_skill_path),
                    "eval_prompt": ev.get("prompt") or [t.get("user") for t in ev.get("turns", [])],
                    "transcript_path": str(transcript_path),
                    "outputs_dir": str(outputs),
                    "grading_path": str(grading_path),
                    "quality_path": str(quality_path),
                },
                indent=2,
            )
        )
        t2 = time.perf_counter()
        q_stdout, q_stderr, q_rc = _claude_cmd(
            quality_prompt,
            model=args.grader_model,
            cwd=REPO_ROOT,
            extra_args=[
                "--permission-mode",
                "bypassPermissions",
                "--disallowedTools",
                "AskUserQuestion",
            ],
            timeout_s=args.grader_timeout_s,
        )
        quality_elapsed = time.perf_counter() - t2
        (ws / "quality.stream.jsonl").write_text(q_stdout)
        if q_stderr:
            (ws / "quality.stderr.log").write_text(q_stderr)
        if quality_path.exists():
            quality = json.loads(quality_path.read_text())
            print(f"    quality overall={quality.get('overall_score')}", flush=True)
        else:
            print(f"    WARN no quality.json (rc={q_rc})", flush=True)

    (ws / "timing.json").write_text(
        json.dumps(
            {
                "executor_duration_seconds": round(exec_elapsed, 2),
                "grader_duration_seconds": round(grader_elapsed, 2),
                "quality_grader_duration_seconds": round(quality_elapsed, 2),
                "total_duration_seconds": round(exec_elapsed + grader_elapsed + quality_elapsed, 2),
            },
            indent=2,
        )
    )

    return {
        "eval_id": eid,
        "eval_name": ev.get("name"),
        "configuration": configuration,
        "run_number": run_index,
        "mode": "multi-turn" if is_multi_turn else "single-turn",
        "result": {
            # None (not 0.0) when the grader failed: aggregate() treats this run
            # as errored and excludes it from the rate.
            "pass_rate": (grading or {}).get("summary", {}).get("pass_rate"),
            "passed": (grading or {}).get("summary", {}).get("passed"),
            "failed": (grading or {}).get("summary", {}).get("failed"),
            "total": (grading or {}).get("summary", {}).get("total"),
            "errored": grading is None,
            "time_seconds": round(exec_elapsed, 2),
            "tool_calls": sum(_count_tool_calls(events).values()),
            "quality_overall": (quality or {}).get("overall_score"),
            "quality_scores": {
                k: v.get("value") for k, v in (quality or {}).get("scores", {}).items()
            },
        },
        "expectations": (grading or {}).get("expectations", []),
        "tool_calls_breakdown": _count_tool_calls(events),
        "gate_results": gate_results,
        "quality_summary": (quality or {}).get("summary"),
    }


def cmd_execute(args: argparse.Namespace) -> int:
    skill_path = Path(args.skill).resolve()
    skill_name = skill_path.name
    evals_path = skill_path / "evals" / "evals.json"
    if not evals_path.exists():
        print(f"no evals.json at {evals_path}", file=sys.stderr)
        return 2
    suite = json.loads(evals_path.read_text())
    iter_dir = _next_iteration_dir(RUNS_ROOT / skill_name)

    only = set(args.only.split(",")) if args.only else None
    plan = execution_plan(epochs=args.epochs, baseline=args.baseline)
    print(
        f"plan: {len(plan)} run(s) per eval "
        f"({args.epochs} epoch(s) x {len(set(c for c, _ in plan))} arm(s))",
        flush=True,
    )
    summaries: list[dict[str, Any]] = []
    for ev in suite["evals"]:
        eid = ev["id"]
        if only and str(eid) not in only:
            continue
        slug = _slug(ev.get("name") or ev["prompt"])
        eval_dir = iter_dir / f"eval-{eid}-{slug}"
        eval_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n[execute] eval-{eid} {slug}", flush=True)
        for configuration, run_index in plan:
            summaries.append(
                _execute_one_run(
                    ev,
                    skill_path=skill_path,
                    skill_name=skill_name,
                    eval_dir=eval_dir,
                    configuration=configuration,
                    run_index=run_index,
                    args=args,
                )
            )

    benchmark = aggregate(
        skill_name,
        args.executor_model,
        args.grader_model,
        summaries,
        epochs=args.epochs,
        git_sha=_git_sha(),
        git_dirty=_git_dirty(),
    )
    (iter_dir / "benchmark.json").write_text(json.dumps(benchmark, indent=2))
    (iter_dir / "benchmark.md").write_text(_render_benchmark_md(benchmark))
    print(f"\nwrote {iter_dir / 'benchmark.json'}")
    print(_render_benchmark_md(benchmark))
    return 0


def aggregate(
    skill_name: str,
    executor_model: str,
    grader_model: str,
    runs: list[dict[str, Any]],
    *,
    epochs: int,
    git_sha: str | None = None,
    git_dirty: bool | None = None,
) -> dict[str, Any]:
    """Two-stage aggregation of per-(eval, configuration, epoch) summaries.

    Stage 1 collapses an eval's epochs into one number (a model-stochasticity
    CI). Stage 2 aggregates across evals -- clustering on the eval so N epochs
    of one eval don't masquerade as N independent observations (the
    standard-error inflation Anthropic's "Adding Error Bars to Evals" warns
    about). Errored runs (``pass_rate is None``) are excluded from rates and
    counted separately, so a grader/infra failure never reads as a 0% score.
    When both ``with_skill`` and ``without_skill`` arms exist, a paired
    per-eval delta quantifies the skill's effect.
    """
    by_cfg_eval: dict[str, dict[Any, list[dict[str, Any]]]] = {}
    for r in runs:
        by_cfg_eval.setdefault(r["configuration"], {}).setdefault(r["eval_id"], []).append(r)

    per_eval: list[dict[str, Any]] = []
    eval_mean: dict[tuple[str, Any], float | None] = {}
    for cfg in sorted(by_cfg_eval):
        for eid in sorted(by_cfg_eval[cfg]):
            rows = by_cfg_eval[cfg][eid]
            rates = [row["result"].get("pass_rate") for row in rows]
            scored = [x for x in rates if x is not None]
            pr = mean_ci(scored)
            qci = mean_ci([row["result"].get("quality_overall") for row in rows])
            tci = mean_ci([row["result"].get("time_seconds") for row in rows])
            per_eval.append(
                {
                    "eval_id": eid,
                    "eval_name": rows[0].get("eval_name"),
                    "configuration": cfg,
                    "mode": rows[0].get("mode"),
                    "epochs": len(rows),
                    "errored_epochs": len(rates) - len(scored),
                    "pass_rate": pr,
                    "quality_overall": qci if qci["n"] else None,
                    "time_seconds": tci,
                }
            )
            eval_mean[(cfg, eid)] = pr["mean"]

    run_summary: dict[str, Any] = {}
    for cfg in sorted(by_cfg_eval):
        rows = [pe for pe in per_eval if pe["configuration"] == cfg]
        scored_means = [
            pe["pass_rate"]["mean"] for pe in rows if pe["pass_rate"]["mean"] is not None
        ]
        q_means = [pe["quality_overall"]["mean"] for pe in rows if pe["quality_overall"]]
        run_summary[cfg] = {
            "pass_rate": mean_ci(scored_means),
            "evals_scored": len(scored_means),
            "errored_runs": sum(pe["errored_epochs"] for pe in rows),
            "quality_overall": mean_ci(q_means) if q_means else None,
            "time_seconds": mean_ci([pe["time_seconds"]["mean"] for pe in rows]),
        }

    baseline_delta = None
    if {"with_skill", "without_skill"} <= set(by_cfg_eval):
        common = sorted(set(by_cfg_eval["with_skill"]) & set(by_cfg_eval["without_skill"]))
        deltas = [
            eval_mean[("with_skill", eid)] - eval_mean[("without_skill", eid)]
            for eid in common
            if eval_mean[("with_skill", eid)] is not None
            and eval_mean[("without_skill", eid)] is not None
        ]
        baseline_delta = {"pass_rate": mean_ci(deltas), "n_evals_paired": len(deltas)}

    return {
        "metadata": {
            "skill_name": skill_name,
            "executor_model": executor_model,
            "grader_model": grader_model,
            "timestamp": _now_iso(),
            "git_sha": git_sha,
            "git_dirty": git_dirty,
            "evals_run": sorted({r["eval_id"] for r in runs}),
            "epochs": epochs,
            "configurations": sorted(by_cfg_eval),
        },
        "runs": runs,
        "per_eval": per_eval,
        "run_summary": run_summary,
        "baseline_delta": baseline_delta,
    }


def _git_sha() -> str | None:
    """Best-effort short SHA so a benchmark can be tied to a skill version."""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
            cwd=str(REPO_ROOT),
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() or None if r.returncode == 0 else None


def _git_dirty() -> bool:
    try:
        r = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=2,
            cwd=str(REPO_ROOT),
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return bool(r.stdout.strip())


def _fmt_ci(stat: dict[str, Any] | None, *, nd: int = 2, sign: bool = False) -> str:
    """Render a mean_ci dict as 'mean [lo, hi] (n=k)', or '—' if unmeasured."""
    if not stat or stat.get("mean") is None:
        return "—"
    m = stat["mean"]
    head = f"{m:+.{nd}f}" if sign else f"{m:.{nd}f}"
    if stat["n"] < 2:
        return f"{head} (n={stat['n']})"
    return f"{head} [{stat['ci_low']:.{nd}f}, {stat['ci_high']:.{nd}f}] (n={stat['n']})"


def _render_benchmark_md(b: dict[str, Any]) -> str:
    m = b["metadata"]
    git = f"{m.get('git_sha') or '?'}{' (dirty)' if m.get('git_dirty') else ''}"
    lines = [
        f"# Benchmark: {m['skill_name']}",
        "",
        f"- timestamp: {m['timestamp']}",
        f"- executor: {m['executor_model']}   grader: {m.get('grader_model', '?')}",
        f"- git: {git}",
        f"- epochs: {m.get('epochs')}   configurations: {', '.join(m.get('configurations', []))}",
        f"- evals: {m['evals_run']}",
        "",
        "## Per-eval (mean [95% CI] across epochs)",
        "",
        "| eval_id | name | config | mode | pass_rate | quality | time_s | epochs | errored |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for pe in b.get("per_eval", []):
        lines.append(
            f"| {pe['eval_id']} | {pe.get('eval_name', '')} | {pe['configuration']} | "
            f"{pe.get('mode', '')} | {_fmt_ci(pe['pass_rate'])} | "
            f"{_fmt_ci(pe.get('quality_overall'))} | {_fmt_ci(pe['time_seconds'], nd=1)} | "
            f"{pe['epochs']} | {pe['errored_epochs']} |"
        )
    lines += [
        "",
        "## Suite (clustered on eval)",
        "",
        "| configuration | pass_rate | quality | evals_scored | errored_runs |",
        "|---|---|---|---|---|",
    ]
    for cfg, s in b["run_summary"].items():
        lines.append(
            f"| {cfg} | {_fmt_ci(s['pass_rate'])} | {_fmt_ci(s.get('quality_overall'))} | "
            f"{s['evals_scored']} | {s['errored_runs']} |"
        )
    if b.get("baseline_delta"):
        d = b["baseline_delta"]
        lines += [
            "",
            "## Skill effect (with_skill − without_skill, paired on eval)",
            "",
            f"- pass_rate uplift: **{_fmt_ci(d['pass_rate'], sign=True)}** "
            f"over {d['n_evals_paired']} paired eval(s)",
        ]
    return "\n".join(lines) + "\n"


# ----- CLI --------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    p.add_argument("--executor-model", default=DEFAULT_EXECUTOR_MODEL)
    p.add_argument("--grader-model", default=DEFAULT_GRADER_MODEL)
    sub = p.add_subparsers(dest="cmd", required=True)

    pt = sub.add_parser("triggers", help="Run triggering eval against triggers.json")
    pt.add_argument("--skill", required=True, help="path to skill dir, e.g. skills/bully-init")
    pt.add_argument(
        "--timeout-s",
        type=float,
        default=300.0,
        help="per-query timeout (default 300s). claude -p only flushes stream-json "
        "on natural completion -- on SIGKILL we lose all events, so the timeout "
        "needs to be high enough that most queries complete on their own.",
    )
    pt.set_defaults(func=cmd_triggers)

    pe = sub.add_parser("execute", help="Run execution-quality eval and grade it")
    pe.add_argument("--skill", required=True, help="path to skill dir, e.g. skills/bully-init")
    pe.add_argument("--only", help="comma-separated eval ids to run (default: all)")
    pe.add_argument(
        "--epochs",
        type=int,
        default=1,
        help="runs per (eval, arm) so every rate carries a 95%% CI. Default 1 "
        "(legacy point estimate); use >=5 for trustworthy error bars.",
    )
    pe.add_argument(
        "--baseline",
        action="store_true",
        help="also run a without_skill control arm (Skill tool disabled) and "
        "report a paired per-eval pass_rate delta -- the skill's attributable effect.",
    )
    pe.add_argument(
        "--executor-timeout-s",
        type=float,
        default=600.0,
        help="executor per-eval timeout (default 600s)",
    )
    pe.add_argument(
        "--grader-timeout-s",
        type=float,
        default=300.0,
        help="grader per-eval timeout (default 300s)",
    )
    pe.add_argument(
        "--executor-permission-mode",
        default="bypassPermissions",
        choices=["acceptEdits", "auto", "bypassPermissions", "default", "dontAsk", "plan"],
        help="permission mode for the executor (default bypassPermissions for fixture-only writes)",
    )
    pe.add_argument(
        "--skip-quality",
        action="store_true",
        help="skip the orthogonal quality grader (saves ~1 grader call per eval)",
    )
    pe.set_defaults(func=cmd_execute)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
