"""Metadata-driven advanced settings bridge for the Android UI.

The module intentionally keeps the desktop YAML semantics: lists preserve their
actual YAML type, custom files use Rime's literal patch keys, and direct/patch
writes are validated atomically. It also exposes the desktop tool's common
cross-file settings page and schema-list checkbox model.
"""
from __future__ import annotations
import copy
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Mapping
from ruamel.yaml import YAML
from advanced_settings.core import RimeYamlEngine
# Import the metadata module as a whole rather than importing every newer
# constant by name. This keeps the mobile bridge loadable when an APK or a
# user's checkout contains an older metadata.py alongside the newer bridge.
# The desktop metadata remains authoritative whenever a symbol is present.
from advanced_settings import metadata as _metadata

FILE_INDEX_META = _metadata.FILE_INDEX_META
SCHEMA_META_CONFIG = _metadata.SCHEMA_META_CONFIG
sort_algebra_patch_items = _metadata.sort_algebra_patch_items
ALGEBRA_SCHEME_NAMES = tuple(getattr(_metadata, "ALGEBRA_SCHEME_NAMES", (
    "全拼", "自然码", "小鹤双拼", "微软双拼", "搜狗双拼", "智能ABC", "紫光双拼",
    "拼音加加", "国标双拼", "自然龙", "汉心龙", "蓝天双拼", "乱序17", "大牛双拼", "首道双拼",
)))
ALGEBRA_AUX_NAMES = tuple(getattr(_metadata, "ALGEBRA_AUX_NAMES", ("直接辅助", "间接辅助")))
ALGEBRA_TIQUAN_SCHEMES = tuple(getattr(_metadata, "ALGEBRA_TIQUAN_SCHEMES", ("自然码", "小鹤双拼")))
ALGEBRA_FUZZY_NAMES = tuple(getattr(_metadata, "ALGEBRA_FUZZY_NAMES", (
    ("n / l", "wanxiang_algebra:/模糊音_nl"),
    ("r / y", "wanxiang_algebra:/模糊音_ry"),
    ("h / f", "wanxiang_algebra:/模糊音_hf"),
    ("r / l", "wanxiang_algebra:/模糊音_rl"),
    ("k / g", "wanxiang_algebra:/模糊音_kg"),
    ("en / eng", "wanxiang_algebra:/模糊音_en_eng"),
    ("in / ing", "wanxiang_algebra:/模糊音_in_ing"),
    ("c / ch", "wanxiang_algebra:/模糊音_c_ch"),
    ("z / zh", "wanxiang_algebra:/模糊音_z_zh"),
    ("s / sh", "wanxiang_algebra:/模糊音_s_sh"),
)))
ALGEBRA_VARIANT_BY_FILE = dict(getattr(_metadata, "ALGEBRA_VARIANT_BY_FILE", {
    "wanxiang.schema.yaml": "base", "wanxiang_pro.schema.yaml": "pro", "wanxiang_lite.schema.yaml": "lite",
}))
REVERSE_PINYIN_SCHEMES = tuple(getattr(_metadata, "REVERSE_PINYIN_SCHEMES", (
    "全拼", "自然码", "小鹤双拼", "微软双拼", "搜狗双拼", "智能ABC", "紫光双拼", "拼音加加",
)))
REVERSE_STROKE_SCHEMES = tuple(getattr(_metadata, "REVERSE_STROKE_SCHEMES", (
    ("hspzn", "hspzn (横竖撇捺折默认)"), ("hupvd", "hupvd (双拼专用)"), ("hslzy", "hslzy (乱序17)"),
)))
ENGLISH_ALGEBRA_SCHEMES = tuple(getattr(_metadata, "ENGLISH_ALGEBRA_SCHEMES", (
    "全拼", "自然码", "小鹤双拼", "微软双拼", "搜狗双拼", "智能ABC", "紫光双拼", "拼音加加", "自然龙", "汉心龙",
)))
MIXED_ALGEBRA_SCHEMES = tuple(getattr(_metadata, "MIXED_ALGEBRA_SCHEMES", ENGLISH_ALGEBRA_SCHEMES))

_MISSING = object()
_MAIN_SCHEMES = (
    ("base", "wanxiang.schema.yaml", "wanxiang"),
    ("lite", "wanxiang_lite.schema.yaml", "wanxiang_lite"),
    ("pro", "wanxiang_pro.schema.yaml", "wanxiang_pro"),
)
_SCHEMA_ALLOWLIST = ("wanxiang", "wanxiang_pro", "wanxiang_english", "wanxiang_t9")
_SCHEME_IDS = ("base", "lite", "pro")
_SAFE_YAML = YAML(typ="safe")


def _json_value(value: Any):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _json_value(v) for k, v in value.items()}
    return str(value)


def _same_value(left: Any, right: Any) -> bool:
    """Compare YAML values without conflating bool/int or list/map types."""
    if left is _MISSING or right is _MISSING:
        return left is right
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left is right
    if isinstance(left, Mapping) or isinstance(right, Mapping):
        if not isinstance(left, Mapping) or not isinstance(right, Mapping):
            return False
        if set(map(str, left.keys())) != set(map(str, right.keys())):
            return False
        right_by_key = {str(k): v for k, v in right.items()}
        return all(_same_value(v, right_by_key[str(k)]) for k, v in left.items())
    if isinstance(left, (list, tuple)) or isinstance(right, (list, tuple)):
        if not isinstance(left, (list, tuple)) or not isinstance(right, (list, tuple)):
            return False
        return len(left) == len(right) and all(_same_value(a, b) for a, b in zip(left, right))
    if isinstance(left, int) or isinstance(right, int):
        return isinstance(left, int) and not isinstance(left, bool) and isinstance(right, int) and not isinstance(right, bool) and left == right
    if isinstance(left, float) or isinstance(right, float):
        return isinstance(left, float) and isinstance(right, float) and float(left) == float(right)
    if isinstance(left, str) or isinstance(right, str):
        return isinstance(left, str) and isinstance(right, str) and str(left) == str(right)
    return type(left) is type(right) and left == right


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


def _has_managed_custom(file_name: str) -> bool:
    return file_name == "default.yaml" or file_name.endswith(".schema.yaml")


def _editor_config(node_type: str) -> dict:
    """Options for desktop's dedicated algebra editors, shared with Android."""
    if node_type == "algebra_patch":
        return {
            "schemes": list(ALGEBRA_SCHEME_NAMES),
            "aux": list(ALGEBRA_AUX_NAMES),
            "tiquan": list(ALGEBRA_TIQUAN_SCHEMES),
            "fuzzy": [{"label": label, "path": path} for label, path in ALGEBRA_FUZZY_NAMES],
        }
    if node_type == "reverse_algebra":
        return {
            "pinyinSchemes": list(REVERSE_PINYIN_SCHEMES),
            "strokeSchemes": [{"id": key, "label": label} for key, label in REVERSE_STROKE_SCHEMES],
        }
    if node_type == "english_algebra":
        return {"schemes": list(ENGLISH_ALGEBRA_SCHEMES)}
    if node_type == "mixed_algebra":
        return {"schemes": list(MIXED_ALGEBRA_SCHEMES)}
    return {}


