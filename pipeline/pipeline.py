"""
Agentic Lint Pipeline

Two-phase evaluation: deterministic script checks, then LLM semantic payload.
Python 3.10+ stdlib only -- no external dependencies.
"""

from __future__ import annotations

import argparse
import difflib
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path, PurePath

# ---------------------------------------------------------------------------
# Config schema + parser
# ---------------------------------------------------------------------------

VALID_ENGINES = {"script", "semantic"}
VALID_SEVERITIES = {"error", "warning"}
VALID_RULE_FIELDS = {"description", "engine", "scope", "severity", "script", "fix_hint"}
VALID_TOP_LEVEL = {"rules", "schema_version", "extends"}

# Files we never want to lint -- lockfiles, minified bundles, generated code.
SKIP_PATTERNS: tuple[str, ...] = (
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "Cargo.lock",
    "*.min.js",
    "*.min.css",
    "*.min.*",
    "dist/**",
    "build/**",
    "__pycache__/**",
    "*.generated.*",
    "*.pb.go",
    "*.g.dart",
    "*.freezed.dart",
)


class ConfigError(Exception):
    """Raised on malformed config input. Carries a 1-indexed line number."""

    def __init__(self, message: str, line: int | None = None):
        self.line = line
        self.message = message
        prefix = f"line {line}: " if line is not None else ""
        super().__init__(f"{prefix}{message}")


@dataclass(frozen=True)
class Rule:
    id: str
    description: str
    engine: str
    scope: tuple[str, ...]
    severity: str
    script: str | None = None
    fix_hint: str | None = None


@dataclass
class Violation:
    rule: str
    engine: str
    severity: str
    line: int | None
    description: str
    suggestion: str | None = None


# ---------------------------------------------------------------------------
# Scalar/list helpers (unchanged semantics, hardened parser uses them)
# ---------------------------------------------------------------------------


def _strip_inline_comment(raw: str) -> str:
    """Remove a trailing ` # comment` while respecting quoted regions."""
    in_single = False
    in_double = False
    for i, ch in enumerate(raw):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double and (i == 0 or raw[i - 1].isspace()):
            return raw[:i].rstrip()
    return raw


def _parse_scalar(raw: str) -> str:
    """Normalize a scalar value: strip inline comment, then matched outer quotes only."""
    raw = _strip_inline_comment(raw).strip()
    if len(raw) >= 2 and ((raw[0] == '"' and raw[-1] == '"') or (raw[0] == "'" and raw[-1] == "'")):
        return raw[1:-1]
    return raw


def _parse_inline_list(raw: str) -> list[str] | None:
    """Parse `[a, b, "c"]` into a list of scalars, or return None if not a list."""
    raw = _strip_inline_comment(raw).strip()
    if not (raw.startswith("[") and raw.endswith("]")):
        return None
    inner = raw[1:-1].strip()
    if not inner:
        return []
    items: list[str] = []
    buf: list[str] = []
    in_single = False
    in_double = False
    for ch in inner:
        if ch == "'" and not in_double:
            in_single = not in_single
            buf.append(ch)
        elif ch == '"' and not in_single:
            in_double = not in_double
            buf.append(ch)
        elif ch == "," and not in_single and not in_double:
            items.append(_parse_scalar("".join(buf)))
            buf = []
        else:
            buf.append(ch)
    if buf:
        items.append(_parse_scalar("".join(buf)))
    return items


# ---------------------------------------------------------------------------
# parse_config with line-numbered errors + extends resolution
# ---------------------------------------------------------------------------


@dataclass
class _ParsedConfig:
    """Internal structure returned by _parse_single_file."""

    rules: list[Rule] = field(default_factory=list)
    extends: list[str] = field(default_factory=list)
    schema_version: int | None = None


