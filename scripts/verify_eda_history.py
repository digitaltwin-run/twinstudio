#!/usr/bin/env python3
"""Verify the hash chain of a portable TwinStudio EDA log."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from twinstudio.eda_history import validate_hash_chain


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=Path(".twinstudio/logs/eda.jsonl"),
    )
    parser.add_argument("--allow-missing", action="store_true")
    args = parser.parse_args()
    if not args.path.is_file():
        if args.allow_missing:
            print(f"EDA history absent: {args.path}")
            return 0
        parser.error(f"file does not exist: {args.path}")
    events = [json.loads(line) for line in args.path.read_text(encoding="utf-8").splitlines() if line.strip()]
    findings = validate_hash_chain(events)
    if findings:
        print("Invalid EDA history hash chain: " + ", ".join(findings))
        return 1
    print(f"Valid EDA history hash chain: {len(events)} event(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
