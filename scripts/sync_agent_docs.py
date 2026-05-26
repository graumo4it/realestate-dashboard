#!/usr/bin/env python3
"""Synchronize CLAUDE.md from AGENTS.md.

AGENTS.md is the source of truth. CLAUDE.md has the same body with a
Claude-specific heading and intro sentence.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "AGENTS.md"
CLAUDE = ROOT / "CLAUDE.md"


REPLACEMENTS = (
    (
        "# AGENTS.md",
        "# CLAUDE.md",
    ),
    (
        "This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.",
        "This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.",
    ),
)


def render_claude(source: str) -> str:
    result = source
    for old, new in REPLACEMENTS:
        if old not in result:
            raise ValueError(f"Expected text not found in AGENTS.md: {old!r}")
        result = result.replace(old, new, 1)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit with non-zero status if CLAUDE.md is out of sync",
    )
    args = parser.parse_args()

    try:
        source = AGENTS.read_text(encoding="utf-8")
        expected = render_claude(source)
    except Exception as exc:
        print(f"sync_agent_docs.py: {exc}", file=sys.stderr)
        return 1

    current = CLAUDE.read_text(encoding="utf-8") if CLAUDE.exists() else ""

    if args.check:
        if current != expected:
            print("CLAUDE.md is out of sync with AGENTS.md", file=sys.stderr)
            return 1
        return 0

    if current != expected:
        CLAUDE.write_text(expected, encoding="utf-8")
        print("Updated CLAUDE.md from AGENTS.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