def _parse_single_file(path: str) -> _ParsedConfig:
    """Parse one .bully.yml into _ParsedConfig. Raises ConfigError on malformed input."""
    rules: list[Rule] = []
    extends: list[str] = []
    schema_version: int | None = None

    current_id: str | None = None
    current_id_line: int | None = None
    fields: dict[str, object] = {}
    field_lines: dict[str, int] = {}
    folding_key: str | None = None
    folded_lines: list[str] = []

    seen_ids: set[str] = set()
    in_rules_block = False
    in_extends_block = False

    def finalize_rule() -> None:
        nonlocal current_id, fields, field_lines
        if current_id is not None:
            if current_id in seen_ids:
                raise ConfigError(f"duplicate rule id '{current_id}'", current_id_line)
            seen_ids.add(current_id)
            rules.append(_build_rule(current_id, fields, field_lines, current_id_line))
        current_id = None
        fields = {}
        field_lines = {}

    try:
        with open(path) as f:
            raw_lines = f.readlines()
    except OSError as e:
        raise ConfigError(f"cannot read config file {path}: {e}") from e

    for lineno, raw_line in enumerate(raw_lines, start=1):
        raw = raw_line.rstrip("\n")
        # Reject hard tabs in leading whitespace -- they break our 2/4-space indent model.
        leading = raw[: len(raw) - len(raw.lstrip(" \t"))]
        if "\t" in leading:
            raise ConfigError("tab character in indentation; use spaces", lineno)

        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(raw) - len(raw.lstrip(" "))

        # Flush folded scalar when dedent happens.
        if folding_key is not None:
            if indent >= 6:
                folded_lines.append(stripped)
                continue
            else:
                fields[folding_key] = " ".join(folded_lines)
                folding_key = None
                folded_lines = []

        # Extends-block continuation: `- item` at indent 2.
        if in_extends_block and indent >= 2 and stripped.startswith("-"):
            item = _parse_scalar(stripped[1:].strip())
            if item:
                extends.append(item)
            continue
        elif in_extends_block:
            in_extends_block = False

        # Top-level key (indent 0).
        if indent == 0:
            if current_id is not None:
                finalize_rule()
            in_rules_block = False

            if stripped == "rules:":
                in_rules_block = True
                continue
            if ":" not in stripped:
                raise ConfigError(f"unexpected top-level line: {stripped!r}", lineno)
            key, _, value = stripped.partition(":")
            key = key.strip()
            value_raw = value.strip()
            if key not in VALID_TOP_LEVEL:
                raise ConfigError(
                    f"unknown top-level key '{key}' "
                    f"(allowed: {', '.join(sorted(VALID_TOP_LEVEL))})",
                    lineno,
                )
            if key == "schema_version":
                v = _parse_scalar(value_raw)
                try:
                    schema_version = int(v)
                except ValueError as e:
                    raise ConfigError(
                        f"schema_version must be an integer, got {v!r}", lineno
                    ) from e
            elif key == "extends":
                as_list = _parse_inline_list(value_raw)
                if as_list is not None:
                    extends.extend(a for a in as_list if a)
                elif value_raw == "":
                    in_extends_block = True
                else:
                    raise ConfigError("extends must be a list like [pack-a, './local.yml']", lineno)
            # `rules:` handled above; anything else would have raised already.
            continue

        # Rule id (indent 2).
        if indent == 2 and stripped.endswith(":"):
            if not in_rules_block:
                raise ConfigError("rule definition outside a `rules:` block", lineno)
            if current_id is not None:
                finalize_rule()
            rid = stripped[:-1].strip()
            if not rid:
                raise ConfigError("empty rule id", lineno)
            if any(ch.isspace() for ch in rid):
                raise ConfigError(f"rule id {rid!r} contains whitespace", lineno)
            current_id = rid
            current_id_line = lineno
            fields = {}
            field_lines = {}
            continue

        # Rule field (indent 4).
        if indent == 4 and ":" in stripped:
            if current_id is None:
                raise ConfigError(
                    "field defined outside any rule (indented without a rule id above)",
                    lineno,
                )
            key, _, value = stripped.partition(":")
            key = key.strip()
            value_raw = value.strip()
            if key not in VALID_RULE_FIELDS:
                raise ConfigError(
                    f"unknown rule field '{key}' in rule '{current_id}' "
                    f"(allowed: {', '.join(sorted(VALID_RULE_FIELDS))})",
                    lineno,
                )
            if value_raw == ">":
                folding_key = key
                folded_lines = []
                field_lines[key] = lineno
                continue
            as_list = _parse_inline_list(value_raw)
            if as_list is not None:
                fields[key] = as_list
            else:
                fields[key] = _parse_scalar(value_raw)
            field_lines[key] = lineno
            continue

        # Anything else is unrecognized indentation.
        raise ConfigError(
            f"could not parse line (unexpected indent {indent}): {stripped!r}", lineno
        )

    # Flush tail state.
    if folding_key is not None:
        fields[folding_key] = " ".join(folded_lines)
    if current_id is not None:
        finalize_rule()

    return _ParsedConfig(rules=rules, extends=extends, schema_version=schema_version)


def _build_rule(
    rule_id: str,
    fields: dict[str, object],
    field_lines: dict[str, int] | None = None,
    rule_line: int | None = None,
) -> Rule:
    """Build a Rule, validating engine/severity/script. Raises ConfigError on misuse."""
    field_lines = field_lines or {}

    engine = str(fields.get("engine", "script"))
    if engine not in VALID_ENGINES:
        raise ConfigError(
            f"rule '{rule_id}': invalid engine {engine!r} (must be 'script' or 'semantic')",
            field_lines.get("engine", rule_line),
        )

    severity = str(fields.get("severity", "error"))
    if severity not in VALID_SEVERITIES:
        raise ConfigError(
            f"rule '{rule_id}': invalid severity {severity!r} (must be 'error' or 'warning')",
            field_lines.get("severity", rule_line),
        )

    script_value = fields.get("script")
    if engine == "script" and script_value is None:
        raise ConfigError(
            f"rule '{rule_id}': engine is 'script' but no 'script' field provided",
            rule_line,
        )
    if engine == "semantic" and script_value is not None:
        raise ConfigError(
            f"rule '{rule_id}': engine is 'semantic' but a 'script' field is set "
            f"(contradiction -- remove one)",
            field_lines.get("script", rule_line),
        )

    fix_hint_value = fields.get("fix_hint")

    return Rule(
        id=rule_id,
        description=str(fields.get("description", "")),
        engine=engine,
        scope=_normalize_scope(fields.get("scope", "*")),
        severity=severity,
        script=str(script_value) if script_value is not None else None,
        fix_hint=str(fix_hint_value) if fix_hint_value is not None else None,
    )


def _normalize_scope(value: object) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(str(v) for v in value)
    if value is None:
        return ("*",)
    return (str(value),)


def _resolve_extends_target(spec: str, config_path: str) -> Path:
    """Resolve an extends reference to an absolute Path."""
    config_dir = Path(config_path).resolve().parent
    p = Path(spec)
    if p.is_absolute():
        return p.resolve()
    return (config_dir / p).resolve()


def parse_config(path: str) -> list[Rule]:
    """Parse .bully.yml into Rule objects, resolving `extends:` transitively.

    Local rules override same-id rules pulled in via extends (warn on stderr).
    Raises ConfigError on cycles, unknown keys/fields, invalid enums, etc.
    """
    resolved = _load_with_extends(path, visited=[])
    return resolved


