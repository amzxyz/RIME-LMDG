"""Metadata-driven advanced settings bridge for the Android UI.

The module intentionally keeps the desktop YAML semantics: lists preserve their
actual YAML type, custom files use Rime's literal patch keys, and direct/patch
writes are validated atomically. It also exposes the desktop tool's common
cross-file settings page and schema-list checkbox model.
"""
from __future__ import annotations
import copy
import json
from pathlib import Path
from typing import Any, Mapping
from ruamel.yaml import YAML
from advanced_settings.core import RimeYamlEngine
from advanced_settings.metadata import FILE_INDEX_META, SCHEMA_META_CONFIG, sort_algebra_patch_items

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
                "template": _json_value(node.get("template")),
                "presetKeys": _json_value(node.get("preset_keys")),
                "actionButton": str(node.get("action_btn", "")),
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


def _scheme_choices(root: Path, usage_path: str, current_name: str, docs=None, engine=None):
    """Build scheme choices using a shared document cache.

    Common settings used to parse every schema once per field. Reusing these
    documents cuts the startup work from dozens of full Rime compilations to
    one compilation per existing schema.
    """
    docs = docs if docs is not None else {}
    engine = engine or RimeYamlEngine()
    choices = []
    for sid, file_name, _ in _MAIN_SCHEMES:
        if not (root / file_name).is_file():
            continue
        if file_name not in docs:
            docs[file_name] = _load(file_name, root)[1]
        doc = docs[file_name]
        label = str(engine.get_path(doc.effective, "schema/name", sid.title()))
        active = str(engine.get_path(doc.effective, usage_path, "")) == str(current_name)
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
    for group, files in FILE_INDEX_META.items():
        for item in files:
            name = str(item.get("file", ""))
            if not (root / name).is_file():
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


def load_form(root_path: str, file_name: str, section: str = "") -> str:
    root = Path(root_path).expanduser().resolve()
    engine, doc = _load(file_name, root)
    rows = []
    for node in _nodes_for(file_name):
        if section and node["section"] != section:
            continue
        base = doc.source_effective if node["baseline"] == "source_effective" else doc.effective
        value = engine.get_path(base, node["path"], None)
        item = dict(node)
        item["value"] = _show_value(value, node["type"])
        item["rawValue"] = _json_value(value)
        item["valueShape"] = "list" if isinstance(value, list) else "dict" if isinstance(value, dict) else "scalar"
        if node["type"] == "schema_checkboxes":
            item["choices"] = _schema_choices(root, value)
        rows.append(item)
    return json.dumps({"file": file_name, "section": section, "fields": rows}, ensure_ascii=False)


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
        return float(text) if "." in text else int(text)
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
        if not normalized:
            raise ValueError("至少需要保留一个启用方案")
        return normalized
    if node_type == "list_text":
        return _parse_list_text(value, original, str(node.get("path", "")).split("/")[-1])
    if node_type in ("dynamic_list", "algebra_patch", "dynamic_block_list", "reverse_algebra", "english_algebra", "mixed_algebra"):
        if isinstance(value, list): return value
        text = str(value or "").strip()
        if text.startswith("["):
            try: return _SAFE_YAML.load(text)
            except Exception: pass
        return [x.strip() for x in text.splitlines() if x.strip()]
    if node_type == "dynamic_kv_list":
        if isinstance(value, dict): return value
        text = str(value or "").strip()
        if text.startswith("{"):
            try: return _SAFE_YAML.load(text) or {}
            except Exception: pass
        result = {}
        for line in text.splitlines():
            if ":" in line: key, item = line.split(":", 1)
            elif "=" in line: key, item = line.split("=", 1)
            else: continue
            result[key.strip()] = item.strip()
        return result
    if node_type in ("raw_yaml", "dynamic_map"):
        text = str(value or "")
        try: return _SAFE_YAML.load(text)
        except Exception: return text
    if node_type == "select" and isinstance(original, int):
        return int(str(value).strip())
    return "" if value is None else str(value)


def _patch_clean(custom: dict):
    return not custom or (set(custom.keys()) <= {"patch"} and not custom.get("patch"))


