# Bully rule configuration reference

## Context (semantic rules only)

By default the semantic evaluator sees only the diff under review. Some rules legitimately need upstream/downstream context (a callsite, a definition, an import block). For those, declare `context:` on the rule:

```yaml
rules:
  callsite-must-pass-typed-arg:
    description: >
      When a function whose typed signature changed is called, every callsite
      must update to match the new signature.
    severity: error
    engine: semantic
    context:
      lines: 30   # show 30 lines around each diff hunk
```

The pipeline reads `lines` lines above and below each diff hunk from the file on disk and includes them as an `<EXCERPT_FOR_RULE rule="...">` block inside the payload's `<UNTRUSTED_EVIDENCE>` region.

This is the *only* mechanism the evaluator has to see beyond the diff — the subagent has no `Read`, `Grep`, or `Glob` tools. If a rule needs a different shape of context (e.g., callers, definitions), file an issue: that's a deliberate boundary, not an oversight.

## Session-scope rules (`engine: session`)

Per-edit rules see one file at a time. Session-scope rules run at the `Stop` hook over the cumulative set of files edited in the session.

```yaml
rules:
  auth-changed-needs-tests:
    description: |
      Auth runtime changed but no auth tests were touched in this session.
    severity: error
    engine: session
    when:
      changed_any: ['src/auth/**']
    require:
      changed_any: ['tests/**/*auth*']
```

The pipeline maintains an append-only JSONL file at `.bully/session.jsonl` (one `{"file": ...}` record per line) with the changed-set; PostToolUse appends to it on every Edit/Write. At Stop time, each session rule whose `when.changed_any` matched is checked against `require.changed_any`; if the requirement is missing, the rule fires (severity-driven, exit 2 for `error`). On a clean Stop the session file is deleted. The append-only format is race-safe under parallel PostToolUse.

## Capabilities (script rules)

`bully trust` is the first safety gate (the user explicitly approved running this config). `capabilities:` is the second — a per-rule declaration of what each script needs:

```yaml
rules:
  lint-format:
    engine: script
    script: 'pnpm run lint'
    capabilities:
      network: false        # strip proxy vars; tripwire on accidental network use
      writes: cwd-only      # HOME and TMPDIR confined to cwd and cwd/.bully/tmp
```

This is declarative and best-effort, not kernel-level sandboxing. Tools that respect standard env vars (`HOME`, `TMPDIR`, `*_PROXY`, `NO_PROXY`) will be confined; tools that bypass them won't be. Treat capabilities as a clarity-and-tripwire mechanism — they document intent and surface accidents loudly. For real isolation, run the script under your platform's sandbox of choice (`firejail`, `bwrap`, `sandbox-exec`, container) outside bully.
