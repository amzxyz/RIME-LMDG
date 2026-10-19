"""Paths and defaults for Rime DLL and vendor distributions."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


# Rime `shared_data_dir`: program-wide read-only config/dicts (repo-local).
SHARED_DATA_REL = "vendor/data"


def shared_data_dir(root: Optional[Path] = None) -> Path:
    base = root or repo_root()
    return (base / SHARED_DATA_REL).resolve()


@dataclass(frozen=True)
class VendorConfig:
    """One Rime distribution checkout (git submodule path)."""

    key: str
    rel_path: str
    schema_id: str
    input_mode: str = "pinyin"
    input_dict_rel_path: Optional[str] = None
    input_code_prefix_len: int = 2

    def data_dir(self, root: Optional[Path] = None) -> Path:
        base = root or repo_root()
        return (base / self.rel_path).resolve()

    def input_dict_path(self, root: Optional[Path] = None) -> Optional[Path]:
        if not self.input_dict_rel_path:
            return None
        base = root or repo_root()
        return (base / self.rel_path / self.input_dict_rel_path).resolve()


# Default schema ids match each distro's primary benchmark schema.
DEFAULT_VENDORS: List[VendorConfig] = [
    VendorConfig("rime_frost", "vendor/rime-frost", "rime_frost"),
    VendorConfig("rime_frost_with_gram", "vendor/rime-frost_with_gram", "rime_frost"),
    VendorConfig("wanxiang", "vendor/rime_wanxiang", "wanxiang"),
    VendorConfig("rime_wanxiang_with_gram", "vendor/rime_wanxiang_with_gram", "wanxiang"),
]


def _append_unique_file(paths: List[Path], candidate: Path) -> None:
    if candidate.is_file() and candidate not in paths:
        paths.append(candidate)


def default_rime_dll_candidates() -> List[Path]:
    """Prefer repo-local shared libraries, then common Weasel install locations."""
    out: List[Path] = []
    root = repo_root()

    # Repo-local copies are the most reproducible across platforms.
    if sys.platform == "darwin":
        for pattern in ("librime*.dylib",):
            for candidate in sorted(root.glob(pattern)):
                _append_unique_file(out, candidate)
            for candidate in sorted((root / "lib").glob(pattern)):
                _append_unique_file(out, candidate)
        return out

    if sys.platform.startswith("linux"):
        for pattern in ("librime.so", "librime.so.*", "librime*.so", "librime*.so.*"):
            for candidate in sorted(root.glob(pattern)):
                _append_unique_file(out, candidate)
            for candidate in sorted((root / "lib").glob(pattern)):
                _append_unique_file(out, candidate)
        return out

    for candidate in (
        root / "rime.dll",
        root / "lib" / "rime.dll",
    ):
        _append_unique_file(out, candidate)

    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    roots = [Path(program_files), Path(program_files_x86)]
    for root in roots:
        weasel = root / "Rime"
        if weasel.is_dir():
            for sub in weasel.glob("weasel-*"):
                dll = sub / "rime.dll"
                if dll.is_file():
                    out.append(dll)
        dll_flat = root / "Rime" / "rime.dll"
        if dll_flat.is_file():
            out.append(dll_flat)
    return out


def resolve_rime_dll(explicit: Optional[str] = None) -> Path:
    if explicit:
        p = Path(explicit)
        if p.is_file():
            return p.resolve()
        raise FileNotFoundError(f"Rime library path is not a file: {explicit}")
    for env_var in ("RIME_LIBRARY", "RIME_DLL"):
        env = os.environ.get(env_var, "").strip()
        if env:
            return resolve_rime_dll(env)
    for c in default_rime_dll_candidates():
        if c.is_file():
            return c.resolve()
    raise FileNotFoundError(
        "Could not find a Rime shared library. Set RIME_LIBRARY or RIME_DLL to the full path "
        "(for example `rime.dll` on Windows, `librime*.dylib` on macOS, "
        "or `librime.so*` on Linux)."
    )
