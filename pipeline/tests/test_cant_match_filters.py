"""Tests for pipeline-side can't-match filters (plan 4.2)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import Rule, _can_match_diff


def _rule(desc: str = "avoid the bad pattern") -> Rule:
    return Rule(
        id="r",
        description=desc,
        engine="semantic",
        scope=("*",),
        severity="error",
    )


def test_empty_diff_skipped():
    ok, reason = _can_match_diff(_rule(), "")
    assert ok is False
    assert reason == "empty-diff"


def test_whitespace_only_additions_skipped():
    diff = "@@ -1,2 +1,4 @@\n+   \n+\t\n"
    ok, reason = _can_match_diff(_rule(), diff)
    assert ok is False
    assert reason == "whitespace-only-additions"


def test_comment_only_additions_skip_non_comment_rule():
    diff = "@@ -1,2 +1,4 @@\n+// a comment\n+// another comment\n"
    ok, reason = _can_match_diff(_rule("avoid bad variable names"), diff)
    assert ok is False
    assert reason == "comment-only-additions"


def test_comment_only_additions_kept_for_comment_rule():
    diff = "@@ -1,2 +1,4 @@\n+// a comment\n+// another comment\n"
    r = _rule("comment quality must be professional")
    ok, _ = _can_match_diff(r, diff)
    assert ok is True


def test_pure_deletion_skips_avoid_rule():
    diff = "@@ -1,2 +0,0 @@\n-old line 1\n-old line 2\n"
    ok, reason = _can_match_diff(_rule("avoid X"), diff)
    assert ok is False
    assert reason == "pure-deletion-add-perspective-rule"


def test_pure_deletion_kept_for_refactor_rule():
    diff = "@@ -1,2 +0,0 @@\n-old line 1\n-old line 2\n"
    # no avoid/no/ban/don't in description
    r = _rule("extract helper methods when appropriate")
    ok, _ = _can_match_diff(r, diff)
    assert ok is True


def test_too_few_added_lines_skipped():
    diff = "@@ -5,1 +5,2 @@\n+only one new line\n"
    ok, reason = _can_match_diff(_rule(), diff)
    assert ok is False
    assert reason == "too-few-added-lines"


def test_enough_added_lines_passes():
    diff = "@@ -5,1 +5,3 @@\n+added line one\n+added line two\n"
    ok, _ = _can_match_diff(_rule(), diff)
    assert ok is True


def test_hash_comment_only_additions_skipped():
    diff = "@@ -1,2 +1,4 @@\n+# hash comment 1\n+# hash comment 2\n"
    ok, reason = _can_match_diff(_rule("avoid bad names"), diff)
    assert ok is False
    assert reason == "comment-only-additions"


def test_sql_dash_dash_comment_only_additions_skipped():
    diff = "@@ -1,2 +1,4 @@\n+-- SQL comment\n+-- another comment\n"
    ok, reason = _can_match_diff(_rule("avoid joins"), diff)
    assert ok is False
    assert reason == "comment-only-additions"