def _load_with_extends(path: str, visited: list[str]) -> list[Rule]:
    """Recursively load a config + its extends. Returns merged rule list."""
    abs_path = str(Path(path).resolve())
    if abs_path in visited:
        cycle = " -> ".join(visited + [abs_path])
        raise ConfigError(f"extends cycle detected: {cycle}")
    visited = visited + [abs_path]

    parsed = _parse_single_file(path)

    # Pull in extends in order.
    merged: dict[str, Rule] = {}
    order: list[str] = []
    for spec in parsed.extends:
        target = _resolve_extends_target(spec, path)
        if not target.exists():
            raise ConfigError(f"extends target not found: {spec} (resolved to {target})")
        inherited = _load_with_extends(str(target), visited)
        for r in inherited:
            if r.id not in merged:
                order.append(r.id)
            merged[r.id] = r

    # Local rules override.
    for r in parsed.rules:
        if r.id in merged:
            sys.stderr.write(f"bully: rule {r.id} overridden by local config\n")
        else:
            order.append(r.id)
        merged[r.id] = r

    return [merged[rid] for rid in order]


# ---------------------------------------------------------------------------
# File filtering
# ---------------------------------------------------------------------------


def _path_matches_skip(file_path: str) -> bool:
    """Return True if the path matches any SKIP_PATTERNS entry."""
    p = PurePath(file_path)
    name = p.name
    posix = p.as_posix()
    for pat in SKIP_PATTERNS:
        # Match basename (covers `*.min.js`, `package-lock.json`, etc.)
        if fnmatch.fnmatch(name, pat):
            return True
        # Match full posix path (covers `dist/**`, etc.)
        if fnmatch.fnmatch(posix, pat):
            return True
        # PurePath.match handles `**` correctly for path-suffix matches.
        try:
            if p.match(pat):
                return True
        except ValueError:
            pass
        # `dist/**` style -- check any segment equals prefix.
        if pat.endswith("/**"):
            prefix = pat[:-3]
            if prefix in p.parts:
                return True
    return False


def filter_rules(rules: list[Rule], file_path: str) -> list[Rule]:
    """Return rules whose scope glob(s) match the given file path."""
    path = PurePath(file_path)
    return [r for r in rules if any(path.match(g) for g in r.scope)]


# ---------------------------------------------------------------------------
# Diff context builder
# ---------------------------------------------------------------------------

# Write-mode content cap markers.
_WRITE_HEAD_LINES = 100
_WRITE_TAIL_LINES = 50
_WRITE_MAX_LINES = 200

# Synthetic-line warning marker.
SYNTHETIC_MARKER = "# WARNING: synthetic line numbers -- could not anchor diff to file on disk"


def build_diff_context(
    tool_name: str,
    file_path: str,
    old_string: str,
    new_string: str,
    context_lines: int = 5,
) -> str:
    """Produce a diff with real file line numbers for the semantic payload.

    Falls back to a synthetic diff (with a warning marker) when anchoring fails.
    For Write mode, caps very large files to head+tail slices.
    """
    try:
        with open(file_path) as f:
            current = f.read()
    except OSError:
        if tool_name == "Write":
            return _cap_write_content(new_string)
        return (
            f"{SYNTHETIC_MARKER}\n"
            f"--- {file_path} (file not readable)\n+++ edit\n-{old_string}\n+{new_string}\n"
        )

    if tool_name == "Write":
        return _cap_write_content(current)

    # Edit path: synthesize before state
    if new_string and new_string in current:
        before = current.replace(new_string, old_string, 1)
    elif old_string and old_string in current:
        before = current
        current = current.replace(old_string, new_string, 1)
    else:
        # Can't anchor to file; return a best-effort synthetic diff.
        before_lines = (old_string or "").splitlines(keepends=True) or ["\n"]
        after_lines = (new_string or "").splitlines(keepends=True) or ["\n"]
        synth = "".join(
            difflib.unified_diff(
                before_lines,
                after_lines,
                fromfile=f"{file_path}.before",
                tofile=f"{file_path}.after",
                n=context_lines,
            )
        )
        return SYNTHETIC_MARKER + "\n" + synth

    before_lines = before.splitlines(keepends=True)
    after_lines = current.splitlines(keepends=True)
    return "".join(
        difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile=f"{file_path}.before",
            tofile=f"{file_path}.after",
            n=context_lines,
        )
    )


def _cap_write_content(content: str) -> str:
    """Return line-numbered content; if too long, slice head + tail with a marker."""
    lines = content.splitlines()
    total = len(lines)
    if total <= _WRITE_MAX_LINES:
        return _line_number(content)

    width = max(3, len(str(total)))
    head = lines[:_WRITE_HEAD_LINES]
    tail = lines[total - _WRITE_TAIL_LINES :]
    out: list[str] = []
    for i, line in enumerate(head, start=1):
        out.append(f"{i:>{width}}: {line}")
    truncated = total - _WRITE_HEAD_LINES - _WRITE_TAIL_LINES
    out.append(f"... {truncated} lines truncated ...")
    tail_start = total - _WRITE_TAIL_LINES + 1
    for i, line in enumerate(tail, start=tail_start):
        out.append(f"{i:>{width}}: {line}")
    return "\n".join(out)


def _was_write_truncated(content: str) -> bool:
    return len(content.splitlines()) > _WRITE_MAX_LINES


def _line_number(content: str) -> str:
    """Prefix each line with `NNNN:` for line-anchored evaluation."""
    lines = content.splitlines()
    width = max(3, len(str(len(lines))))
    return "\n".join(f"{i:>{width}}: {line}" for i, line in enumerate(lines, start=1))


