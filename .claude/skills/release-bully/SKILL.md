---
name: release-bully
description: Use when cutting a new bully release — bumping the plugin version so Claude Code users get an update notification. Triggers include "cut a release", "ship a new version", "release vX.Y.Z", "bump the version", or "publish an update to bully".
---

# Release bully

## Overview

Bully is a Claude Code plugin. Claude Code detects updates by comparing the `version` field in the marketplace repo against the user's installed version. A release = bump SemVer everywhere, rewrite the changelog, commit, tag, push, create a GitHub release. Do not skip steps — inconsistent version fields break update detection silently.

## When to use

- User asks to cut a release, ship a version, or publish an update.
- Version bumps in `plugin.json`, `marketplace.json`, or `pyproject.toml` — all three must move together.

**Do not use for:** dependency bumps, internal refactors, or any change that doesn't warrant a new published version.

## Version fields (all four must match)

| File | Path | Field |
|------|------|-------|
| `.claude-plugin/plugin.json` | root | `version` |
| `.claude-plugin/marketplace.json` | root | `metadata.version` |
| `.claude-plugin/marketplace.json` | first plugin entry | `plugins[0].version` |
| `pyproject.toml` | `[project]` table | `version` |
| `pipeline/pipeline.py` | top of file | `BULLY_VERSION = "..."` (stamped into `session_init` telemetry records) |

Drift between these is the most common release bug. Grep to verify after editing:

```bash
grep -RnE '"version"|^version|^BULLY_VERSION' .claude-plugin/ pyproject.toml pipeline/pipeline.py
```

All five lines must show the new version.

## Workflow

### 1. Pre-flight

```bash
git status                    # working tree must be clean
git rev-parse --abbrev-ref HEAD  # must be main
git fetch origin && git status   # must be up to date with origin/main
bash scripts/lint.sh          # ruff + shellcheck + pytest + dogfood must pass
```

If any check fails, stop. Do not release from a dirty or failing tree.

### 2. Decide the bump

Look at commits since the last tag:

```bash
LAST=$(git describe --tags --abbrev=0 2>/dev/null || echo "")
git log ${LAST:+$LAST..}HEAD --oneline
```

Apply SemVer:

- **Patch** (`0.1.0` → `0.1.1`): bug fixes, docs, internal refactor, no behavior change.
- **Minor** (`0.1.0` → `0.2.0`): new features, new rules, new skills, added CLI flags — backwards-compatible.
- **Major** (`0.1.0` → `1.0.0`): schema changes to `.bully.yml`, removed/renamed rules, breaking hook contract, changed exit codes. **Schema bumps for `.bully.yml` (e.g. `schema_version: 1` → `2`) are always major.**

If the commit list mixes categories, pick the highest-impact bump. If unsure, ask the user.

### 3. Edit the five version fields

Use `Edit` (not `sed`) to update each file. Exact new string in every case: `X.Y.Z` (no leading `v`).

For `marketplace.json`, there are two occurrences — bump both.

For `pipeline/pipeline.py`, update the `BULLY_VERSION = "X.Y.Z"` constant near the top. This value gets stamped into every `session_init` telemetry record, so it must match the released version exactly.

### 4. Rewrite CHANGELOG.md

Target format (Keep a Changelog + SemVer, matching the existing file):

```markdown
## [Unreleased]
### Planned
See docs/plan.md for the active improvement plan.

## [X.Y.Z] - YYYY-MM-DD
### Added
- ...
### Changed
- ...
### Fixed
- ...

## [0.1.0] - 2026-04-16
...
```

Steps:
1. Move whatever was under `## [Unreleased]` into a new `## [X.Y.Z] - YYYY-MM-DD` section (today's date, ISO).
2. Use `Added` / `Changed` / `Fixed` / `Removed` / `Security` subheads as applicable. Drop empty ones.
3. Reset `## [Unreleased]` to just the `### Planned` placeholder.
4. Entries should describe user-visible change and motivation — read them as if they were release notes, because they are.

If the `[Unreleased]` section is empty or placeholder-only, derive entries from `git log ${LAST:+$LAST..}HEAD --oneline` and confirm with the user.

### 5. Verify before committing

```bash
grep -RnE '"version"|^version|^BULLY_VERSION' .claude-plugin/ pyproject.toml pipeline/pipeline.py
git diff
```

All five version lines must show `X.Y.Z`. Diff should touch only the five version fields and `CHANGELOG.md`. If anything else changed, abort.

### 6. Commit, tag, push

```bash
git add .claude-plugin/plugin.json .claude-plugin/marketplace.json pyproject.toml pipeline/pipeline.py CHANGELOG.md
git commit -m "Release v0.2.0"
```

Set the version once, then reuse it so nothing drifts:

```bash
V=0.2.0   # no leading v
awk -v ver="$V" 'BEGIN{p="^## \\[" ver "\\]"} $0~p{f=1;next} /^## \[/{f=0} f' CHANGELOG.md > /tmp/bully-release-notes.md
test -s /tmp/bully-release-notes.md || { echo "empty release notes — CHANGELOG section missing"; exit 1; }

git tag -a "v$V" -F /tmp/bully-release-notes.md
git push origin main
git push origin "v$V"
```

### 7. GitHub release

```bash
gh release create "v$V" --title "v$V" --notes-file /tmp/bully-release-notes.md
```

If `gh` is not authenticated, stop and tell the user to run `gh auth login` — do not try to paper over auth errors.

### 8. Announce result

Report: version bumped, tag pushed, release URL (from `gh release create` output). Note that Claude Code users running `/plugin update bully` will now pick up the new version.

## Common mistakes

| Mistake | Fix |
|---------|-----|
| Only bumped `plugin.json`, not `marketplace.json` | Re-run the grep in §5 — all five lines must match. |
| Tagged before pushing commit | Push the commit first, then the tag — otherwise remote has an orphan tag. |
| Used a lightweight tag (`git tag v0.2.0`) | Use `-a ... -F ...` for an annotated tag with release notes. |
| `gh release create` before `git push origin <tag>` | Push the tag first; `gh release create` needs it on the remote. |
| Picked patch when a breaking change landed | Re-read commits. If users need to edit their `.bully.yml` or re-wire hooks, it's major. |
| Committed with uncommitted unrelated changes | Stash them first. The release commit must be version + changelog only. |

## Abort criteria

Stop mid-flow if any of these happen — do not try to "just fix it forward":

- Lint or tests fail during pre-flight.
- Four version fields don't all match after edits.
- `git diff` shows unexpected files.
- `git push` rejects (someone else pushed; pull/rebase and restart from §1).
- `gh release create` fails with anything other than "release already exists".

When you stop, leave the tree in whatever state the failure produced and surface the error to the user. Do not `git reset --hard` — they may want to salvage work.
