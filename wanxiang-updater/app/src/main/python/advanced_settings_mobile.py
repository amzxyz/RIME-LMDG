"""Metadata-driven advanced settings bridge used by the Android UI.

The Android screen deliberately does not edit YAML as plain text. This module
uses the same RimeYamlEngine, FILE_INDEX_META and SCHEMA_META_CONFIG as the
desktop tool, including custom patch/direct write modes and atomic validation.
"""
from __future__ import annotations
import copy
import json
from pathlib import Path
from typing import Any
from ruamel.yaml import YAML
from advanced_settings.core import RimeYamlEngine, RimeYamlError, is_managed_source_yaml
from advanced_settings.metadata import FILE_INDEX_META, SCHEMA_META_CONFIG, sort_algebra_patch_items


def _json_value(value: Any):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _json_value(v) for k, v in value.items()}
    return str(value)


def _match(meta: dict, file_name: str) -> bool:
    name = file_name.lower()
    if str(meta.get("_match_file", "")).lower() == name:
        return True
    return name in {str(x).lower() for x in meta.get("_match_files", [])}


def _source_path(root: Path, file_name: str) -> Path:
    path = (root / file_name).resolve()
    if path.parent != root.resolve():
        raise ValueError("非法配置路径")
    return path


def _custom_path(root: Path, file_name: str) -> Path:
    if file_name == "default.yaml":
        return root / "default.custom.yaml"
    if file_name.endswith(".schema.yaml"):
        return root / (file_name[:-len(".schema.yaml")] + ".custom.yaml")
    return root / (file_name[:-len(".yaml")] + ".custom.yaml")


def _nodes_for(file_name: str):
    result = []
    for key, meta in SCHEMA_META_CONFIG.items():
        if not _match(meta, file_name):
            continue
        root_key = str(meta.get("_root_key", "")).strip("/")
        for path, node in (meta.get("nodes") or {}).items():
            child = "" if str(path).strip("/") == "__self__" else str(path).strip("/")
            full = "/".join(x for x in (root_key, child) if x)
            result.append({
                "section": key,
                "sectionTitle": str(meta.get("_title", key)),
                "sectionDesc": str(meta.get("_desc", "")),
                "path": full,
                "title": str(node.get("title", path)),
                "desc": str(node.get("desc", "")),
                "type": str(node.get("type", "str")),
                "baseline": str(node.get("baseline", "effective")),
                "options": _json_value(node.get("options", node.get("choices", []))),
            })
    return result


def scan_sections(root_path: str) -> str:
    root = Path(root_path).expanduser().resolve()
    sections = []
    for group, files in FILE_INDEX_META.items():
        for item in files:
            name = str(item.get("file", ""))
            path = root / name
            if not path.is_file():
                continue
            sections.append({
                "group": str(group),
                "file": name,
                "name": str(item.get("name", name)),
                "sections": [
                    {"key": n["section"], "title": n["sectionTitle"], "desc": n["sectionDesc"]}
                    for n in _nodes_for(name)
                ],
            })
    return json.dumps(sections, ensure_ascii=False)


def _load(file_name: str, root: Path):
    schema = _source_path(root, file_name)
    custom = _custom_path(root, file_name)
    engine = RimeYamlEngine()
    doc = engine.load_pair(str(schema), str(custom) if custom.exists() else "")
    return engine, doc


def load_form(root_path: str, file_name: str, section: str = "") -> str:
    root = Path(root_path).expanduser().resolve()
    engine, doc = _load(file_name, root)
    rows = []
    for node in _nodes_for(file_name):
        if section and node["section"] != section:
            continue
        base = doc.source_effective if node["baseline"] == "source_effective" else doc.effective
        value = engine.get_path(base, node["path"], None)
        if node["type"] in ("list_text", "dynamic_list", "algebra_patch", "multiline_str"):
            if isinstance(value, list):
                shown = "\n".join(str(x) for x in value)
            elif isinstance(value, dict):
                shown = json.dumps(_json_value(value), ensure_ascii=False, indent=2)
            else:
                shown = "" if value is None else str(value)
        else:
            shown = value
        item = dict(node)
        item["value"] = _json_value(shown)
        item["rawValue"] = _json_value(value)
        rows.append(item)
    return json.dumps({"file": file_name, "section": section, "fields": rows}, ensure_ascii=False)