def save_form(root_path: str, file_name: str, section: str, direct_mode: bool, updates_json: str) -> str:
    root = Path(root_path).expanduser().resolve()
    engine, doc = _load(file_name, root)
    updates = json.loads(updates_json or "{}")
    nodes = {n["path"]: n for n in _nodes_for(file_name) if not section or n["section"] == section}
    direct_mode = bool(direct_mode or (file_name != "default.yaml" and not file_name.endswith(".schema.yaml")))
    target = Path(doc.schema_path if direct_mode else doc.custom_path)

    if direct_mode:
        data = copy.deepcopy(doc.schema)
        for path, raw in updates.items():
            node = nodes.get(path)
            if not node: continue
            original = engine.get_path(doc.source_effective, path, None)
            value = _coerce(node, raw, original)
            if node["type"] == "algebra_patch": value = sort_algebra_patch_items(value, original or [])
            engine.set_path(data, path, value)
        engine.validate_data(data)
        if data == doc.schema:
            return json.dumps({"changed": [], "message": "没有变化"}, ensure_ascii=False)
        engine.atomic_write_many({target: data})
        return json.dumps({"changed": [target.name], "message": "保存成功"}, ensure_ascii=False)

    custom = copy.deepcopy(engine.load_file(str(target), default={}) if target.exists() else {})
    if not isinstance(custom, dict): custom = {}
    patch = custom.get("patch")
    if not isinstance(patch, dict): patch = {}
    for path, raw in updates.items():
        node = nodes.get(path)
        if not node: continue
        original = engine.get_path(doc.source_effective, path, None)
        value = _coerce(node, raw, original)
        if node["type"] == "algebra_patch": value = sort_algebra_patch_items(value, original or [])
        # Rime custom YAML uses literal patch path keys, not a nested mapping.
        if value == original:
            patch.pop(path, None)
            patch.pop(path + "/+", None)
        else:
            patch[path] = value
    custom["patch"] = patch
    if _patch_clean(custom):
        if target.exists(): engine.atomic_write_many({target: None})
        return json.dumps({"changed": [target.name] if target.exists() else [], "message": "保存成功"}, ensure_ascii=False)
    engine.validate_data(custom)
    engine.atomic_write_many({target: custom})
    return json.dumps({"changed": [target.name], "message": "保存成功"}, ensure_ascii=False)


def _main_files(root: Path):
    return [(sid, fn, default) for sid, fn, default in _MAIN_SCHEMES if (root / fn).is_file()]


def _primary_file(root: Path):
    default_path = root / "default.yaml"
    if default_path.is_file():
        engine = RimeYamlEngine()
        data = engine.load_file(str(default_path), default={})
        schema_list = engine.get_path(data, "schema_list", [])
        if isinstance(schema_list, list):
            active = [x.get("schema") for x in schema_list if isinstance(x, Mapping)]
            for sid, fn, _ in _MAIN_SCHEMES:
                if sid == active[0] and (root / fn).is_file(): return fn
    return _main_files(root)[0][1] if _main_files(root) else "wanxiang.schema.yaml"


def load_common_settings(root_path: str) -> str:
    root = Path(root_path).expanduser().resolve()
    engine = RimeYamlEngine()
    docs = {}
    def get_doc(file_name):
        if not (root / file_name).is_file(): return None
        if file_name not in docs:
            docs[file_name] = _load_light(file_name, root)
        return docs[file_name]
    def get(file_name, path, default=None):
        doc = get_doc(file_name)
        return engine.get_path(doc.effective, path, default) if doc is not None else default
    # Determine the primary scheme from the already cached default document.
    primary = _primary_file(root)
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
        {"path":"phrase_dict", "title":"自定义短语词库", "desc":"生成端词库名及主方案使用端关联。", "type":"str", "value":phrase_name, "choices":_scheme_choices(root, "custom_phrase/dictionary", phrase_name, docs, engine)},
        {"path":"phrase_schemes", "title":"自定义短语关联方案", "desc":"勾选后同步写入对应主方案。", "type":"scheme_checkboxes", "value":"", "choices":_scheme_choices(root, "custom_phrase/dictionary", phrase_name, docs, engine)},
        {"path":"abbrev_dict", "title":"简码词库", "desc":"生成端词库名及主方案使用端关联。", "type":"str", "value":abbrev_name, "choices":_scheme_choices(root, "abbrev_phrase/dictionary", abbrev_name, docs, engine)},
        {"path":"abbrev_schemes", "title":"简码关联方案", "desc":"勾选后同步写入对应主方案。", "type":"scheme_checkboxes", "value":"", "choices":_scheme_choices(root, "abbrev_phrase/dictionary", abbrev_name, docs, engine)},
        {"path":"wanxiang_lookup/key", "title":"反查快捷键", "desc":"同步反查 key、prefix、recognizer 正则和 alphabet。", "type":"str", "value":get(primary, "wanxiang_lookup/key", "`")},
        {"path":"super_tips/db_name", "title":"超级提示数据库", "desc":"超级提示数据文件路径。", "type":"str", "value":get(primary, "super_tips/db_name", "lua/tips")},
        {"path":"super_tips/tips_key", "title":"超级提示上屏按键", "desc":"默认使用 comma。", "type":"str", "value":get(primary, "super_tips/tips_key", "comma")},
        {"path":"super_tips/disabled_types", "title":"屏蔽的提示类型", "desc":"每行一个类型，保存为 YAML 数组。", "type":"list_text", "value":"\n".join(str(x) for x in (get(primary, "super_tips/disabled_types", []) or []))},
        {"path":"grammar_action", "title":"语法模型参数", "desc":"写入或清除桌面工具中的 LMDG 推荐参数。", "type":"select", "options":["保持当前配置", "写入推荐参数", "清除推荐参数"], "value":"保持当前配置"},
    ]
    return json.dumps({"fields": fields, "primary": primary}, ensure_ascii=False)


