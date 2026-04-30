"""Tests for config parsing and rule filtering."""

from pathlib import Path

import pytest

from bully import ConfigError, Rule, filter_rules, parse_config

FIXTURES = Path(__file__).parent / "fixtures"


def _write_config(tmp_path: Path, body: str) -> Path:
    p = tmp_path / ".bully.yml"
    p.write_text(body)
    return p


def test_parses_script_rule():
    rules = parse_config(str(FIXTURES / "basic-config.yml"))
    script_rules = [r for r in rules if r.engine == "script"]
    assert len(script_rules) == 1
    rule = script_rules[0]
    assert rule.id == "no-compact"
    assert rule.description == "Do not use compact() -- use explicit arrays"
    assert rule.engine == "script"
    assert rule.scope == ("*.php",)
    assert rule.severity == "error"
    assert "grep" in rule.script


def test_parses_semantic_rule_with_folded_description():
    rules = parse_config(str(FIXTURES / "basic-config.yml"))
    semantic_rules = [r for r in rules if r.engine == "semantic"]
    assert len(semantic_rules) == 1
    rule = semantic_rules[0]
    assert rule.id == "inline-single-use-vars"
    assert "Inline variables" in rule.description
    assert "once after assignment" in rule.description
    assert rule.script is None


def test_parses_multiple_rules():
    rules = parse_config(str(FIXTURES / "multi-rule-config.yml"))
    assert len(rules) == 6
    ids = [r.id for r in rules]
    assert "no-compact" in ids
    assert "no-db-facade" in ids
    assert "inline-single-use-vars" in ids
    assert "extract-complex-logic" in ids
    assert "js-no-console" in ids


def test_filter_matches_php_files():
    rules = parse_config(str(FIXTURES / "multi-rule-config.yml"))
    matched = filter_rules(rules, "src/Stores/EloquentRoleStore.php")
    ids = [r.id for r in matched]
    assert "no-compact" in ids
    assert "no-db-facade" in ids
    assert "inline-single-use-vars" in ids
    assert "extract-complex-logic" in ids  # scope: "*"
    assert "js-no-console" not in ids


def test_filter_matches_js_files():
    rules = parse_config(str(FIXTURES / "multi-rule-config.yml"))
    matched = filter_rules(rules, "src/app.js")
    ids = [r.id for r in matched]
    assert "js-no-console" in ids
    assert "extract-complex-logic" in ids  # scope: "*"
    assert "no-compact" not in ids


def test_filter_no_match_returns_empty():
    rules = parse_config(str(FIXTURES / "multi-rule-config.yml"))
    matched = filter_rules(rules, "README.md")
    ids = [r.id for r in matched]
    assert "no-compact" not in ids
    assert "js-no-console" not in ids
    assert "extract-complex-logic" in ids  # scope: "*" matches everything


def test_filter_wildcard_scope_matches_all():
    rules = [
        Rule(id="universal", description="test", engine="semantic", scope="*", severity="error")
    ]
    assert len(filter_rules(rules, "anything.txt")) == 1
    assert len(filter_rules(rules, "deep/nested/file.php")) == 1


# ---- semantic-rule description validation ------------------------------


def test_semantic_rule_missing_description_raises(tmp_path: Path):
    cfg = _write_config(
        tmp_path,
        "schema_version: 1\n"
        "rules:\n"
        "  no-desc:\n"
        "    engine: semantic\n"
        '    scope: "*.py"\n'
        "    severity: error\n",
    )
    with pytest.raises(ConfigError) as exc:
        parse_config(str(cfg))
    msg = str(exc.value)
    assert "description" in msg
    assert "semantic" in msg


def test_semantic_rule_empty_description_raises(tmp_path: Path):
    cfg = _write_config(
        tmp_path,
        "schema_version: 1\n"
        "rules:\n"
        "  empty-desc:\n"
        '    description: ""\n'
        "    engine: semantic\n"
        '    scope: "*.py"\n'
        "    severity: error\n",
    )
    with pytest.raises(ConfigError) as exc:
        parse_config(str(cfg))
    msg = str(exc.value)
    assert "description" in msg
    assert "semantic" in msg


def test_semantic_rule_whitespace_description_raises(tmp_path: Path):
    cfg = _write_config(
        tmp_path,
        "schema_version: 1\n"
        "rules:\n"
        "  whitespace-desc:\n"
        '    description: "   "\n'
        "    engine: semantic\n"
        '    scope: "*.py"\n'
        "    severity: error\n",
    )
    with pytest.raises(ConfigError) as exc:
        parse_config(str(cfg))
    msg = str(exc.value)
    assert "description" in msg
    assert "semantic" in msg


def test_semantic_rule_with_valid_description_parses(tmp_path: Path):
    cfg = _write_config(
        tmp_path,
        "schema_version: 1\n"
        "rules:\n"
        "  good-desc:\n"
        '    description: "Avoid bare except in production code"\n'
        "    engine: semantic\n"
        '    scope: "*.py"\n'
        "    severity: error\n",
    )
    rules = parse_config(str(cfg))
    assert len(rules) == 1
    assert rules[0].id == "good-desc"
    assert rules[0].engine == "semantic"
    assert rules[0].description == "Avoid bare except in production code"


def test_script_rule_without_description_still_parses(tmp_path: Path):
    cfg = _write_config(
        tmp_path,
        "schema_version: 1\n"
        "rules:\n"
        "  script-no-desc:\n"
        "    engine: script\n"
        '    scope: "*.py"\n'
        "    severity: error\n"
        '    script: "exit 0"\n',
    )
    rules = parse_config(str(cfg))
    assert len(rules) == 1
    assert rules[0].id == "script-no-desc"
    assert rules[0].description == ""


def test_ast_rule_without_description_still_parses(tmp_path: Path):
    cfg = _write_config(
        tmp_path,
        "schema_version: 1\n"
        "rules:\n"
        "  ast-no-desc:\n"
        "    engine: ast\n"
        '    scope: "*.py"\n'
        "    severity: error\n"
        '    pattern: "print($X)"\n',
    )
    rules = parse_config(str(cfg))
    assert len(rules) == 1
    assert rules[0].id == "ast-no-desc"
    assert rules[0].description == ""
