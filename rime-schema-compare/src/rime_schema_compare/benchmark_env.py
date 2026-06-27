"""Prepare vendor user_data_dir before librime benchmark: no user dict, patch schema."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any, Dict, List

import yaml

logger = logging.getLogger(__name__)

PATCH_TRANSLATOR_DISABLE_USER_DICT = "translator/enable_user_dict"
PATCH_BODY: Dict[str, Any] = {"patch": {PATCH_TRANSLATOR_DISABLE_USER_DICT: False}}


def remove_all_userdbs(user_dir: Path) -> List[Path]:
    """Remove directories (and any files) named *.userdb under user_dir."""
    removed: List[Path] = []
    if not user_dir.is_dir():
        return removed
    # LevelDB-style folders: foo.userdb/
    dirs = sorted(
        (p for p in user_dir.rglob("*") if p.is_dir() and p.name.endswith(".userdb")),
        key=lambda p: len(p.parts),
        reverse=True,
    )
    for p in dirs:
        try:
            shutil.rmtree(p)
            removed.append(p)
        except OSError as e:
            logger.warning("[评测环境] 无法删除 userdb 目录 %s: %s", p, e)
    for p in user_dir.rglob("*.userdb"):
        if p.is_file():
            try:
                p.unlink()
                removed.append(p)
            except OSError as e:
                logger.warning("[评测环境] 无法删除 userdb 文件 %s: %s", p, e)
    return removed


def merge_disable_user_dict_patch(custom_yaml: Path) -> None:
    """Create or update {schema_id}.custom.yaml so translator user dict is off."""
    custom_yaml.parent.mkdir(parents=True, exist_ok=True)
    data: Dict[str, Any] = {}
    if custom_yaml.is_file():
        text = custom_yaml.read_text(encoding="utf-8")
        if text.strip():
            loaded = yaml.safe_load(text)
            if isinstance(loaded, dict):
                data = loaded
            elif loaded is not None:
                logger.warning(
                    "[评测环境] %s 根类型非 map，将重写为仅含 patch",
                    custom_yaml,
                )
    patch = data.get("patch")
    if not isinstance(patch, dict):
        patch = {}
    patch[PATCH_TRANSLATOR_DISABLE_USER_DICT] = False
    data["patch"] = patch
    custom_yaml.write_text(
        yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def prepare_vendor_for_benchmark(user_dir: Path, schema_id: str) -> Dict[str, Any]:
    """
    Delete *.userdb under user_dir; ensure ``{schema_id}.custom.yaml`` sets
    ``translator/enable_user_dict: false``.
    """
    removed = remove_all_userdbs(user_dir)
    custom_path = user_dir / f"{schema_id}.custom.yaml"
    merge_disable_user_dict_patch(custom_path)
    return {
        "userdb_paths_removed": [str(p) for p in removed],
        "custom_yaml": str(custom_path.resolve()),
    }