# ---------------------------------------------------------------------------
# Script output parsing
# ---------------------------------------------------------------------------

_FILE_LINE_COL = re.compile(r"^(?P<file>[^:\s]+):(?P<line>\d+):(?P<col>\d+):\s*(?P<msg>.+)$")
_FILE_LINE = re.compile(r"^(?P<file>[^:\s]+):(?P<line>\d+):\s*(?P<msg>.+)$")
_LINE_CONTENT = re.compile(r"^(?P<line>\d+)[:\s-]+(?P<msg>.*)$")


def _violation_from_dict(rule_id: str, severity: str, d: dict) -> Violation | None:
    line = d.get("line") or d.get("lineNumber") or d.get("line_no")
    message = d.get("message") or d.get("msg") or d.get("description") or ""
    if line is None and not message:
        return None
    try:
        line_i = int(line) if line is not None else None
    except (TypeError, ValueError):
        line_i = None
    return Violation(
        rule=rule_id,
        engine="script",
        severity=severity,
        line=line_i,
        description=str(message).strip(),
    )


def parse_script_output(rule_id: str, severity: str, output: str) -> list[Violation]:
    """Parse common tool output formats into Violation records."""
    stripped = output.strip()
    if not stripped:
        return []

    if stripped.startswith("{") or stripped.startswith("["):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            v = _violation_from_dict(rule_id, severity, parsed)
            if v is not None:
                return [v]
        elif isinstance(parsed, list):
            vs = [
                _violation_from_dict(rule_id, severity, item)
                for item in parsed
                if isinstance(item, dict)
            ]
            vs = [v for v in vs if v is not None]
            if vs:
                return vs

    violations: list[Violation] = []
    unmatched: list[str] = []
    for line in stripped.splitlines():
        if not line.strip():
            continue
        m = _FILE_LINE_COL.match(line) or _FILE_LINE.match(line)
        if m:
            violations.append(
                Violation(
                    rule=rule_id,
                    engine="script",
                    severity=severity,
                    line=int(m.group("line")),
                    description=m.group("msg").strip(),
                )
            )
            continue
        m = _LINE_CONTENT.match(line)
        if m:
            violations.append(
                Violation(
                    rule=rule_id,
                    engine="script",
                    severity=severity,
                    line=int(m.group("line")),
                    description=m.group("msg").strip(),
                )
            )
            continue
        unmatched.append(line)

    if violations:
        return violations

    return [
        Violation(
            rule=rule_id,
            engine="script",
            severity=severity,
            line=None,
            description=" ".join(unmatched)[:500],
        )
    ]


def execute_script_rule(rule: Rule, file_path: str, diff: str) -> list[Violation]:
    """Run a script-engine rule against a file."""
    cmd = rule.script.replace("{file}", file_path)
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            input=diff,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return [
            Violation(
                rule=rule.id,
                engine="script",
                severity=rule.severity,
                line=None,
                description=f"Script timed out after 30s: {cmd}",
            )
        ]

    if result.returncode != 0:
        violations = parse_script_output(rule.id, rule.severity, result.stdout)
        if not violations:
            return [
                Violation(
                    rule=rule.id,
                    engine="script",
                    severity=rule.severity,
                    line=None,
                    description=rule.description,
                )
            ]
        return violations

    return []


# ---------------------------------------------------------------------------
# Semantic payload + pipeline-side can't-match filters
# ---------------------------------------------------------------------------

_COMMENT_LINE_RE = re.compile(r"^\s*(?://|#|--)|^\s*/\*|^\s*\*/|^\s*\*\s")

_ADD_PERSPECTIVE_HINTS = ("avoid", "no ", "no-", "ban", "don't", "dont", "forbid")


def _hunk_added_lines(diff: str) -> list[str]:
    """Return lines added in the diff (lines starting with `+` but not `+++`)."""
    out: list[str] = []
    for line in diff.splitlines():
        if line.startswith("+++"):
            continue
        if line.startswith("+"):
            out.append(line[1:])
    return out


def _hunk_removed_lines(diff: str) -> list[str]:
    out: list[str] = []
    for line in diff.splitlines():
        if line.startswith("---"):
            continue
        if line.startswith("-"):
            out.append(line[1:])
    return out


def _all_whitespace(lines: list[str]) -> bool:
    return all(not line.strip() for line in lines)


def _all_comment(lines: list[str]) -> bool:
    if not lines:
        return False
    return all(_COMMENT_LINE_RE.match(line) or not line.strip() for line in lines)


def _rule_add_perspective(description: str) -> bool:
    d = description.lower()
    return any(h in d for h in _ADD_PERSPECTIVE_HINTS)


def _can_match_diff(rule: Rule, diff: str) -> tuple[bool, str]:
    """Return (should_evaluate, skip_reason_if_not)."""
    if not diff.strip():
        return False, "empty-diff"

    added = _hunk_added_lines(diff)
    removed = _hunk_removed_lines(diff)

    if added and _all_whitespace(added):
        return False, "whitespace-only-additions"

    if added and _all_comment(added) and "comment" not in rule.description.lower():
        return False, "comment-only-additions"

    if not added and removed and _rule_add_perspective(rule.description):
        return False, "pure-deletion-add-perspective-rule"

    if len(added) < 2 and not removed:
        return False, "too-few-added-lines"

    if added and len(added) < 2:
        return False, "too-few-added-lines"

    return True, ""