def _nodes_for(file_name: str, schema_data: Any = None, effective_data: Any = None, direct_mode: bool = False):
    """Resolve visible fields using the same matching rules as the desktop UI.

    Explicit _match_file(s) entries are always available for that file. Metadata
    without an explicit matcher (engine, translator, key_binder, etc.) is shown
    only when its root node exists in the source or literal-patched tree, exactly
    like AdvancedSettingsMixin. wanxiang_algebra.yaml has its own version/module
    hierarchy and therefore needs generated fields instead of schema metadata.
    """
    result = []
    if Path(file_name).name.lower() == "wanxiang_algebra.yaml":
        if not isinstance(schema_data, Mapping):
            return result
        for version, modules in schema_data.items():
            if not isinstance(modules, Mapping):
                continue
            section = f"algebra::{version}"
            for module, rules in modules.items():
                simple_list = isinstance(rules, list) and all(isinstance(item, str) for item in rules)
                node_type = "dynamic_list" if simple_list else "raw_yaml"
                count_desc = f"当前 {len(rules)} 条规则；按列表顺序执行。" if isinstance(rules, list) else "该模块为 YAML 结构，保存时保留其列表/映射类型。"
                result.append({
                    "section": section,
                    "sectionTitle": f"📁 {version}",
                    "sectionDesc": "拼写运算规则版本；选择版本后逐模块编辑。",
                    "path": f"{version}/{module}",
                    "title": f"📝 {module}",
                    "desc": count_desc,
                    "type": node_type,
                    "baseline": "source_effective",
                    "options": [],
                    "template": None,
                    "presetKeys": None,
                    "actionButton": "",
                    "variant": "",
                    "editorConfig": {},
                })
        return result

    for key, meta in SCHEMA_META_CONFIG.items():
        explicit_match = bool(meta.get("_match_file") or meta.get("_match_files"))
        if explicit_match:
            if not _match(meta, file_name):
                continue
        else:
            root_key = str(meta.get("_root_key", key)).strip("/")
            in_schema = isinstance(schema_data, Mapping) and root_key in schema_data
            in_effective = not direct_mode and isinstance(effective_data, Mapping) and root_key in effective_data
            if not (in_schema or in_effective):
                continue
        root_key = str(meta.get("_root_key", key)).strip("/")
        for path, node in (meta.get("nodes") or {}).items():
            child = "" if str(path).strip("/") == "__self__" else str(path).strip("/")
            full = "/".join(x for x in (root_key, child) if x)
            node_type = str(node.get("type", "str"))
            result.append({
                "section": key,
                "sectionTitle": str(meta.get("_title", key)),
                "sectionDesc": str(meta.get("_desc", "")),
                "path": full,
                "title": str(node.get("title", path)),
                "desc": str(node.get("desc", "")),
                "type": node_type,
                "baseline": str(node.get("baseline", "effective")),
                "options": _json_value(node.get("options", node.get("choices", []))),
                "template": _json_value(node.get("template")),
                "presetKeys": _json_value(node.get("preset_keys")),
                "actionButton": str(node.get("action_btn", "")),
                "variant": ALGEBRA_VARIANT_BY_FILE.get(Path(file_name).name, ""),
                "editorConfig": _editor_config(node_type),
            })
    return result


def _schema_choices(root: Path, current_value: Any):
    active = set()
    if isinstance(current_value, list):
        for item in current_value:
            if isinstance(item, Mapping) and item.get("schema"):
                active.add(str(item["schema"]))
    choices = []
    for schema_id in _SCHEMA_ALLOWLIST:
        path = root / f"{schema_id}.schema.yaml"
        if not path.is_file():
            continue
        label = schema_id
        try:
            data = _SAFE_YAML.load(path.read_text(encoding="utf-8")) or {}
            label = str((data.get("schema") or {}).get("name") or schema_id)
        except Exception:
            pass
        choices.append({"id": schema_id, "label": label, "checked": schema_id in active})
    return choices

def _scheme_choices(root: Path, usage_path: str, current_name: str, docs=None, engine=None, direct_mode=False):
    """Build scheme choices using a shared document cache and current edit mode."""
    docs = docs if docs is not None else {}
    engine = engine or RimeYamlEngine()
    choices = []
    for sid, file_name, _ in _MAIN_SCHEMES:
        if not (root / file_name).is_file():
            continue
        if file_name not in docs:
            docs[file_name] = _load(file_name, root)[1]
        doc = docs[file_name]
        view = doc.schema if direct_mode else doc.effective
        label = str(engine.get_path(view, "schema/name", sid.title()))
        active = str(engine.get_path(view, usage_path, "")) == str(current_name)
        choices.append({"id": sid, "label": label, "checked": active})
    return choices

def _binding_state(bindings):
    paging = "默认 (PageUp/Dn)"
    cand2 = ""
    cand3 = ""
    for item in bindings if isinstance(bindings, list) else []:
        if not isinstance(item, Mapping):
            continue
        accept = str(item.get("accept", "")).lower()
        send = str(item.get("send", "")).lower()
        if send in ("page_up", "page_down", "prior", "next"):
            if accept in ("minus", "equal", "-", "="): paging = "减号等号 ( - = )"
            elif accept in ("bracketleft", "bracketright", "[", "]"): paging = "中括号 ( [ ] )"
            elif accept in ("comma", "period", ",", "."): paging = "逗号句号 ( , . )"
        if send == "2" and accept not in ("2", "kp_2"): cand2 = accept
        if send == "3" and accept not in ("3", "kp_3"): cand3 = accept
    return paging, cand2, cand3


def scan_sections(root_path: str) -> str:
    root = Path(root_path).expanduser().resolve()
    sections = []
    engine = RimeYamlEngine()
    for group, files in FILE_INDEX_META.items():
        for item in files:
            name = str(item.get("file", ""))
            source_path = root / name
            if not source_path.is_file():
                continue
            try:
                custom_path = _custom_path(root, name) if _has_managed_custom(name) else None
                document = engine.load_pair(
                    str(source_path),
                    str(custom_path) if custom_path is not None else "",
                    reuse_compile_session=True,
                )
                nodes = _nodes_for(name, document.schema, document.effective)
            except Exception:
                # Keep a broken-but-registered file visible; the editor will
                # report the actual parse/compile error when opened.
                try:
                    schema = engine.load_file(str(source_path), default={})
                    custom_path = _custom_path(root, name) if _has_managed_custom(name) else None
                    custom = engine.load_file(str(custom_path), default={}) if custom_path and custom_path.is_file() else {}
                    patch = custom.get("patch", {}) if isinstance(custom, Mapping) else {}
                    effective = engine.apply_patch(schema, patch if isinstance(patch, Mapping) else {})
                    nodes = _nodes_for(name, schema, effective)
                except Exception:
                    nodes = _nodes_for(name, {}, {})
            seen_sections = {}
            for node in nodes:
                identity = (node["section"], node["sectionTitle"])
                seen_sections.setdefault(identity, node["sectionDesc"])
            sections.append({
                "group": str(group),
                "file": name,
                "name": str(item.get("name", name)),
                "sections": [
                    {"key": key, "title": title, "desc": desc}
                    for (key, title), desc in seen_sections.items()
                ],
            })
    return json.dumps(sections, ensure_ascii=False)


