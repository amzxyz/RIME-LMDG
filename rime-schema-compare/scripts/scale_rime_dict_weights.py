#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scale the trailing integer weight in Rime dict YAML lines (tab-separated:
  text<TAB>code<TAB>weight
) under vendor/rime-frost/cn_dicts and cn_dicts_cell.

Default multiplier 205_000 matches the breakeven scale discussed for Poet
paths (see project notes). Use --dry-run first.

Usage (from repo root):
  python scripts/scale_rime_dict_weights.py --dry-run
  python scripts/scale_rime_dict_weights.py --backup
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

# Breakeven ~ exp(12.22); rounded for YAML integers
DEFAULT_MULTIPLIER = 205_000


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_target_dirs(root: Path) -> list[Path]:
    return [
        root / "vendor" / "rime-frost" / "cn_dicts",
        root / "vendor" / "rime-frost" / "cn_dicts_cell",
    ]


def scale_line(line: str, multiplier: int) -> str:
    """If line looks like a dict entry with trailing integer weight, scale it."""
    if line.startswith("#") or not line.strip():
        return line
    stripped = line.rstrip("\r\n")
    ending = line[len(stripped) :]
    parts = stripped.split("\t")
    if len(parts) < 3:
        return line
    tail = parts[-1].strip()
    if not tail.lstrip("-").isdigit():
        return line
    try:
        w = int(tail)
    except ValueError:
        return line
    parts[-1] = str(w * multiplier)
    return "\t".join(parts) + ending


def process_file(path: Path, multiplier: int, dry_run: bool, backup: bool) -> tuple[int, int]:
    """Returns (lines_changed, bytes_written_or_would_write)."""
    changed = 0
    out_chunks: list[str] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        for line in f:
            new_line = scale_line(line, multiplier)
            if new_line != line:
                changed += 1
            out_chunks.append(new_line)
    text = "".join(out_chunks)
    if dry_run:
        return changed, len(text.encode("utf-8"))
    if backup:
        bak = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, bak)
    path.write_text(text, encoding="utf-8", newline="")
    return changed, len(text.encode("utf-8"))


def main() -> int:
    root = repo_root()
    p = argparse.ArgumentParser(description="Multiply Rime dict YAML weights by a constant.")
    p.add_argument(
        "--multiplier",
        type=int,
        default=DEFAULT_MULTIPLIER,
        help=f"Integer factor for weights (default: {DEFAULT_MULTIPLIER})",
    )
    p.add_argument(
        "--dirs",
        type=Path,
        nargs="*",
        default=None,
        help="Directories to scan (default: rime-frost cn_dicts + cn_dicts_cell under repo root)",
    )
    p.add_argument("--dry-run", action="store_true", help="Do not write files; print summary only")
    p.add_argument(
        "--backup",
        action="store_true",
        help="Before overwrite, copy each file to same name with .bak suffix",
    )
    p.add_argument(
        "--glob",
        default="*.yaml",
        help="Filename glob per directory (default: *.yaml)",
    )
    args = p.parse_args()

    dirs = [Path(d).resolve() for d in args.dirs] if args.dirs else default_target_dirs(root)
    mult = args.multiplier
    if mult <= 0:
        print("multiplier must be positive", file=sys.stderr)
        return 2

    files: list[Path] = []
    for d in dirs:
        if not d.is_dir():
            print(f"[skip] not a directory: {d}", file=sys.stderr)
            continue
        files.extend(sorted(d.glob(args.glob)))

    if not files:
        print("No files matched.", file=sys.stderr)
        return 1

    total_changed = 0
    for fp in files:
        n, _ = process_file(fp, mult, dry_run=args.dry_run, backup=args.backup and not args.dry_run)
        total_changed += n
        print(f"{'[dry-run] ' if args.dry_run else ''}{fp}: scaled {n} lines")

    print(f"Done. multiplier={mult} files={len(files)} lines_touched={total_changed}")
    if args.dry_run:
        print("Re-run without --dry-run to apply; add --backup to keep .bak copies.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