def build_semantic_payload(
    file_path: str,
    diff: str,
    passed_checks: list[str],
    semantic_rules: list[Rule],
) -> dict:
    """Build the payload the LLM uses for semantic evaluation.

    Structure intentionally separates the subagent-only input
    (`_evaluator_input`) from the full payload (which still carries
    `passed_checks` for the parent). The skill can strip the full payload
    to `_evaluator_input` before dispatching.
    """
    evaluate = [
        {"id": r.id, "description": r.description, "severity": r.severity} for r in semantic_rules
    ]
    payload = {
        "file": file_path,
        "diff": diff,
        "passed_checks": passed_checks,
        "evaluate": evaluate,
    }
    if SYNTHETIC_MARKER in diff:
        payload["line_anchors"] = "synthetic"

    # Evaluator input strips passed_checks (subagent doesn't use it for judgment).
    payload["_evaluator_input"] = {
        "file": file_path,
        "diff": diff,
        "evaluate": evaluate,
    }
    if SYNTHETIC_MARKER in diff:
        payload["_evaluator_input"]["line_anchors"] = "synthetic"
    return payload


# ---------------------------------------------------------------------------
# Baseline + per-line disables
# ---------------------------------------------------------------------------

_DISABLE_RE = re.compile(r"bully-disable\s*:?\s*(?P<ids>[^#\n\r]*?)(?:\s+(?P<reason>[^#\n\r]+))?$")


def _baseline_path(config_path: str) -> Path:
    return Path(config_path).resolve().parent / ".bully" / "baseline.json"


def _load_baseline(config_path: str) -> dict:
    p = _baseline_path(config_path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    out: dict[tuple[str, str, int, str], bool] = {}
    for entry in data.get("baseline", []):
        key = (
            entry.get("rule_id", ""),
            entry.get("file", ""),
            int(entry.get("line", 0) or 0),
            entry.get("checksum", ""),
        )
        out[key] = True
    return out


def _line_checksum(file_path: str, line: int | None) -> str:
    if line is None or line <= 0:
        return ""
    try:
        with open(file_path, encoding="utf-8", errors="replace") as f:
            for i, content in enumerate(f, start=1):
                if i == line:
                    return hashlib.sha256(content.encode("utf-8")).hexdigest()
    except OSError:
        return ""
    return ""


def _is_baselined(
    baseline: dict, rule_id: str, config_path: str, file_path: str, line: int | None
) -> bool:
    if not baseline or line is None:
        return False
    try:
        rel = str(Path(file_path).resolve().relative_to(Path(config_path).resolve().parent))
    except ValueError:
        rel = file_path
    checksum = _line_checksum(file_path, line)
    if not checksum:
        return False
    return (rule_id, rel, line, checksum) in baseline


def _parse_disable_directive(text: str) -> tuple[set[str] | None, str | None]:
    """Extract rule ids from an `bully-disable:` comment. Empty set = disable all."""
    m = _DISABLE_RE.search(text)
    if not m:
        return None, None
    ids_raw = (m.group("ids") or "").strip()
    reason = (m.group("reason") or "").strip() or None
    if not ids_raw:
        return set(), reason
    ids = {s.strip().rstrip(",") for s in re.split(r"[,\s]+", ids_raw) if s.strip()}
    return ids, reason


def _line_has_disable(file_path: str, line: int | None, rule_id: str) -> bool:
    """Return True if the violation line or the previous line carries a disable directive."""
    if line is None or line <= 0:
        return False
    try:
        with open(file_path, encoding="utf-8", errors="replace") as f:
            content_lines = f.readlines()
    except OSError:
        return False

    targets: list[str] = []
    if line - 1 < len(content_lines):
        targets.append(content_lines[line - 1])
    if line - 2 >= 0 and line - 2 < len(content_lines):
        targets.append(content_lines[line - 2])

    for text in targets:
        ids, _reason = _parse_disable_directive(text)
        if ids is None:
            continue
        if not ids or rule_id in ids:
            return True
    return False


# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------


def _telemetry_path(config_path: str) -> Path | None:
    """Return the telemetry log path if telemetry is enabled for this project."""
    project_dir = Path(config_path).resolve().parent
    tel_dir = project_dir / ".bully"
    if not tel_dir.is_dir():
        return None
    return tel_dir / "log.jsonl"


def _append_telemetry(
    log_path: Path,
    file_path: str,
    status: str,
    rule_records: list[dict],
    latency_ms: int,
) -> None:
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "file": file_path,
        "status": status,
        "latency_ms": latency_ms,
        "rules": rule_records,
    }
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        pass


def _append_record(log_path: Path, record: dict) -> None:
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Pipeline orchestration
# ---------------------------------------------------------------------------