def _load(file_name: str, root: Path):
    schema = _source_path(root, file_name)
    custom = _custom_path(root, file_name) if _has_managed_custom(file_name) else None
    engine = RimeYamlEngine()
    # Keep the derived custom path even before the file exists; save operations
    # must be able to create a first-time *.custom.yaml patch file.
    doc = engine.load_pair(str(schema), str(custom) if custom is not None else "")
    return engine, doc


def _load_light(file_name: str, root: Path):
    """Load only raw YAML plus literal custom patch for common settings.

    The full Rime compiler is needed by ordinary schema pages, but common
    settings read direct paths and do not need include/reference expansion.
    Avoiding that compiler is what keeps the mobile startup responsive.
    """
    schema_path = _source_path(root, file_name)
    custom_path = _custom_path(root, file_name)
    engine = RimeYamlEngine()
    schema = engine.load_file(str(schema_path), default={})
    custom = engine.load_file(str(custom_path), default={}) if custom_path.exists() else {}
    patch = custom.get("patch", {}) if isinstance(custom, Mapping) else {}
    patch = patch if isinstance(patch, Mapping) else {}
    source_effective = engine.apply_patch(schema, patch)
    from types import SimpleNamespace
    return SimpleNamespace(
        file_name=file_name,
        schema_path=str(schema_path),
        custom_path=str(custom_path),
        schema=schema,
        patch=patch,
        source_effective=source_effective,
        effective=source_effective,
    )


def _show_value(value: Any, node_type: str) -> str:
    if node_type in ("schema_checkboxes", "scheme_checkboxes"):
        return ""
    if isinstance(value, list):
        if any(isinstance(x, (dict, list)) for x in value):
            return json.dumps(_json_value(value), ensure_ascii=False, indent=2)
        return "\n".join(str(x) for x in value)
    if isinstance(value, dict):
        return json.dumps(_json_value(value), ensure_ascii=False, indent=2)
    return "" if value is None else str(value)


def load_form(root_path: str, file_name: str, section: str = "", direct_mode: bool = False) -> str:
    root = Path(root_path).expanduser().resolve()
    engine, doc = _load(file_name, root)
    # Files without a corresponding Rime custom file are always edited directly.
    direct_mode = bool(direct_mode or (file_name != "default.yaml" and not file_name.endswith(".schema.yaml")))
    rows = []
    for node in _nodes_for(file_name, doc.schema, doc.effective, direct_mode):
        if section and node["section"] != section:
            continue
        if direct_mode:
            base = doc.schema
        else:
            base = doc.source_effective if node["baseline"] == "source_effective" else doc.effective
        value = engine.get_path(base, node["path"], None)
        item = dict(node)
        item["value"] = _show_value(value, node["type"])
        item["rawValue"] = _json_value(value)
        item["valueShape"] = "list" if isinstance(value, list) else "dict" if isinstance(value, Mapping) else "scalar"
        item["editorConfig"] = _json_value(node.get("editorConfig", {}))
        if node["type"] == "schema_checkboxes":
            item["choices"] = _schema_choices(root, value)
        rows.append(item)
    return json.dumps({"file": file_name, "section": section, "directMode": direct_mode, "fields": rows}, ensure_ascii=False)

def _parse_list_text(text: Any, original: Any, key_name: str = ""):
    if isinstance(text, list):
        return text
    raw = str(text if text is not None else "").strip()
    force_array = isinstance(original, list) or "format" in key_name or "rules" in key_name
    if not raw:
        return [] if force_array else None
    if raw.startswith("[") and raw.endswith("]"):
        try:
            parsed = _SAFE_YAML.load(raw)
            return parsed if isinstance(parsed, list) else [parsed]
        except Exception:
            return [raw]
    if "\n" in raw:
        return [line.strip() for line in raw.splitlines() if line.strip()]
    if "," in raw or "，" in raw:
        return [item.strip() for item in raw.replace("，", ",").split(",") if item.strip()]
    if force_array:
        return [raw]
    try:
        return _SAFE_YAML.load(raw)
    except Exception:
        return raw


