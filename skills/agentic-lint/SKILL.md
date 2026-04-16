---
name: agentic-lint
description: Interprets agentic-lint PostToolUse hook output. Activates when hook feedback contains "AGENTIC LINT" after Edit or Write tool calls -- either as tool-blocking stderr (exit code 2) or as an injected additionalContext semantic-evaluation payload. Fixes all violations before proceeding. Not user-invocable; triggered automatically by the hook.
metadata:
  author: dynamik-dev
  version: 2.0.0
  category: workflow-automation
  tags: [linting, hooks, code-quality, post-tool-use]
---

# Agentic Lint

Interpret and act on agentic-lint PostToolUse hook output. Fix script violations immediately. Evaluate semantic rules against the provided diff and fix any violations found.

## Instructions

This skill is NOT invoked by the user. It activates when the agentic-lint hook surfaces feedback after an Edit or Write tool call. There are two formats, each requiring a different response.

### Handling Script Violations (hook exited 2)

When the tool result from your last Edit/Write includes feedback that begins with **"AGENTIC LINT -- blocked"**, the pipeline has already run deterministic script checks and found failures. The hook exited with code 2, which Claude Code treats as a blocking signal: the tool call did not take effect as written, or is flagged as non-compliant.

Format:

```
AGENTIC LINT -- blocked. Fix these before proceeding:

- [rule-id] line N: description of the violation
- [rule-id] line M: description of the violation

Passed checks: rule-a, rule-b
```

1. Parse the violation list. Each line follows `- [rule-id] line N: description`.
2. Fix every listed violation in the affected file before making any other tool calls. Use the Edit tool.
3. After fixing, the hook re-fires on the next Edit/Write and re-checks the file. Repeat until the hook reports no violations.
4. Do not skip, defer, or suppress any violation. Every violation must be resolved before moving to the next task.

### Handling Semantic Evaluation Requests

When the hook injects a `hookSpecificOutput.additionalContext` that begins with **"AGENTIC LINT SEMANTIC EVALUATION REQUIRED"**, the script checks passed but the pipeline is asking you to judge the diff against semantic rules.

The payload is a JSON object with these fields:

- `file` -- the file that was modified.
- `diff` -- a unified diff (for Edit) or a line-numbered snapshot (for Write). Line numbers are anchored to the file on disk so you can cite specific lines in violations.
- `passed_checks` -- array of rule ids the deterministic script checks already verified as passing. Do not re-investigate concerns already covered.
- `evaluate` -- array of `{id, description, severity}` objects. For semantic rules, the `description` IS the evaluation prompt.

**Do not evaluate the rules yourself.** Dispatch the `agentic-lint-evaluator` subagent and let it return the verdict. Offloading to the subagent runs the evaluation on a smaller model with an isolated context, which keeps your main session lean.

Use the `Agent` tool with:

- `subagent_type`: `agentic-lint-evaluator`
- `description`: a 3-5 word summary like "Evaluate lint rules"
- `prompt`: the literal `additionalContext` string the hook gave you (the entire payload, headers and all). The agent knows how to parse it.

The agent returns text in this exact shape:

```
VIOLATIONS:
- [rule-id] line N: <what's wrong>
  fix: <suggestion>

NO_VIOLATIONS:
- rule-id-a
- rule-id-b
```

Parse the `VIOLATIONS:` section. For each entry, look up the rule's severity from the original `evaluate` payload (the agent does not echo severity), then act:

- **error severity**: Fix the violation immediately using the Edit tool, applying the agent's `fix:` suggestion as a starting point. Do this before any other tool call.
- **warning severity**: Note it in a single sentence, then continue the current task.
- **empty `VIOLATIONS:` section**: Proceed normally.

If the agent's response does not match the expected shape (missing headers, JSON, or prose-only), treat it as a transient failure: re-dispatch once with the same payload. If the second response is also malformed, fall back to evaluating the rules yourself against the diff using the same output format, then proceed.

### Using passed_checks correctly

`passed_checks` lists rule ids the deterministic script checks already verified. Two implications:

1. Do not re-investigate those concerns. If `no-compact` passed, the file does not contain `compact()` -- do not search for it.
2. Use them to catch cross-rule interactions. If a script rule like `no-db-facade` passed but a semantic rule like `dependency-direction` is in the evaluation list, check whether the diff introduces an indirect `DB::` usage that the script rule would not catch.