def run_pipeline(
    config_path: str,
    file_path: str,
    diff: str,
    rule_filter: set[str] | None = None,
) -> dict:
    """Full two-phase pipeline.

    Phase 1: script rules. If any error-severity violations, block.
    Phase 2: build semantic payload for remaining semantic rules.
    """
    start = time.perf_counter()
    rule_records: list[dict] = []
    log_path = _telemetry_path(config_path)

    # Short-circuit auto-generated files.
    if _path_matches_skip(file_path):
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        result = {"status": "skipped", "file": file_path, "reason": "auto-generated"}
        if log_path is not None:
            _append_telemetry(log_path, file_path, "skipped", rule_records, elapsed_ms)
        return result

    rules = parse_config(config_path)
    matching = filter_rules(rules, file_path)
    if rule_filter:
        matching = [r for r in matching if r.id in rule_filter]

    def flush(status: str, result: dict) -> dict:
        if log_path is not None:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            _append_telemetry(log_path, file_path, status, rule_records, elapsed_ms)
        return result

    if not matching:
        return flush("pass", {"status": "pass", "file": file_path})

    script_rules = [r for r in matching if r.engine == "script"]
    semantic_rules = [r for r in matching if r.engine == "semantic"]

    all_violations: list[Violation] = []
    passed_checks: list[str] = []
    baseline = _load_baseline(config_path)

    for rule in script_rules:
        rule_start = time.perf_counter()
        violations = execute_script_rule(rule, file_path, diff)
        rule_ms = int((time.perf_counter() - rule_start) * 1000)

        # Apply fix_hint as fallback suggestion.
        if rule.fix_hint:
            violations = [replace(v, suggestion=v.suggestion or rule.fix_hint) for v in violations]

        # Filter per-line disables.
        filtered: list[Violation] = []
        for v in violations:
            if _line_has_disable(file_path, v.line, rule.id):
                continue
            if _is_baselined(baseline, rule.id, config_path, file_path, v.line):
                continue
            filtered.append(v)
        violations = filtered

        if violations:
            all_violations.extend(violations)
            rule_records.append(
                {
                    "id": rule.id,
                    "engine": "script",
                    "verdict": "violation",
                    "severity": rule.severity,
                    "line": violations[0].line,
                    "latency_ms": rule_ms,
                }
            )
        else:
            passed_checks.append(rule.id)
            rule_records.append(
                {
                    "id": rule.id,
                    "engine": "script",
                    "verdict": "pass",
                    "severity": rule.severity,
                    "latency_ms": rule_ms,
                }
            )

    # Can't-match filters for semantic rules.
    dispatched_semantic: list[Rule] = []
    for rule in semantic_rules:
        ok, reason = _can_match_diff(rule, diff)
        if ok:
            dispatched_semantic.append(rule)
            rule_records.append(
                {
                    "id": rule.id,
                    "engine": "semantic",
                    "verdict": "evaluate_requested",
                    "severity": rule.severity,
                }
            )
        else:
            if log_path is not None:
                _append_record(
                    log_path,
                    {
                        "ts": datetime.now(timezone.utc)
                        .isoformat(timespec="seconds")
                        .replace("+00:00", "Z"),
                        "type": "semantic_skipped",
                        "file": file_path,
                        "rule": rule.id,
                        "reason": reason,
                    },
                )

    blocking = [v for v in all_violations if v.severity == "error"]

    if blocking:
        return flush(
            "blocked",
            {
                "status": "blocked",
                "file": file_path,
                "violations": [asdict(v) for v in all_violations],
                "passed": passed_checks,
            },
        )

    if dispatched_semantic:
        payload = build_semantic_payload(file_path, diff, passed_checks, dispatched_semantic)
        result = {"status": "evaluate", **payload}
        if _was_write_truncated_for_path(file_path):
            result["write_content"] = "truncated"
        if all_violations:
            result["warnings"] = [asdict(v) for v in all_violations]
        return flush("evaluate", result)

    result = {"status": "pass", "file": file_path, "passed": passed_checks}
    if all_violations:
        result["warnings"] = [asdict(v) for v in all_violations]
    return flush("pass", result)


def _was_write_truncated_for_path(file_path: str) -> bool:
    """Cheap stat-only check that doesn't re-read huge files into memory unnecessarily."""
    try:
        with open(file_path, encoding="utf-8", errors="replace") as f:
            count = sum(1 for _ in f)
        return count > _WRITE_MAX_LINES
    except OSError:
        return False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _format_blocked_stderr(result: dict) -> str:
    """Render a blocked pipeline result as agent-readable text for stderr."""
    lines = ["AGENTIC LINT -- blocked. Fix these before proceeding:", ""]
    for v in result.get("violations", []):
        line_repr = v.get("line") if v.get("line") is not None else "?"
        lines.append(f"- [{v['rule']}] line {line_repr}: {v['description']}")
        if v.get("suggestion"):
            lines.append(f"  suggestion: {v['suggestion']}")
    passed = result.get("passed", [])
    if passed:
        lines.append("")
        lines.append(f"Passed checks: {', '.join(passed)}")
    return "\n".join(lines) + "\n"


def _read_stdin_payload() -> dict:
    """Read stdin; if JSON, return parsed dict, else wrap as raw diff."""
    if sys.stdin.isatty():
        return {}
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        pass
    return {"diff": raw}


def _build_semantic_prompt(payload: dict) -> str:
    """Render the semantic evaluation payload as a human-readable prompt."""
    lines = [
        f"Evaluate this diff against the rules below. File: {payload.get('file', '?')}",
        "",
    ]
    passed = payload.get("passed_checks", [])
    if passed:
        lines.append(f"Already passed (do not re-evaluate): {', '.join(passed)}")
        lines.append("")
    lines.append("Rules to evaluate:")
    for r in payload.get("evaluate", []):
        lines.append(f"- [{r['id']}] ({r['severity']}): {r['description']}")
    lines.append("")
    lines.append("Diff:")
    lines.append(payload.get("diff", ""))
    lines.append("")
    lines.append(
        "For each violation: rule id, line number, description, fix suggestion. "
        "If no violations, say 'no violations' explicitly."
    )
    return "\n".join(lines)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="pipeline.py",
        description="Agentic Lint pipeline. Runs script and semantic rules for a file.",
    )
    parser.add_argument("positional", nargs="*", help=argparse.SUPPRESS)
    parser.add_argument("--config", help="Path to .bully.yml")
    parser.add_argument("--file", dest="file_path", help="Target file to evaluate")
    parser.add_argument(
        "--rule",
        action="append",
        default=[],
        help="Evaluate only this rule id. Repeatable.",
    )
    parser.add_argument(
        "--print-prompt",
        action="store_true",
        help="Print the LLM prompt text for the semantic payload instead of JSON.",
    )
    parser.add_argument("--diff", help="Inline diff string (bypasses stdin).")
    parser.add_argument(
        "--hook-mode",
        action="store_true",
        help="Read tool-hook JSON on stdin and emit Claude Code hook output.",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate the config file: parse, check enums, exit nonzero on error.",
    )
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="Run diagnostic checks and exit.",
    )
    parser.add_argument(
        "--show-resolved-config",
        action="store_true",
        help="Print merged rules (after resolving extends) as compact text.",
    )
    parser.add_argument(
        "--baseline-init",
        action="store_true",
        help="Run the pipeline over a glob and write current violations to baseline.json.",
    )
    parser.add_argument(
        "--glob",
        default=None,
        help="Glob pattern for --baseline-init (relative to config dir).",
    )
    parser.add_argument(
        "--log-verdict",
        action="store_true",
        help="Append a semantic_verdict telemetry record.",
    )
    parser.add_argument("--verdict", choices=("pass", "violation"), default=None)
    args = parser.parse_args(argv)
    # Back-compat: accept positional args (used by hook)
    if args.positional and not args.config:
        args.config = args.positional[0]
    if len(args.positional) >= 2 and not args.file_path:
        args.file_path = args.positional[1]
    return args