def _coerce(node: Mapping[str, Any], value: Any, original: Any):
    node_type = node["type"]
    if node_type == "bool":
        if isinstance(value, bool): return value
        return str(value).strip().lower() in ("1", "true", "yes", "on", "是")
    if node_type == "int": return int(str(value).strip())
    if node_type == "float": return float(str(value).strip())
    if node_type == "number":
        text = str(value).strip()
        parsed = _SAFE_YAML.load(text)
        if isinstance(parsed, bool) or not isinstance(parsed, (int, float)):
            raise ValueError("请输入有效数字")
        return parsed
    if node_type in ("schema_checkboxes", "scheme_checkboxes"):
        if isinstance(value, list): ids = value
        else:
            text = str(value or "").strip()
            try: ids = json.loads(text) if text else []
            except Exception: ids = [x.strip() for x in text.splitlines() if x.strip()]
        normalized = []
        for item in ids:
            schema_id = item.get("schema") if isinstance(item, Mapping) else str(item)
            allowed = _SCHEMA_ALLOWLIST if node_type == "schema_checkboxes" else _SCHEME_IDS
            if schema_id in allowed and not any(x.get("schema") == schema_id for x in normalized):
                normalized.append({"schema": schema_id})
        if node_type == "schema_checkboxes" and not normalized:
            raise ValueError("至少需要保留一个启用方案")
        return normalized
    if node_type == "list_text":
        return _parse_list_text(value, original, str(node.get("path", "")).split("/")[-1])
    if node_type in ("reverse_algebra", "english_algebra", "mixed_algebra"):
        # Desktop's dedicated algebra widgets emit a mapping containing the
        # literal __include/__patch compiler directives.  Treating these three
        # fields as generic lists corrupted the YAML shape on Android.
        if isinstance(value, Mapping):
            return dict(value)
        text = str(value or "").strip()
        if not text:
            return {}
        try:
            parsed = _SAFE_YAML.load(text)
        except Exception as error:
            raise ValueError(f"拼写挂载项不是有效 YAML/JSON：{error}") from error
        if isinstance(parsed, Mapping):
            return dict(parsed)
        # Keep reading older serialized forms, but normalize them to the same
        # mapping shape produced by the desktop editor whenever possible.
        if isinstance(parsed, list):
            mapping = next((x for x in parsed if isinstance(x, Mapping) and ("__include" in x or "__patch" in x)), None)
            if mapping is not None:
                return dict(mapping)
        raise ValueError("该字段需要包含 __include / __patch 的 YAML/JSON 映射")
    if node_type in ("dynamic_list", "algebra_patch", "dynamic_block_list"):
        if isinstance(value, list): return value
        text = str(value or "").strip()
        if not text: return []
        # JSON is valid YAML; also accept YAML block lists for complex rule blocks.
        if text.startswith(("[", "- ", "-\n", "{")):
            try:
                parsed = _SAFE_YAML.load(text)
            except Exception as error:
                raise ValueError(f"列表不是有效 YAML/JSON：{error}") from error
            if isinstance(parsed, list):
                if node_type == "dynamic_block_list" and any(not isinstance(x, Mapping) for x in parsed):
                    raise ValueError("规则块的每个元素必须是映射对象")
                return parsed
            if node_type == "dynamic_block_list" and isinstance(parsed, Mapping):
                return [dict(parsed)]
            raise ValueError("该字段要求 YAML/JSON 列表")
        if node_type == "dynamic_block_list":
            raise ValueError("规则块需要 YAML/JSON 列表，每项必须是映射对象")
        return [x.strip() for x in text.splitlines() if x.strip()]
    if node_type == "dynamic_kv_list":
        if isinstance(value, dict): return value
        text = str(value or "").strip()
        if not text: return {}
        if text.startswith("{"):
            try:
                parsed = _SAFE_YAML.load(text)
                if isinstance(parsed, Mapping): return dict(parsed)
            except Exception: pass
        result = {}
        preset_keys = node.get("presetKeys") or node.get("preset_keys") or {}
        for line in text.splitlines():
            if ":" in line: key, item = line.split(":", 1)
            elif "=" in line: key, item = line.split("=", 1)
            else: continue
            key = key.strip()
            raw_item = item.strip()
            desc = str(preset_keys.get(key, "")) if isinstance(preset_keys, Mapping) else ""
            if not raw_item:
                continue
            if "(true/false)" in desc.lower():
                parsed_item = raw_item.lower() in ("true", "1", "yes", "on", "是")
            elif "数字" in desc:
                try:
                    parsed_item = int(raw_item)
                except ValueError:
                    try: parsed_item = float(raw_item)
                    except ValueError: parsed_item = raw_item
            elif "填列表" in desc or "数组" in desc:
                parsed_item = _parse_list_text(raw_item, [], key)
            else:
                parsed_item = raw_item
            result[key] = parsed_item
        return result
    if node_type in ("raw_yaml", "dynamic_map"):
        text = str(value or "").strip()
        if not text: return None if node_type == "raw_yaml" else {}
        try:
            parsed = _SAFE_YAML.load(text)
        except Exception:
            if node_type == "dynamic_map": raise ValueError("映射内容不是有效 YAML/JSON")
            return [line.strip() for line in text.splitlines() if line.strip()]
        if node_type == "dynamic_map" and not isinstance(parsed, Mapping):
            raise ValueError("该字段需要 YAML/JSON 映射对象")
        return dict(parsed) if node_type == "dynamic_map" else parsed
    if node_type == "select" and isinstance(original, bool):
        return str(value).strip().lower() in ("1", "true", "yes", "on")
    if node_type == "select" and isinstance(original, int):
        return int(str(value).strip())
    return "" if value is None else str(value)

def _is_empty_value(value: Any) -> bool:
    return value is None or value == "" or (isinstance(value, (list, Mapping)) and len(value) == 0)


def _patch_clean(custom: dict):
    return not custom or (set(custom.keys()) <= {"patch"} and not custom.get("patch"))


def save_form(root_path: str, file_name: str, section: str, direct_mode: bool, updates_json: str) -> str:
    root = Path(root_path).expanduser().resolve()
    updates = json.loads(updates_json or "{}")
    engine, doc = _load(file_name, root)
    direct_mode = bool(direct_mode or (file_name != "default.yaml" and not file_name.endswith(".schema.yaml")))
    nodes = {
        n["path"]: n for n in _nodes_for(file_name, doc.schema, doc.effective, direct_mode)
        if not section or n["section"] == section
    }
    target = Path(doc.schema_path if direct_mode else doc.custom_path).resolve()

    if direct_mode:
        data = copy.deepcopy(doc.schema)
        for path, raw in updates.items():
            node = nodes.get(path)
            if not node: continue
            current = engine.get_path(data, path, _MISSING)
            value = _coerce(node, raw, current)
            if node["type"] == "algebra_patch": value = sort_algebra_patch_items(value, current if isinstance(current, list) else [])
            if _same_value(value, current): continue
            engine.set_path(data, path, value)
        if _same_value(data, doc.schema):
            return json.dumps({"changed": [], "message": "没有变化"}, ensure_ascii=False)
        engine.validate_data(data)
        engine.atomic_write_many({target: data})
        return json.dumps({"changed": [target.name], "message": "保存成功"}, ensure_ascii=False)

    custom = copy.deepcopy(engine.load_file(str(target), default={}) if target.exists() else {})
    if not isinstance(custom, dict):
        raise ValueError(f"{target.name} 的根节点必须是 YAML 映射")
    patch = custom.get("patch")
    if patch is None:
        patch = {}
    if not isinstance(patch, dict):
        raise ValueError(f"{target.name} 的 patch 必须是映射，暂不支持直接编辑 patch 序列")
    original_custom = copy.deepcopy(custom)

    for path, raw in updates.items():
        node = nodes.get(path)
        if not node: continue
        display_base = doc.source_effective if node["baseline"] == "source_effective" else doc.effective
        current = engine.get_path(display_base, path, _MISSING)
        schema_base = engine.get_path(doc.schema, path, _MISSING)
        value = _coerce(node, raw, current if current is not _MISSING else schema_base)
        if node["type"] == "algebra_patch":
            sort_base = schema_base if isinstance(schema_base, list) else (current if isinstance(current, list) else [])
            value = sort_algebra_patch_items(value, sort_base)
        # All form fields are submitted together. An unchanged field must not delete its existing override.
        if _same_value(value, current):
            continue
        special_compile_directive = path.endswith("/__patch") or path.endswith("/__include")
        if _same_value(value, schema_base) or (_is_empty_value(value) and not special_compile_directive):
            patch.pop(path, None)
            patch.pop(path + "/+", None)
        else:
            patch[path] = value

    custom["patch"] = patch
    if _same_value(custom, original_custom):
        return json.dumps({"changed": [], "message": "没有变化"}, ensure_ascii=False)
    if _patch_clean(custom):
        if target.exists():
            engine.atomic_write_many({target: None})
            return json.dumps({"changed": [target.name], "message": "保存成功"}, ensure_ascii=False)
        return json.dumps({"changed": [], "message": "没有变化"}, ensure_ascii=False)
    engine.validate_data(custom)
    engine.atomic_write_many({target: custom})
    return json.dumps({"changed": [target.name], "message": "保存成功"}, ensure_ascii=False)

def _main_files(root: Path):
    return [(sid, fn, default) for sid, fn, default in _MAIN_SCHEMES if (root / fn).is_file()]


