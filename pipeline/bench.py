"""
Bully Test Bench

Two modes:
  bully bench                         -- run fixture suite, append to bench/history.jsonl
  bully bench --config <path>         -- analyze token cost of any .bully.yml

Stdlib-only except for the optional `anthropic` import, which is gated
behind API-key presence and falls back to a char-count proxy.
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bully bench",
        description="Measure bully's speed and input-token cost.",
    )
    parser.add_argument(
        "--config",
        help="Path to a .bully.yml; enables Mode B (config cost analysis).",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Mode A only: diff the last two runs in bench/history.jsonl.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of a formatted table.",
    )
    parser.add_argument(
        "--no-tokens",
        action="store_true",
        help="Skip Anthropic API call; use char-count proxy for token counts.",
    )
    parser.add_argument(
        "--fixtures-dir",
        default="bench/fixtures",
        help="Directory of fixture subdirectories (default: bench/fixtures).",
    )
    parser.add_argument(
        "--history",
        default="bench/history.jsonl",
        help="Path to history JSONL (default: bench/history.jsonl).",
    )

    parser.parse_args(argv)

    # Stub: subsequent tasks will dispatch to mode_a / mode_b / compare.
    print("bench: not yet implemented", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