# ---- subcommand handlers ----


def _cmd_validate(config_path: str | None) -> int:
    path = config_path or ".bully.yml"
    if not os.path.exists(path):
        print(f"[FAIL] config not found: {path}", file=sys.stderr)
        return 1
    try:
        rules = parse_config(path)
    except ConfigError as e:
        print(f"[FAIL] {path}: {e}", file=sys.stderr)
        return 1
    print(f"[OK] parsed {len(rules)} rule(s) from {path}")
    for r in rules:
        print(f"  - {r.id}  engine={r.engine}  severity={r.severity}  scope={list(r.scope)}")
    return 0


def _cmd_show_resolved(config_path: str | None) -> int:
    path = config_path or ".bully.yml"
    try:
        rules = parse_config(path)
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    for r in rules:
        print(
            f"{r.id}\tengine={r.engine}\tseverity={r.severity}\t"
            f"scope={','.join(r.scope)}\tfix_hint={r.fix_hint or ''}"
        )
    return 0


def _cmd_doctor() -> int:
    ok = True

    # Python version
    print(f"[OK] Python {sys.version_info.major}.{sys.version_info.minor} >= 3.10")

    # Config present
    cfg = Path.cwd() / ".bully.yml"
    if cfg.is_file():
        print(f"[OK] config present at {cfg}")
    else:
        print(f"[FAIL] no .bully.yml at {Path.cwd()}")
        ok = False

    # Config parses
    if cfg.is_file():
        try:
            rules = parse_config(str(cfg))
            print(f"[OK] config parses ({len(rules)} rules)")
        except ConfigError as e:
            print(f"[FAIL] config parse error: {e}")
            ok = False

    # PostToolUse hook wired in .claude/settings.json
    hook_wired = False
    for settings in (
        Path.cwd() / ".claude" / "settings.json",
        Path.home() / ".claude" / "settings.json",
    ):
        if not settings.is_file():
            continue
        try:
            data = json.loads(settings.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        hooks = data.get("hooks", {})
        entries = hooks.get("PostToolUse", [])
        if isinstance(entries, list):
            for entry in entries:
                for h in entry.get("hooks", []) if isinstance(entry, dict) else []:
                    if "hook.sh" in str(h.get("command", "")):
                        hook_wired = True
                        break
                if hook_wired:
                    break
        if hook_wired:
            print(f"[OK] PostToolUse hook wired in {settings}")
            break
    if not hook_wired:
        print("[FAIL] no PostToolUse hook invoking hook.sh found in .claude/settings.json")
        ok = False

    # Evaluator subagent definition
    claude_home = Path(os.environ.get("CLAUDE_HOME", str(Path.home() / ".claude")))
    agent_file = claude_home / "agents" / "bully-evaluator.md"
    if agent_file.is_file():
        print(f"[OK] evaluator agent at {agent_file}")
    else:
        print(f"[FAIL] evaluator agent missing at {agent_file}")
        ok = False

    # Skills
    for suffix in (
        "bully",
        "bully-init",
        "bully-author",
        "bully-review",
    ):
        skill_md = Path.home() / ".claude" / "skills" / suffix / "SKILL.md"
        if skill_md.is_file():
            print(f"[OK] skill {suffix} present")
        else:
            print(f"[FAIL] skill {suffix} missing (expected at {skill_md})")
            ok = False

    return 0 if ok else 1


def _cmd_log_verdict(
    config_path: str | None, rule_id: str, verdict: str, file_path: str | None
) -> int:
    path = config_path or ".bully.yml"
    log_path = _telemetry_path(path)
    if log_path is None:
        print(
            "telemetry disabled (no .bully/ directory next to config)",
            file=sys.stderr,
        )
        return 0
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "type": "semantic_verdict",
        "rule": rule_id,
        "verdict": verdict,
    }
    if file_path:
        record["file"] = file_path
    _append_record(log_path, record)
    return 0