def _primary_file(root: Path, direct_mode=False):
    """Return the first enabled main scheme, using real Rime schema IDs."""
    default_path = root / "default.yaml"
    schema_to_file = {
        "wanxiang": "wanxiang.schema.yaml",
        "wanxiang_lite": "wanxiang_lite.schema.yaml",
        "wanxiang_pro": "wanxiang_pro.schema.yaml",
    }
    if default_path.is_file():
        doc = _load_light("default.yaml", root)
        view = doc.schema if direct_mode else doc.effective
        schema_list = RimeYamlEngine().get_path(view, "schema_list", [])
        if isinstance(schema_list, list):
            for item in schema_list:
                schema_id = item.get("schema") if isinstance(item, Mapping) else None
                file_name = schema_to_file.get(str(schema_id))
                if file_name and (root / file_name).is_file():
                    return file_name
    files = _main_files(root)
    return files[0][1] if files else "wanxiang.schema.yaml"

def load_common_settings(root_path: str, direct_mode: bool = False) -> str:
    root = Path(root_path).expanduser().resolve()
    engine = RimeYamlEngine()
    docs = {}
    def get_doc(file_name):
        if not (root / file_name).is_file(): return None
        if file_name not in docs:
            # The desktop common page reads the compiled Rime view. A literal
            # merge loses __include / __patch values (notably key bindings).
            docs[file_name] = _load(file_name, root)[1]
        return docs[file_name]
    def get(file_name, path, default=None):
        doc = get_doc(file_name)
        if doc is None: return default
        view = doc.schema if direct_mode else doc.effective
        return engine.get_path(view, path, default)

    primary = _primary_file(root, direct_mode)
    if not (root / primary).is_file():
        raise FileNotFoundError("未找到可编辑的主方案 YAML 文件")
    schema_value = get("default.yaml", "schema_list", [])
    default_bindings = get("default.yaml", "key_binder/bindings", [])
    primary_bindings = get(primary, "key_binder/bindings", [])
    paging, cand2, cand3 = _binding_state(primary_bindings or default_bindings)
    phrase_name = get("wanxiang_phrase.schema.yaml", "translator/dictionary", "custom_phrase") if (root / "wanxiang_phrase.schema.yaml").is_file() else "custom_phrase"
    abbrev_name = get("wanxiang_abbrev.schema.yaml", "translator/dictionary", "wanxiang_abbrev") if (root / "wanxiang_abbrev.schema.yaml").is_file() else "wanxiang_abbrev"
    fields = [
        {"path":"schema_list", "title":"启用方案", "desc":"勾选后才会出现在输入法方案菜单中。至少保留一个。", "type":"schema_checkboxes", "value":"", "choices":_schema_choices(root, schema_value)},
        {"path":"menu/page_size", "title":"候选词个数", "desc":"同步 default.yaml 与所有已安装主方案，范围 1-10。", "type":"int", "value":str(get("default.yaml", "menu/page_size", 6))},
        {"path":"paging", "title":"翻页按键习惯", "desc":"同步主方案的 PageUp/PageDown 绑定。", "type":"select", "options":["默认 (PageUp/Dn)", "逗号句号 ( , . )", "中括号 ( [ ] )", "减号等号 ( - = )"], "value":paging},
        {"path":"cand2", "title":"次选快捷键", "desc":"发送第 2 个候选的按键；留空表示不额外绑定。", "type":"str", "value":cand2},
        {"path":"cand3", "title":"三选快捷键", "desc":"发送第 3 个候选的按键；留空表示不额外绑定。", "type":"str", "value":cand3},
        {"path":"translator/enable_user_dict", "title":"启用自动调频", "desc":"同步 Base / Lite / Pro 主方案的用户词频记忆。", "type":"bool", "value":get(primary, "translator/enable_user_dict", True)},
        {"path":"translator/dictionary", "title":"当前主方案词库", "desc":"主方案使用的 dictionary 名称，不填写扩展名。", "type":"str", "value":get(primary, "translator/dictionary", "wanxiang")},
        {"path":"phrase_dict", "title":"自定义短语词库", "desc":"生成端词库名及主方案使用端关联。", "type":"str", "value":phrase_name, "choices":_scheme_choices(root, "custom_phrase/dictionary", phrase_name, docs, engine, direct_mode)},
        {"path":"phrase_schemes", "title":"自定义短语关联方案", "desc":"勾选后同步写入对应主方案。", "type":"scheme_checkboxes", "value":"", "choices":_scheme_choices(root, "custom_phrase/dictionary", phrase_name, docs, engine, direct_mode)},
        {"path":"abbrev_dict", "title":"简码词库", "desc":"生成端词库名及主方案使用端关联。", "type":"str", "value":abbrev_name, "choices":_scheme_choices(root, "abbrev_phrase/dictionary", abbrev_name, docs, engine, direct_mode)},
        {"path":"abbrev_schemes", "title":"简码关联方案", "desc":"勾选后同步写入对应主方案。", "type":"scheme_checkboxes", "value":"", "choices":_scheme_choices(root, "abbrev_phrase/dictionary", abbrev_name, docs, engine, direct_mode)},
        {"path":"wanxiang_lookup/key", "title":"反查快捷键", "desc":"同步反查 key、prefix、recognizer 正则和 alphabet。", "type":"str", "value":get(primary, "wanxiang_lookup/key", "`")},
        {"path":"super_tips/db_name", "title":"超级提示数据库", "desc":"超级提示数据文件路径。", "type":"str", "value":get(primary, "super_tips/db_name", "lua/tips")},
        {"path":"super_tips/tips_key", "title":"超级提示上屏按键", "desc":"默认使用 comma。", "type":"str", "value":get(primary, "super_tips/tips_key", "comma")},
        {"path":"super_tips/disabled_types", "title":"屏蔽的提示类型", "desc":"每行一个类型，保存为 YAML 数组。", "type":"list_text", "value":"\n".join(str(x) for x in (get(primary, "super_tips/disabled_types", []) or []))},
        {"path":"grammar_action", "title":"语法模型参数", "desc":"写入或清除桌面工具中的 LMDG 推荐参数。", "type":"select", "options":["保持当前配置", "写入推荐参数", "清除推荐参数"], "value":"保持当前配置"},
    ]
    return json.dumps({"fields": fields, "primary": primary, "directMode": bool(direct_mode)}, ensure_ascii=False)

def _replace_reverse_pattern_prefix(pattern: Any, old_key: str, new_key: str) -> str:
    """Match desktop prefix replacement without corrupting the rest of a regex."""
    pattern = str(pattern or "")
    old_key = str(old_key or "")
    replacement = re.escape(new_key)
    if not pattern.startswith("^"):
        return f"^{replacement}[A-Za-z;]*$"
    escaped_old = re.escape(old_key)
    for prefix in ("^" + escaped_old, "^" + old_key):
        if old_key and pattern.startswith(prefix):
            return "^" + replacement + pattern[len(prefix):]
    if len(pattern) >= 2:
        return "^" + replacement + pattern[2:]
    return f"^{replacement}[A-Za-z;]*$"


def _set_nested(engine, data, path, value):
    engine.set_path(data, path, value)