def _coerce(node_type: str, value: Any):
    if node_type == "bool":
        if isinstance(value, bool): return value
        return str(value).strip().lower() in ("1", "true", "yes", "on", "是")
    if node_type == "int":
        return int(str(value).strip())
    if node_type == "float":
        return float(str(value).strip())
    if node_type == "number":
        text = str(value).strip()
        return float(text) if "." in text else int(text)
    if node_type in ("list_text", "dynamic_list", "algebra_patch", "dynamic_block_list"):
        if isinstance(value, list): return value
        text = str(value).strip()
        if text.startswith("["):
            try: return json.loads(text)
            except Exception: pass
        return [x.strip() for x in text.splitlines() if x.strip()]
    if node_type == "dynamic_kv_list":
        if isinstance(value, dict): return value
        text = str(value).strip()
        if text.startswith("{"):
            try: return json.loads(text)
            except Exception: pass
        result = {}
        for line in text.splitlines():
            if ":" in line:
                key, item = line.split(":", 1)
            elif "=" in line:
                key, item = line.split("=", 1)
            else:
                continue
            result[key.strip()] = item.strip()
        return result
    if node_type == "raw_yaml":
        text = str(value)
        try: return YAML(typ="safe").load(text)
        except Exception: return text
    return "" if value is None else str(value)


def save_form(root_path: str, file_name: str, section: str, direct_mode: bool, updates_json: str) -> str:
    root = Path(root_path).expanduser().resolve()
    engine, doc = _load(file_name, root)
    updates = json.loads(updates_json or "{}")
    nodes = {n["path"]: n for n in _nodes_for(file_name) if not section or n["section"] == section}
    changed = []
    # wanxiang_algebra.yaml 没有独立 custom 登记，桌面工具也只允许直写。
    direct_mode = bool(direct_mode or (file_name != "default.yaml" and not file_name.endswith(".schema.yaml")))
    if direct_mode:
        data = copy.deepcopy(doc.schema)
        for path, value in updates.items():
            node = nodes.get(path)
            if not node: continue
            value = _coerce(node["type"], value)
            if node["type"] == "algebra_patch":
                original = engine.get_path(data, path, [])
                value = sort_algebra_patch_items(value, original)
            engine.set_path(data, path, value)
        engine.validate_data(data)
        target = Path(doc.schema_path)
        engine.atomic_write_many({target: data})
        changed.append(target.name)
    else:
        custom = copy.deepcopy(engine.load_file(doc.custom_path, default={}) if doc.custom_path and Path(doc.custom_path).exists() else {})
        patch = custom.get("patch") if isinstance(custom, dict) else None
        if not isinstance(patch, dict): patch = {}
        original_patch = copy.deepcopy(patch)
        for path, value in updates.items():
            node = nodes.get(path)
            if not node: continue
            value = _coerce(node["type"], value)
            if node["type"] == "algebra_patch":
                original = engine.get_path(doc.source_effective, path, [])
                value = sort_algebra_patch_items(value, original)
            engine.set_path(patch, path, value)
        custom["patch"] = patch
        engine.validate_data(custom)
        target = Path(doc.custom_path)
        if patch == original_patch and target.exists():
            return json.dumps({"changed": [], "message": "没有变化"}, ensure_ascii=False)
        engine.atomic_write_many({target: custom})
        changed.append(target.name)
    return json.dumps({"changed": changed, "message": "保存成功"}, ensure_ascii=False)