def _cmd_baseline_init(config_path: str | None, glob: str | None) -> int:
    path = config_path or ".bully.yml"
    cfg_abs = Path(path).resolve()
    if not cfg_abs.exists():
        print(f"config not found: {path}", file=sys.stderr)
        return 1
    root = cfg_abs.parent
    if not glob:
        glob = "**/*"
    entries: list[dict] = []
    for candidate in root.glob(glob):
        if not candidate.is_file():
            continue
        if _path_matches_skip(str(candidate)):
            continue
        try:
            result = run_pipeline(str(cfg_abs), str(candidate), "")
        except ConfigError as e:
            print(f"config error: {e}", file=sys.stderr)
            return 1
        if result.get("status") != "blocked":
            continue
        for v in result.get("violations", []):
            line = v.get("line")
            checksum = _line_checksum(str(candidate), line)
            try:
                rel = str(candidate.resolve().relative_to(root))
            except ValueError:
                rel = str(candidate)
            entries.append(
                {
                    "rule_id": v["rule"],
                    "file": rel,
                    "line": line or 0,
                    "checksum": checksum,
                }
            )
    out_dir = root / ".bully"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / "baseline.json"
    out.write_text(json.dumps({"baseline": entries}, indent=2) + "\n")
    print(f"wrote {len(entries)} baseline entries to {out}")
    return 0


# ---- hook-mode + main ----


def _find_config_upward(start: Path) -> Path | None:
    cur = start.resolve()
    if cur.is_file():
        cur = cur.parent
    for p in (cur, *cur.parents):
        candidate = p / ".bully.yml"
        if candidate.is_file():
            return candidate
    return None


def _hook_mode() -> int:
    """Read stdin JSON from Claude Code, run the pipeline, emit hook output."""
    payload = _read_stdin_payload()
    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {})
    if not isinstance(tool_input, dict):
        tool_input = {}
    file_path = tool_input.get("file_path") or payload.get("file_path") or ""
    old_string = tool_input.get("old_string", "") or payload.get("old_string", "") or ""
    if tool_name == "Write":
        new_string = (
            tool_input.get("content")
            or tool_input.get("new_string")
            or payload.get("content")
            or payload.get("new_string")
            or ""
        )
    else:
        new_string = tool_input.get("new_string", "") or payload.get("new_string", "") or ""

    if not file_path or not Path(file_path).is_file():
        return 0

    config = _find_config_upward(Path(file_path))
    if config is None:
        return 0

    diff = build_diff_context(
        tool_name=tool_name,
        file_path=file_path,
        old_string=old_string,
        new_string=new_string,
    )

    try:
        result = run_pipeline(str(config), file_path, diff)
    except ConfigError as e:
        sys.stderr.write(f"AGENTIC LINT -- config error: {e}\n")
        return 0

    status = result.get("status", "pass")
    if status == "blocked":
        sys.stderr.write(_format_blocked_stderr(result))
        return 2
    if status == "evaluate":
        ctx = "AGENTIC LINT SEMANTIC EVALUATION REQUIRED:\n\n" + json.dumps(
            result, separators=(",", ":")
        )
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PostToolUse",
                        "additionalContext": ctx,
                    }
                }
            )
        )
    return 0


def main() -> None:
    args = _parse_args(sys.argv[1:])

    # Subcommands.
    if args.validate:
        sys.exit(_cmd_validate(args.config))
    if args.doctor:
        sys.exit(_cmd_doctor())
    if args.show_resolved_config:
        sys.exit(_cmd_show_resolved(args.config))
    if args.baseline_init:
        sys.exit(_cmd_baseline_init(args.config, args.glob))
    if args.log_verdict:
        if not args.rule or not args.verdict:
            print(
                "usage: --log-verdict --rule RULE_ID --verdict pass|violation [--file PATH]",
                file=sys.stderr,
            )
            sys.exit(1)
        rule_id = args.rule[0] if args.rule else ""
        sys.exit(_cmd_log_verdict(args.config, rule_id, args.verdict, args.file_path))
    if args.hook_mode:
        sys.exit(_hook_mode())

    if not args.config or not args.file_path:
        print(
            json.dumps(
                {
                    "error": "Usage: pipeline.py --config <path> --file <path> "
                    "(or positional: pipeline.py <config> <file>)"
                }
            ),
            file=sys.stderr,
        )
        sys.exit(1)

    config_path = args.config
    file_path = args.file_path

    if not os.path.exists(config_path):
        print(json.dumps({"status": "pass", "file": file_path, "reason": "no config found"}))
        sys.exit(0)

    if args.diff is not None:
        diff = args.diff
    else:
        payload = _read_stdin_payload()
        if "diff" in payload:
            diff = payload["diff"]
        elif "tool_name" in payload:
            tool_input = (
                payload.get("tool_input", {}) if isinstance(payload.get("tool_input"), dict) else {}
            )
            diff = build_diff_context(
                tool_name=payload.get("tool_name", ""),
                file_path=tool_input.get("file_path") or payload.get("file_path", file_path),
                old_string=tool_input.get("old_string") or payload.get("old_string", ""),
                new_string=(
                    tool_input.get("content")
                    or tool_input.get("new_string")
                    or payload.get("new_string", "")
                ),
            )
        else:
            diff = ""

    try:
        result = run_pipeline(
            config_path,
            file_path,
            diff,
            rule_filter=set(args.rule) if args.rule else None,
        )
    except ConfigError as e:
        print(json.dumps({"status": "error", "error": str(e)}), file=sys.stderr)
        sys.exit(1)

    if args.print_prompt:
        if result.get("status") == "evaluate":
            print(_build_semantic_prompt(result))
        else:
            print(
                json.dumps(
                    {
                        "note": "No semantic evaluation to print (status is not 'evaluate').",
                        "result": result,
                    },
                    indent=2,
                )
            )
        return

    print(json.dumps(result, indent=2))

    if result.get("status") == "blocked":
        sys.stderr.write(_format_blocked_stderr(result))
        sys.exit(2)


if __name__ == "__main__":
    main()