def _stage_named_dictionary(root: Path, default_name: str, target_name: str, pending: dict):
    """Match desktop's ensure_named_dictionary without parsing TSV as YAML.

    All dictionary changes are prepared before touching any config file, so
    a missing source or invalid existing dictionary cannot create broken refs.
    """
    if not target_name.replace("_", "").isalnum():
        raise ValueError("词库名只能使用字母、数字、下划线")
    if target_name == default_name:
        return
    src = _source_path(root, f"{default_name}.dict.yaml")
    dst = _source_path(root, f"{target_name}.dict.yaml")
    if not dst.exists() and not src.is_file():
        raise FileNotFoundError(f"找不到默认词库：{src.name}")
    if dst in pending:
        return
    original = dst.read_bytes() if dst.exists() else src.read_bytes()
    text = original.decode("utf-8")
    lines = text.splitlines(keepends=True)
    header_end = next((i for i, line in enumerate(lines) if line.strip() == "..."), len(lines))
    name_re = re.compile(r"^\s*name\s*:")
    found = False
    for i in range(header_end):
        if name_re.match(lines[i]):
            ending = "\r\n" if lines[i].endswith("\r\n") else "\n" if lines[i].endswith("\n") else ""
            lines[i] = f"name: {target_name}{ending}"
            found = True
            break
    if not found:
        lines.insert(1 if lines and lines[0].strip() == "---" else 0, f"name: {target_name}\n")
    result = "".join(lines).encode("utf-8")
    if not dst.exists() or result != original:
        pending[dst] = result


def _commit_config_and_dictionaries(engine: RimeYamlEngine, configs: dict, dictionaries: dict):
    """Commit one bounded set; restore YAML and dictionary bytes on failure.

    Dictionary bodies are TSV and are never passed through RimeYamlEngine's
    YAML parser. Each destination is same-directory fsynced temporary replace.
    """
    affected = list(configs) + list(dictionaries)
    originals = {path: path.read_bytes() if path.exists() else None for path in affected}
    temps = []
    try:
        # Publish dictionaries first: config references never point at a
        # not-yet-created dictionary after a successful commit.
        for path, raw in dictionaries.items():
            fd, temp_path = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
            temps.append(Path(temp_path))
            with os.fdopen(fd, "wb") as out:
                out.write(raw)
                out.flush()
                os.fsync(out.fileno())
            os.replace(temp_path, path)
        if configs:
            engine.atomic_write_many(configs)
    except Exception:
        for path, raw in originals.items():
            try:
                if raw is None:
                    path.unlink(missing_ok=True)
                else:
                    fd, temp_path = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".restore", dir=str(path.parent))
                    temps.append(Path(temp_path))
                    with os.fdopen(fd, "wb") as out:
                        out.write(raw)
                        out.flush()
                        os.fsync(out.fileno())
                    os.replace(temp_path, path)
            except Exception:
                pass
        raise
    finally:
        for path in temps:
            path.unlink(missing_ok=True)


