# Security Policy

## Reporting a Vulnerability

bully runs deterministic shell commands and dispatches a Claude subagent. If you find a way to escape the sandboxed scope or inject commands through a crafted `.bully.yml` or through file contents that bypass the script-rule scoping, please report it privately.

**Preferred:** [GitHub private vulnerability reporting](https://github.com/dynamik-dev/bully/security/advisories/new)

**Alternative:** Email chris@arter.dev with subject line `[bully] security`.

Expected response: acknowledgement within 72 hours.

## Scope

In scope:
- Command injection through config parsing or diff handling.
- Path traversal in rule `scope` globs.
- Telemetry file tampering causing the analyzer to crash or misclassify.
- Hook exit-code bypass.

Out of scope:
- Rules themselves being poorly written (that's a config bug, not a security issue).
- The `bully` skill making a judgment error on a semantic rule.
- Third-party linters invoked by a rule's `script:` field.

## Supported Versions

Only `main` is supported. Tagged releases may receive security fixes at maintainer discretion.
