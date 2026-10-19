#!/usr/bin/env python3
"""One-shot check: RIME_DLL + first vendor directory + a short input string."""

from __future__ import annotations

import sys
from pathlib import Path

if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from rime_schema_compare.config import DEFAULT_VENDORS, resolve_rime_dll
from rime_schema_compare.rime_runner import RimeDistroRunner


def main() -> None:
    dll = resolve_rime_dll()
    v = DEFAULT_VENDORS[0]
    runner = RimeDistroRunner(dll)
    try:
        runner.switch_distro(v)
        print("input_feed_mode:", runner.input_feed_mode)
        r = runner.decode_input("ceshi")
        print("dll:", dll)
        print("vendor:", v.key, v.schema_id)
        print("decode 'ceshi':", r)
    finally:
        runner.close()


if __name__ == "__main__":
    main()