def save_common_settings(root_path: str, direct_mode: bool, updates_json: str) -> str:
    root = Path(root_path).expanduser().resolve()
    updates = json.loads(updates_json or "{}")
    engine = RimeYamlEngine()
    main_files = _main_files(root)
    primary = _primary_file(root, direct_mode)
    if not main_files or not (root / primary).is_file():
        raise FileNotFoundError("未找到可编辑的主方案 YAML 文件")
    docs = {}
    changes = {}
    originals = {}
    pending_dicts = {}

    def get_doc(file_name):
        if file_name not in docs:
            docs[file_name] = _load(file_name, root)[1]
        return docs[file_name]

    def current_view(doc):
        return doc.schema if direct_mode else doc.source_effective

    def custom_key(doc):
        return str(Path(doc.custom_path).resolve())

    def ensure_change(file_name):
        doc = get_doc(file_name)
        if direct_mode:
            key = file_name
            if key not in changes:
                changes[key] = copy.deepcopy(doc.schema)
                originals[key] = copy.deepcopy(doc.schema)
            return key, changes[key]
        key = custom_key(doc)
        if key not in changes:
            target = Path(key)
            custom = engine.load_file(str(target), default={}) if target.exists() else {}
            if not isinstance(custom, dict):
                raise ValueError(f"{target.name} 的根节点必须是 YAML 映射")
            changes[key] = custom
            originals[key] = copy.deepcopy(custom)
        return key, changes[key]

    def update(file_name, path, value):
        if not (root / file_name).is_file():
            return False
        doc = get_doc(file_name)
        if direct_mode:
            working = changes.get(file_name, doc.schema)
            current = engine.get_path(working, path, _MISSING)
            if _same_value(current, value):
                return False
            _, data = ensure_change(file_name)
            engine.set_path(data, path, value)
            return True

        key = custom_key(doc)
        if key in changes:
            custom_view = changes[key].get("patch", {})
            if not isinstance(custom_view, Mapping):
                raise ValueError(f"{Path(key).name} 的 patch 必须是映射")
            current_data = engine.apply_patch(doc.schema, custom_view)
        else:
            current_data = doc.source_effective
        current = engine.get_path(current_data, path, _MISSING)
        if _same_value(current, value):
            return False
        schema_base = engine.get_path(doc.schema, path, _MISSING)
        _, custom = ensure_change(file_name)
        patch = custom.get("patch")
        if patch is None:
            patch = {}
        if not isinstance(patch, dict):
            raise ValueError(f"{Path(key).name} 的 patch 必须是映射")
        if _same_value(value, schema_base):
            patch.pop(path, None)
            patch.pop(path + "/+", None)
        else:
            patch[path] = copy.deepcopy(value)
        custom["patch"] = patch
        return True

    def remove(file_name, path):
        if not (root / file_name).is_file():
            return False
        doc = get_doc(file_name)
        if direct_mode:
            working = changes.get(file_name, doc.schema)
            if engine.get_path(working, path, _MISSING) is _MISSING:
                return False
            _, data = ensure_change(file_name)
            return engine.delete_path(data, path)

        key = custom_key(doc)
        custom = changes.get(key)
        if custom is None:
            target = Path(key)
            custom = engine.load_file(str(target), default={}) if target.exists() else {}
        if not isinstance(custom, dict):
            raise ValueError(f"{Path(key).name} 的根节点必须是 YAML 映射")
        patch = custom.get("patch") or {}
        if not isinstance(patch, Mapping) or (path not in patch and path + "/+" not in patch):
            return False
        _, custom = ensure_change(file_name)
        patch = custom.get("patch")
        if not isinstance(patch, dict):
            raise ValueError(f"{Path(key).name} 的 patch 必须是映射")
        patch.pop(path, None)
        patch.pop(path + "/+", None)
        custom["patch"] = patch
        return True

    def update_bindings(file_name, paging=None, cand2=None, cand3=None):
        """Port the desktop binding editor: direct lists or custom patch append lists."""
        if paging is None and cand2 is None and cand3 is None:
            return
        doc = get_doc(file_name)

        def binding_kind(item):
            if not isinstance(item, Mapping):
                return ""
            accept = str(item.get("accept", "")).lower()
            send = str(item.get("send", "")).lower()
            is_paging = accept in ("comma", "period", "bracketleft", "bracketright", "minus", "equal", ",", ".", "[", "]", "-", "=") and send in ("page_up", "page_down", "prior", "next")
            is_candidate = send in ("2", "3") and accept not in ("2", "kp_2", "3", "kp_3")
            if paging is not None and is_paging:
                return "paging"
            if cand2 is not None and is_candidate and send == "2":
                return "cand2"
            if cand3 is not None and is_candidate and send == "3":
                return "cand3"
            return ""

        def clean_items(items):
            if not isinstance(items, list):
                return items
            return [copy.deepcopy(item) for item in items if not binding_kind(item)]

        if direct_mode:
            working = changes.get(file_name, doc.schema)
            bindings = engine.get_path(working, "key_binder/bindings", [])
            if not isinstance(bindings, list):
                bindings = []
            new_bindings = clean_items(bindings)
            if file_name != "default.yaml":
                if paging == "逗号句号 ( , . )":
                    new_bindings.extend([{"when":"paging", "accept":"comma", "send":"Page_Up"}, {"when":"has_menu", "accept":"period", "send":"Page_Down"}])
                elif paging == "中括号 ( [ ] )":
                    new_bindings.extend([{"when":"paging", "accept":"bracketleft", "send":"Page_Up"}, {"when":"has_menu", "accept":"bracketright", "send":"Page_Down"}])
                elif paging == "减号等号 ( - = )":
                    new_bindings.extend([{"when":"has_menu", "accept":"minus", "send":"Page_Up"}, {"when":"has_menu", "accept":"equal", "send":"Page_Down"}])
                if cand2 is not None and str(cand2).strip():
                    new_bindings.append({"when":"has_menu", "accept":str(cand2).strip(), "send":2})
                if cand3 is not None and str(cand3).strip():
                    new_bindings.append({"when":"has_menu", "accept":str(cand3).strip(), "send":3})
            if not _same_value(new_bindings, bindings):
                _, data = ensure_change(file_name)
                engine.set_path(data, "key_binder/bindings", new_bindings)
            return

        key = custom_key(doc)
        if key in changes:
            custom = changes[key]
        else:
            target = Path(key)
            custom = engine.load_file(str(target), default={}) if target.exists() else {}
        if not isinstance(custom, dict):
            raise ValueError(f"{Path(key).name} 的根节点必须是 YAML 映射")
        patch = copy.deepcopy(custom.get("patch") or {})
        if not isinstance(patch, dict):
            raise ValueError(f"{Path(key).name} 的 patch 必须是映射")
        original_patch = copy.deepcopy(patch)

        # Remove only the changed binding classes from existing replacement and append patches.
        for patch_path in ("key_binder/bindings", "key_binder/bindings/+"):
            old_items = patch.get(patch_path)
            if isinstance(old_items, list):
                cleaned = clean_items(old_items)
                if not _same_value(cleaned, old_items):
                    if cleaned:
                        patch[patch_path] = cleaned
                    else:
                        patch.pop(patch_path, None)

        if file_name != "default.yaml":
            base_bindings = engine.get_path(doc.schema, "key_binder/bindings", [])
            if not isinstance(base_bindings, list):
                base_bindings = []
            base_accepts = set()
            base_key2 = ""
            base_key3 = ""
            for item in base_bindings:
                if not isinstance(item, Mapping):
                    continue
                accept = str(item.get("accept", "")).lower()
                send = str(item.get("send", "")).lower()
                if send in ("page_up", "page_down", "prior", "next"):
                    base_accepts.add(accept)
                if send == "2" and accept not in ("2", "kp_2", "3", "kp_3"):
                    base_key2 = accept
                if send == "3" and accept not in ("2", "kp_2", "3", "kp_3"):
                    base_key3 = accept

            base_paging = "默认 (PageUp/Dn)"
            if "minus" in base_accepts or "-" in base_accepts:
                base_paging = "减号等号 ( - = )"
            elif "bracketleft" in base_accepts or "[" in base_accepts:
                base_paging = "中括号 ( [ ] )"
            elif "comma" in base_accepts or "," in base_accepts:
                base_paging = "逗号句号 ( , . )"

            append_key = "key_binder/bindings/+"
            append_items = patch.get(append_key, [])
            if not isinstance(append_items, list):
                append_items = []
            else:
                append_items = copy.deepcopy(append_items)

            if paging is not None and paging != base_paging:
                if paging == "逗号句号 ( , . )":
                    append_items.extend([{"when":"paging", "accept":"comma", "send":"Page_Up"}, {"when":"has_menu", "accept":"period", "send":"Page_Down"}])
                elif paging == "中括号 ( [ ] )":
                    append_items.extend([{"when":"paging", "accept":"bracketleft", "send":"Page_Up"}, {"when":"has_menu", "accept":"bracketright", "send":"Page_Down"}])
                elif paging == "减号等号 ( - = )":
                    append_items.extend([{"when":"has_menu", "accept":"minus", "send":"Page_Up"}, {"when":"has_menu", "accept":"equal", "send":"Page_Down"}])
            if cand2 is not None and str(cand2).strip() and str(cand2).strip().lower() != base_key2:
                append_items.append({"when":"has_menu", "accept":str(cand2).strip(), "send":2})
            if cand3 is not None and str(cand3).strip() and str(cand3).strip().lower() != base_key3:
                append_items.append({"when":"has_menu", "accept":str(cand3).strip(), "send":3})

            if append_items:
                patch[append_key] = append_items
            else:
                patch.pop(append_key, None)

        if not _same_value(patch, original_patch):
            _, working_custom = ensure_change(file_name)
            working_custom["patch"] = patch

    if "schema_list" in updates:
        schema_value = _coerce({"type":"schema_checkboxes","path":"schema_list"}, updates["schema_list"], [])
        update("default.yaml", "schema_list", schema_value)
    if "menu/page_size" in updates:
        page = int(str(updates["menu/page_size"]).strip())
        if not 1 <= page <= 10: raise ValueError("候选词个数必须在 1-10 之间")
        for file_name in ["default.yaml"] + [fn for _, fn, _ in main_files]: update(file_name, "menu/page_size", page)
    if any(k in updates for k in ("paging", "cand2", "cand3")):
        for file_name in ["default.yaml"] + [fn for _, fn, _ in main_files]:
            if not (root / file_name).is_file(): continue
            update_bindings(
                file_name,
                updates.get("paging") if "paging" in updates else None,
                updates.get("cand2") if "cand2" in updates else None,
                updates.get("cand3") if "cand3" in updates else None,
            )
    if "phrase_dict" in updates or "phrase_schemes" in updates:
        phrase_doc = get_doc("wanxiang_phrase.schema.yaml") if (root / "wanxiang_phrase.schema.yaml").is_file() else None
        current_name = engine.get_path(current_view(phrase_doc), "translator/dictionary", "custom_phrase") if phrase_doc else "custom_phrase"
        name = str(updates.get("phrase_dict", current_name)).strip()
        if not name or not name.replace("_", "").isalnum(): raise ValueError("自定义短语词库名只能包含字母、数字和下划线")
        selected = ({str(x.get("schema")) for x in _coerce({"type":"scheme_checkboxes"}, updates["phrase_schemes"], [])}
                    if "phrase_schemes" in updates else {
                        sid for sid, fn, _ in main_files if str(engine.get_path(current_view(get_doc(fn)), "custom_phrase/dictionary", "")) == str(current_name)
                    })
        if "phrase_dict" in updates:
            _stage_named_dictionary(root, "custom_phrase", name, pending_dicts)
        if phrase_doc: update("wanxiang_phrase.schema.yaml", "translator/dictionary", name)
        for sid, fn, _ in main_files:
            if sid in selected: update(fn, "custom_phrase/dictionary", name)
            elif "phrase_schemes" in updates: remove(fn, "custom_phrase/dictionary")
    if "abbrev_dict" in updates or "abbrev_schemes" in updates:
        abbrev_doc = get_doc("wanxiang_abbrev.schema.yaml") if (root / "wanxiang_abbrev.schema.yaml").is_file() else None
        current_name = engine.get_path(current_view(abbrev_doc), "translator/dictionary", "wanxiang_abbrev") if abbrev_doc else "wanxiang_abbrev"
        name = str(updates.get("abbrev_dict", current_name)).strip()
        if not name or not name.replace("_", "").isalnum(): raise ValueError("简码词库名只能包含字母、数字和下划线")
        selected = ({str(x.get("schema")) for x in _coerce({"type":"scheme_checkboxes"}, updates["abbrev_schemes"], [])}
                    if "abbrev_schemes" in updates else {
                        sid for sid, fn, _ in main_files if str(engine.get_path(current_view(get_doc(fn)), "abbrev_phrase/dictionary", "")) == str(current_name)
                    })
        if "abbrev_dict" in updates:
            _stage_named_dictionary(root, "wanxiang_abbrev", name, pending_dicts)
        if abbrev_doc: update("wanxiang_abbrev.schema.yaml", "translator/dictionary", name)
        for sid, fn, _ in main_files:
            if sid in selected: update(fn, "abbrev_phrase/dictionary", name)
            elif "abbrev_schemes" in updates: remove(fn, "abbrev_phrase/dictionary")
    if updates.get("grammar_action") in ("写入推荐参数", "清除推荐参数"):
        for _, fn, _ in main_files:
            if updates["grammar_action"] == "写入推荐参数":
                update(fn, "grammar", {"language":"wanxiang-lts-zh-hans", "collocation_max_length":7, "collocation_min_length":3, "collocation_penalty":-10, "non_collocation_penalty":3, "weak_collocation_penalty":-35, "unseen_two_char_penalty":0, "rear_penalty":-8})
                update(fn, "translator/contextual_suggestions", False)
                update(fn, "translator/max_homophones", 8)
                update(fn, "translator/max_homographs", 8)
            else:
                remove(fn, "grammar")
                remove(fn, "translator/contextual_suggestions")
                remove(fn, "translator/max_homophones")
                remove(fn, "translator/max_homographs")

    if "translator/enable_user_dict" in updates:
        enabled = _coerce({"type":"bool"}, updates["translator/enable_user_dict"], True)
        for _, fn, _ in main_files: update(fn, "translator/enable_user_dict", enabled)
    if "translator/dictionary" in updates:
        name = str(updates["translator/dictionary"]).strip()
        if not name or not name.replace("_", "").isalnum(): raise ValueError("词库名只能包含字母、数字和下划线")
        spec = next((x for x in main_files if x[1] == primary), None)
        if spec:
            _stage_named_dictionary(root, spec[2], name, pending_dicts)
            update(primary, "translator/dictionary", name)
            if spec[0] == "pro":
                update(primary, "user_dict_set/dictionary", name)
                update(primary, "add_user_dict/dictionary", name)
    if any(k in updates for k in ("wanxiang_lookup/key", "super_tips/db_name", "super_tips/tips_key", "super_tips/disabled_types")):
        if "wanxiang_lookup/key" in updates:
            key = str(updates["wanxiang_lookup/key"]).strip()
            if len(key) != 1 or key.isalnum(): raise ValueError("反查快捷键必须是单个非字母数字符号")
            for _, fn, _ in main_files:
                doc = get_doc(fn)
                view = current_view(doc)
                old = str(engine.get_path(view, "wanxiang_lookup/key", "`"))
                pattern = engine.get_path(view, "recognizer/patterns/wanxiang_reverse", "^`[A-Za-z;]*$")
                update(fn, "wanxiang_lookup/key", key)
                update(fn, "wanxiang_reverse/prefix", key)
                update(fn, "recognizer/patterns/wanxiang_reverse", _replace_reverse_pattern_prefix(pattern, old, key))
                alphabet = engine.get_path(view, "speller/alphabet", "")
                if isinstance(alphabet, str) and alphabet:
                    updated_alphabet = alphabet.replace(old, "") if old != key else alphabet
                    if key not in updated_alphabet:
                        updated_alphabet += key
                    update(fn, "speller/alphabet", updated_alphabet)
        for path in ("super_tips/db_name", "super_tips/tips_key", "super_tips/disabled_types"):
            if path in updates:
                val = _parse_list_text(updates[path], [], path) if path.endswith("disabled_types") else str(updates[path])
                for fn in ("wanxiang.schema.yaml", "wanxiang_pro.schema.yaml"):
                    if (root / fn).is_file(): update(fn, path, val)

    write_changes = {}
    changed = []
    for key, data in list(changes.items()):
        if direct_mode:
            target = (root / key).resolve()
            if _same_value(data, originals[key]):
                continue
            engine.validate_data(data)
            write_changes[target] = data
            changed.append(target.name)
        else:
            target = Path(key).resolve()
            if _same_value(data, originals[key]):
                continue
            if _patch_clean(data):
                if target.exists():
                    write_changes[target] = None
                    changed.append(target.name)
            else:
                engine.validate_data(data)
                write_changes[target] = data
                changed.append(target.name)
    if write_changes or pending_dicts:
        _commit_config_and_dictionaries(engine, write_changes, pending_dicts)
    changed.extend(path.name for path in pending_dicts)
    return json.dumps({"changed": sorted(set(changed)), "message":"保存成功" if changed else "没有变化"}, ensure_ascii=False)

def get_common_value(root: Path, file_name: str, path: str, default: Any, direct_mode=False):
    try:
        _, doc = _load(file_name, root)
        view = doc.schema if direct_mode else doc.source_effective
        return RimeYamlEngine().get_path(view, path, default)
    except Exception:
        return default

def import_switches(root_path: str) -> str:
    root = Path(root_path).expanduser().resolve()
    path = root / "wanxiang.schema.yaml"
    if not path.is_file():
        raise FileNotFoundError("未找到 wanxiang.schema.yaml")
    data = _SAFE_YAML.load(path.read_text(encoding="utf-8")) or {}
    switches = data.get("switches", []) if isinstance(data, Mapping) else []
    result = []
    for item in switches if isinstance(switches, list) else []:
        if not isinstance(item, Mapping):
            continue
        if "name" in item and "reset" not in item:
            result.append(str(item["name"]))
        elif isinstance(item.get("options"), list) and len(item["options"]) > 1:
            result.extend(str(x) for x in item["options"][1:])
    return json.dumps({"value": "\n".join(result), "count": len(result)}, ensure_ascii=False)
