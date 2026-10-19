#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Time decode with one Rime session: begin_decode_batch → repeat feed+get_context → end_decode_batch.

Compares per-sentence cost vs one-shot decode_input (new session each time).

Usage (repo root):
  $env:PYTHONUTF8='1'
  python scripts/benchmark_one_sentence.py --vendor rime_frost \\
    --input "xinxingchanyedefazhan" --repeat 30
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from rime_schema_compare.config import DEFAULT_VENDORS, VendorConfig, resolve_rime_dll
from rime_schema_compare.rime_runner import RimeDistroRunner


def pick_vendor(key: str) -> VendorConfig:
    k = key.strip().lower()
    for v in DEFAULT_VENDORS:
        if v.key.lower() == k:
            return v
    raise SystemExit(f"Unknown vendor {key!r}. Known: {[x.key for x in DEFAULT_VENDORS]}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--vendor", default="rime_frost", help="Vendor key (see config.DEFAULT_VENDORS)")
    p.add_argument("--input", default="", help="Raw input string fed to Rime")
    p.add_argument("--pinyin", default="", help="Backward-compatible alias of --input")
    p.add_argument("--repeat", type=int, default=30, help="Iterations of feed+get_context on same session")
    p.add_argument("--rime-dll", default="", help="Override rime.dll path")
    args = p.parse_args()
    raw_input = args.input or args.pinyin
    if not raw_input:
        raise SystemExit("Need --input (or legacy --pinyin)")

    dll = resolve_rime_dll(args.rime_dll or None)
    vendor = pick_vendor(args.vendor)
    runner = RimeDistroRunner(dll)

    try:
        t0 = time.perf_counter()
        runner.switch_distro(vendor)
        load_ms = (time.perf_counter() - t0) * 1000.0

        rime = runner._rime
        schema_id = runner._schema_id or ""
        print(f"dll: {dll}")
        print(f"vendor: {vendor.key} schema={schema_id}")
        print(f"input ({len(raw_input)} chars): {raw_input[:80]}{'…' if len(raw_input) > 80 else ''}")
        print(f"input_feed_mode: {runner.input_feed_mode}")
        print(f"switch_distro (cold): {load_ms:.2f} ms")
        print()

        t_sess0 = time.perf_counter()
        if not runner.begin_decode_batch():
            print("begin_decode_batch failed")
            return 1
        session_open_ms = (time.perf_counter() - t_sess0) * 1000.0
        print(f"begin_decode_batch (create_session + select_schema): {session_open_ms:.2f} ms")
        session_id = runner._batch_session_id
        assert session_id and rime is not None

        labels = ("feed", "get_ctx", "sum_fg")
        rows: list[list[float]] = []

        for i in range(args.repeat):
            parts: list[float] = []
            t = time.perf_counter()
            ok_feed = rime.feed_input(session_id, raw_input)
            parts.append((time.perf_counter() - t) * 1000.0)

            t = time.perf_counter()
            ctx = rime.get_context(session_id)
            parts.append((time.perf_counter() - t) * 1000.0)

            parts.append(parts[0] + parts[1])
            rows.append(parts)

            if not ok_feed:
                print(f"iter {i}: feed_pinyin failed")
            if not ctx:
                print(f"iter {i}: get_context returned None")
            elif i == 0:
                nc = len((ctx.get("candidates") or []))
                top = ((ctx.get("candidates") or [{}])[0].get("text") or "").strip() if nc else ""
                print(f"first iter: candidates={nc} top_candidate[:40]={top[:40]!r}")

        runner.end_decode_batch()

        print(f"--- same session: {args.repeat} × (feed + get_context) (ms) ---")
        for j, name in enumerate(labels):
            col = [r[j] for r in rows]
            print(
                f"{name:10s}  mean={statistics.mean(col):8.3f}  "
                f"min={min(col):8.3f}  max={max(col):8.3f}  "
                f"stdev={statistics.pstdev(col) if len(col) > 1 else 0:.3f}"
            )

        t = time.perf_counter()
        r = runner.decode_input(raw_input)
        one_shot_ms = (time.perf_counter() - t) * 1000.0
        print()
        print(
            f"decode_input() one-shot (new session each call): {one_shot_ms:.3f} ms  "
            f"ok={r.ok} text[:40]={r.prediction[:40]!r}"
        )
        mean_fg = statistics.mean([r[2] for r in rows])
        print()
        print(
            f"Mean feed+get_ctx on reused session ≈ {mean_fg:.3f} ms vs "
            f"one-shot full decode ≈ {one_shot_ms:.3f} ms "
            f"(ratio {one_shot_ms / mean_fg:.1f}×)"
        )
        print(
            "Note: RimeSetInput avoids per-key simulation; librime still composes and builds "
            "the candidate menu for the full string each time."
        )
    finally:
        runner.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