def _set_nested(engine, data, path, value):
    engine.set_path(data, path, value)


def save_common_settings(root_path: str, direct_mode: bool, updates_json: str) -> str:
    root = Path(root_path).expanduser().resolve()
    updates = json.loads(updates_json or "{}")
    engine = RimeYamlEngine()
    main_files = _main_files(root)
    primary = _primary_file(root)
    docs = {}
    changes = {}

    def get_doc(file_name):
        if file_name not in docs: docs[file_name] = _load(file_name, root)[1]
        return docs[file_name]

    def update(file_name, path, value):
        doc = get_doc(file_name)
        if direct_mode:
            data = changes.setdefault(file_name, copy.deepcopy(doc.schema))
            _set_nested(engine, data, path, value)
        else:
            custom_path = Path(doc.custom_path)
            custom = changes.setdefault(str(custom_path), copy.deepcopy(engine.load_file(str(custom_path), default={}) if custom_path.exists() else {}))
            if not isinstance(custom, dict): custom = {}; changes[str(custom_path)] = custom
            patch = custom.setdefault("patch", {})
            base = engine.get_path(doc.source_effective, path, None)
            if value == base:
                patch.pop(path, None)
                patch.pop(path + "/+", None)
            else:
                patch[path] = value

    def remove(file_name, path):
        doc = get_doc(file_name)
        if direct_mode:
            data = changes.setdefault(file_name, copy.deepcopy(doc.schema))
            current = data
            parts = path.split("/")
            for part in parts[:-1]:
                if not isinstance(current, dict) or part not in current: return
                current = current[part]
            if isinstance(current, dict): current.pop(parts[-1], None)
        else:
            custom_path = Path(doc.custom_path)
            custom = changes.setdefault(str(custom_path), copy.deepcopy(engine.load_file(str(custom_path), default={}) if custom_path.exists() else {}))
            if not isinstance(custom, dict): custom = {}; changes[str(custom_path)] = custom
            patch = custom.setdefault("patch", {})
            patch.pop(path, None)
            patch.pop(path + "/+", None)

    def update_bindings(file_name, paging=None, cand2=None, cand3=None):
        doc = get_doc(file_name)
        current = engine.get_path(doc.effective, "key_binder/bindings", [])
        if not isinstance(current, list): current = []
        new = []
        for item in current:
            if not isinstance(item, Mapping):
                continue
            accept = str(item.get("accept", "")).lower()
            send = str(item.get("send", "")).lower()
            is_paging = accept in ("comma", "period", "bracketleft", "bracketright", "minus", "equal", ",", ".", "[", "]", "-", "=") and send in ("page_up", "page_down", "prior", "next")
            is_candidate = send in ("2", "3") and accept not in ("2", "kp_2", "3", "kp_3")
            if (paging is not None and is_paging) or (cand2 is not None and send == "2" and is_candidate) or (cand3 is not None and send == "3" and is_candidate):
                continue
            new.append(copy.deepcopy(item))
        if file_name != "default.yaml":
            if paging == "逗号句号 ( , . )":
                new.extend([{"when":"paging", "accept":"comma", "send":"Page_Up"}, {"when":"has_menu", "accept":"period", "send":"Page_Down"}])
            elif paging == "中括号 ( [ ] )":
                new.extend([{"when":"paging", "accept":"bracketleft", "send":"Page_Up"}, {"when":"has_menu", "accept":"bracketright", "send":"Page_Down"}])
            elif paging == "减号等号 ( - = )":
                new.extend([{"when":"has_menu", "accept":"minus", "send":"Page_Up"}, {"when":"has_menu", "accept":"equal", "send":"Page_Down"}])
            if cand2:
                new.append({"when":"has_menu", "accept":str(cand2).strip(), "send":2})
            if cand3:
                new.append({"when":"has_menu", "accept":str(cand3).strip(), "send":3})
        update(file_name, "key_binder/bindings", new)

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
            doc = get_doc(file_name)
            old_paging, old_cand2, old_cand3 = _binding_state(engine.get_path(doc.effective, "key_binder/bindings", []))
            update_bindings(
                file_name,
                updates.get("paging") if "paging" in updates else old_paging,
                updates.get("cand2") if "cand2" in updates else old_cand2,
                updates.get("cand3") if "cand3" in updates else old_cand3,
            )
    if "phrase_dict" in updates or "phrase_schemes" in updates:
        name = str(updates.get("phrase_dict", "custom_phrase")).strip()
        selected = set()
        if "phrase_schemes" in updates:
            selected = {str(x.get("schema")) for x in _coerce({"type":"scheme_checkboxes"}, updates["phrase_schemes"], [])}
        if (root / "wanxiang_phrase.schema.yaml").is_file(): update("wanxiang_phrase.schema.yaml", "translator/dictionary", name)
        for sid, fn, _ in main_files:
            if sid in selected: update(fn, "custom_phrase/dictionary", name)
            elif "phrase_schemes" in updates: remove(fn, "custom_phrase/dictionary")
    if "abbrev_dict" in updates or "abbrev_schemes" in updates:
        name = str(updates.get("abbrev_dict", "wanxiang_abbrev")).strip()
        selected = set()
        if "abbrev_schemes" in updates:
            selected = {str(x.get("schema")) for x in _coerce({"type":"scheme_checkboxes"}, updates["abbrev_schemes"], [])}
        if (root / "wanxiang_abbrev.schema.yaml").is_file(): update("wanxiang_abbrev.schema.yaml", "translator/dictionary", name)
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
            update(primary, "translator/dictionary", name)
            if spec[0] == "pro":
                update(primary, "user_dict_set/dictionary", name)
                update(primary, "add_user_dict/dictionary", name)
    if any(k in updates for k in ("wanxiang_lookup/key", "super_tips/db_name", "super_tips/tips_key", "super_tips/disabled_types")):
        if "wanxiang_lookup/key" in updates:
            key = str(updates["wanxiang_lookup/key"]).strip()
            if len(key) != 1 or key.isalnum(): raise ValueError("反查快捷键必须是单个非字母数字符号")
            update(primary, "wanxiang_lookup/key", key)
            update(primary, "wanxiang_reverse/prefix", key)
            old = get_common_value(root, primary, "wanxiang_lookup/key", "`")
            pattern = get_common_value(root, primary, "recognizer/patterns/wanxiang_reverse", "^`[A-Za-z;]*$")
            update(primary, "recognizer/patterns/wanxiang_reverse", str(pattern).replace(str(old), key, 1))
        for path in ("super_tips/db_name", "super_tips/tips_key", "super_tips/disabled_types"):
            if path in updates:
                val = _parse_list_text(updates[path], [], path) if path.endswith("disabled_types") else str(updates[path])
                for fn in ("wanxiang.schema.yaml", "wanxiang_pro.schema.yaml"):
                    if (root / fn).is_file(): update(fn, path, val)

    changed = []
    for key, data in list(changes.items()):
        target = Path(key) if not direct_mode else root / key
        if direct_mode:
            engine.validate_data(data)
            if data != get_doc(key).schema: changed.append(target.name)
        else:
            if not data.get("patch"):
                changes[key] = None
            else:
                engine.validate_data(data)
            changed.append(target.name)
    if changes:
        engine.atomic_write_many({Path(k): v for k, v in changes.items()})
    return json.dumps({"changed": sorted(set(changed)), "message":"保存成功"}, ensure_ascii=False)


def get_common_value(root: Path, file_name: str, path: str, default: Any):
    try:
        _, doc = _load(file_name, root)
        return RimeYamlEngine().get_path(doc.effective, path, default)
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