### Severity Handling

- **error**: Blocks progress. Must be fixed before any other tool call.
- **warning**: Noted but non-blocking. One sentence in the response, then continue.

### What Not to Do

- Do not re-evaluate rules listed in `passed_checks`.
- Do not ask the user whether to fix error-severity violations. Fix them.
- Do not batch violation fixes with unrelated edits. Fix violations in dedicated Edit calls.
- Do not ignore the hook output. Blocked feedback means the last edit is not compliant.
- Do not cite line numbers that do not appear in the diff. If you cannot locate the violation to a specific line, widen scope and say so rather than fabricating.

## Examples

### Example 1: Script Violations Detected

Tool result feedback (stderr from exit 2):
```
AGENTIC LINT -- blocked. Fix these before proceeding:

- [no-compact] line 42: return compact('result');
- [no-db-facade] line 58: $users = DB::table('users')->get();
```

Actions:
1. Open the file that was just edited (the agent knows the path from the most recent Edit/Write call).
2. Replace the `compact()` call on line 42 with an explicit array.
3. Replace the `DB::` call on line 58 with the equivalent `Model::query()` call.
4. The hook re-fires on the next Edit and verifies the fixes.

### Example 2: Semantic Evaluation Required

additionalContext:
```
AGENTIC LINT SEMANTIC EVALUATION REQUIRED:

{
  "file": "src/Evaluators/CachedEvaluator.php",
  "diff": "--- src/Evaluators/CachedEvaluator.php.before\n+++ src/Evaluators/CachedEvaluator.php.after\n@@ -28,6 +28,11 @@\n     private Evaluator $inner;\n \n+    public function evaluate($subject, $permission, $scope = null)\n+    {\n+        $result = $this->inner->evaluate($subject, $permission, $scope);\n+        return $result;\n+    }\n }",
  "passed_checks": ["no-compact", "no-db-facade", "no-event-helper"],
  "evaluate": [
    {"id": "no-inline-single-use", "description": "Inline single-use variables; do not assign to a variable only to return it immediately", "severity": "error"},
    {"id": "full-type-hints", "description": "All methods must have full PHP 8.4+ type hints and return types", "severity": "error"}
  ]
}
```

Actions:
1. Evaluate `no-inline-single-use` against the diff: `$result` is assigned on line 32 and immediately returned on line 33. This is a violation.
2. Evaluate `full-type-hints` against the diff: the method signature on line 30 has no parameter types or return type. This is a violation.
3. Fix both in a single Edit: inline the return and add type declarations.
4. The hook re-fires on the next Edit and re-evaluates.

### Example 3: No Violations Found

Hook output:
```
--- AGENTIC LINT SEMANTIC EVALUATION REQUIRED ---
{
  "file": "src/Models/Role.php",
  "diff": "@@ -10,6 +10,7 @@\n+    protected $casts = ['is_system' => 'boolean'];",
  "passed_checks": ["no-compact", "no-db-facade"],
  "evaluate": [
    {"id": "full-type-hints", "description": "All methods must have full PHP 8.4+ type hints and return types", "severity": "error"}
  ]
}
```

Actions:
1. Evaluate `full-type-hints`: the diff adds a property declaration, not a method. No method signatures are affected. No violation.
2. State explicitly: no violations found. Proceed with current task.

## Troubleshooting

### Error: Hook keeps re-firing after fix

Cause: The fix introduced a new violation or did not fully resolve the original one.
Solution: Read the new violation list carefully. Each re-fire produces a fresh report. Fix what the new report says, not what the previous one said.

### Error: Semantic rule is ambiguous for the given diff

Cause: The diff is too small to determine whether a rule applies.
Solution: If the rule clearly does not apply to the changed lines, state "no violation" and proceed. Only flag violations you can point to a specific line for.

## Performance Notes

- Script violations are deterministic: the hook tells you exactly what is wrong and where. Fix them mechanically.
- Semantic evaluations require judgment. Read the diff carefully and apply each rule individually.
- Keep violation fixes minimal and targeted. Do not refactor surrounding code unless the rule demands it.
