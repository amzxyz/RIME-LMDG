from __future__ import annotations

import copy
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from enum import IntEnum
from io import StringIO
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

from ruamel.yaml import YAML
from ruamel.yaml.constructor import DuplicateKeyError


_MISSING = object()


# 高级设置只允许接触原始代码 FILE_INDEX_META 中登记的纯配置文件。
# 这是硬边界，不使用“只要后缀是 .yaml 就处理”的泛化规则。
MANAGED_RIME_SOURCE_FILES = frozenset({
    "default.yaml",
    "wanxiang_algebra.yaml",
    "wanxiang.schema.yaml",
    "wanxiang_pro.schema.yaml",
    "wanxiang_english.schema.yaml",
    "wanxiang_mixedcode.schema.yaml",
    "wanxiang_reverse.schema.yaml",
    "wanxiang_t9.schema.yaml",
})

MANAGED_RIME_CUSTOM_FILES = frozenset({
    "default.custom.yaml",
    "wanxiang.custom.yaml",
    "wanxiang_pro.custom.yaml",
    "wanxiang_english.custom.yaml",
    "wanxiang_mixedcode.custom.yaml",
    "wanxiang_reverse.custom.yaml",
    "wanxiang_t9.custom.yaml",
})


def is_managed_source_yaml(path: Path | str) -> bool:
    return Path(path).name.lower() in MANAGED_RIME_SOURCE_FILES


def is_managed_config_yaml(path: Path | str) -> bool:
    name = Path(path).name.lower()
    return name in MANAGED_RIME_SOURCE_FILES or name in MANAGED_RIME_CUSTOM_FILES


def is_rime_dictionary(path: Path | str) -> bool:
    return Path(path).name.lower().endswith(".dict.yaml")


@dataclass(frozen=True)
class YamlDuplicateIssue:
    file_path: str
    key: str
    parent_path: str
    first_line: int
    second_line: int
    first_text: str = ""
    second_text: str = ""

    @property
    def title(self) -> str:
        parent = self.parent_path or "<根节点>"
        return f"{Path(self.file_path).name}: {parent}/{self.key}"


class RimeYamlError(RuntimeError):
    def __init__(self, message: str, *, file_path: str = "", issue: Optional[YamlDuplicateIssue] = None):
        super().__init__(message)
        self.file_path = file_path
        self.issue = issue


@dataclass
class LoadedRimeDocument:
    file_name: str
    schema_path: str
    custom_path: str
    schema: Any
    patch: Any
    effective: Any


class RimeYamlEngine:
    """Rime YAML 加载、补丁解析、校验与事务写入。"""

    def __init__(self) -> None:
        self.yaml = YAML()
        self.yaml.preserve_quotes = True
        self.yaml.allow_duplicate_keys = False
        self.yaml.width = 1024
        self.yaml.indent(mapping=2, sequence=4, offset=2)

        self.safe_yaml = YAML(typ="safe")
        self.safe_yaml.allow_duplicate_keys = False

    @staticmethod
    def _line_text(path: str, index: int) -> str:
        try:
            lines = Path(path).read_text(encoding="utf-8").splitlines()
            return lines[index] if 0 <= index < len(lines) else ""
        except Exception:
            return ""

    @staticmethod
    def _key_at_line(path: str, line_index: int) -> str:
        text = RimeYamlEngine._line_text(path, line_index)
        match = re.match(r"^\s*(?:['\"]([^'\"]+)['\"]|([^:#][^:]*?))\s*:\s*", text)
        if not match:
            return "<未知键>"
        return (match.group(1) or match.group(2) or "<未知键>").strip()

    @staticmethod
    def _parent_path_at_line(path: str, line_index: int) -> str:
        """按缩进推断键的父路径，仅用于给错误定位提供上下文。"""
        try:
            lines = Path(path).read_text(encoding="utf-8").splitlines()
        except Exception:
            return ""

        if not (0 <= line_index < len(lines)):
            return ""

        current = lines[line_index]
        current_indent = len(current) - len(current.lstrip(" "))
        stack: List[Tuple[int, str]] = []

        key_pattern = re.compile(r"^(\s*)(?:-\s*)?(?:['\"]([^'\"]+)['\"]|([^:#][^:]*?))\s*:\s*(?:#.*)?$")
        for idx, line in enumerate(lines[:line_index]):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            match = key_pattern.match(line)
            if not match:
                continue
            indent = len(match.group(1))
            key = (match.group(2) or match.group(3) or "").strip()
            while stack and stack[-1][0] >= indent:
                stack.pop()
            stack.append((indent, key))

        while stack and stack[-1][0] >= current_indent:
            stack.pop()
        return "/".join(key for _, key in stack)

    def duplicate_issue_from_error(self, path: str, error: DuplicateKeyError) -> YamlDuplicateIssue:
        problem_line = getattr(getattr(error, "problem_mark", None), "line", 0) or 0
        context_line = getattr(getattr(error, "context_mark", None), "line", problem_line) or problem_line
        key = self._key_at_line(path, problem_line)
        parent = self._parent_path_at_line(path, problem_line)

        # ruamel 的 context_mark 常指向整个映射起点，并不一定是第一次定义。
        # 从重复行向上寻找“同缩进、同父路径、同键名”的真实首定义。
        first_line = context_line
        try:
            lines = Path(path).read_text(encoding="utf-8").splitlines()
            current_text = lines[problem_line] if 0 <= problem_line < len(lines) else ""
            current_indent = len(current_text) - len(current_text.lstrip(" "))
            for index in range(problem_line - 1, -1, -1):
                line = lines[index]
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                indent = len(line) - len(line.lstrip(" "))
                if indent != current_indent:
                    continue
                if self._key_at_line(path, index) != key:
                    continue
                if self._parent_path_at_line(path, index) != parent:
                    continue
                first_line = index
                break
        except Exception:
            pass

        return YamlDuplicateIssue(
            file_path=path,
            key=key,
            parent_path=parent,
            first_line=first_line,
            second_line=problem_line,
            first_text=self._line_text(path, first_line),
            second_text=self._line_text(path, problem_line),
        )

    def load_file(self, path: str, *, default: Any = None) -> Any:
        if not path or not os.path.exists(path):
            return copy.deepcopy(default)
        if is_rime_dictionary(path):
            raise RimeYamlError(
                f"拒绝把 Rime 词典当作纯 YAML 解析：{Path(path).name}",
                file_path=path,
            )
        try:
            text = Path(path).read_text(encoding="utf-8")
            data = self.yaml.load(text)
            return copy.deepcopy(default) if data is None else data
        except DuplicateKeyError as error:
            issue = self.duplicate_issue_from_error(path, error)
            raise RimeYamlError(
                f"YAML 同层级重复键：{issue.title}（第 {issue.first_line + 1}、{issue.second_line + 1} 行）",
                file_path=path,
                issue=issue,
            ) from error
        except Exception as error:
            raise RimeYamlError(f"无法解析 {Path(path).name}: {error}", file_path=path) from error

    def load_pair(self, schema_path: str, custom_path: str = "") -> LoadedRimeDocument:
        if not is_managed_source_yaml(schema_path):
            raise RimeYamlError(
                f"高级设置拒绝加载未登记文件：{Path(schema_path).name}",
                file_path=schema_path,
            )
        if custom_path and Path(custom_path).exists() and not is_managed_config_yaml(custom_path):
            raise RimeYamlError(
                f"高级设置拒绝加载未登记补丁：{Path(custom_path).name}",
                file_path=custom_path,
            )
        schema = self.load_file(schema_path, default={})
        custom = self.load_file(custom_path, default={}) if custom_path and Path(custom_path).exists() else {}
        patch = custom.get("patch", {}) if isinstance(custom, Mapping) else {}
        patch = patch or {}
        effective = self.apply_patch(schema, patch)
        return LoadedRimeDocument(
            file_name=Path(schema_path).name,
            schema_path=schema_path,
            custom_path=custom_path,
            schema=schema,
            patch=patch,
            effective=effective,
        )

    @staticmethod
    def _tokenize(path: str) -> List[str]:
        return [part for part in str(path).split("/") if part != ""]

    @staticmethod
    def _parse_index(token: str) -> Tuple[str, Optional[int]]:
        if token.startswith("@before "):
            try:
                return "before", int(token[8:].strip())
            except ValueError:
                return "key", None
        if token.startswith("@after "):
            try:
                return "after", int(token[7:].strip())
            except ValueError:
                return "key", None
        if token.startswith("@"):
            try:
                return "index", int(token[1:])
            except ValueError:
                return "key", None
        return "key", None

    def get_path(self, data: Any, path: str, default: Any = None) -> Any:
        current = data
        for token in self._tokenize(path):
            kind, index = self._parse_index(token)
            if kind == "index":
                if not isinstance(current, Sequence) or isinstance(current, (str, bytes)) or index is None or not (0 <= index < len(current)):
                    return default
                current = current[index]
            elif isinstance(current, Mapping) and token in current:
                current = current[token]
            else:
                return default
        return current

    def _ensure_child(self, parent: Any, token: str, next_token: Optional[str]) -> Any:
        kind, index = self._parse_index(token)
        next_kind, _ = self._parse_index(next_token or "")
        want_list = next_kind in {"index", "before", "after"}

        if kind == "index":
            if not isinstance(parent, list) or index is None:
                raise TypeError(f"路径 {token} 需要列表父节点")
            while len(parent) <= index:
                parent.append(None)
            if parent[index] is None:
                parent[index] = [] if want_list else {}
            return parent[index]

        if not isinstance(parent, MutableMapping):
            raise TypeError(f"路径 {token} 需要字典父节点")
        if token not in parent or parent[token] is None:
            parent[token] = [] if want_list else {}
        return parent[token]

    def set_path(self, data: Any, path: str, value: Any) -> None:
        tokens = self._tokenize(path)
        if not tokens:
            raise ValueError("空路径")

        current = data
        for idx, token in enumerate(tokens[:-1]):
            current = self._ensure_child(current, token, tokens[idx + 1])

        last = tokens[-1]
        kind, index = self._parse_index(last)
        if kind == "index":
            if not isinstance(current, list) or index is None:
                raise TypeError(f"路径 {last} 需要列表父节点")
            while len(current) <= index:
                current.append(None)
            current[index] = copy.deepcopy(value)
        elif kind == "before":
            if not isinstance(current, list) or index is None:
                raise TypeError(f"路径 {last} 需要列表父节点")
            current.insert(max(0, min(index, len(current))), copy.deepcopy(value))
        elif kind == "after":
            if not isinstance(current, list) or index is None:
                raise TypeError(f"路径 {last} 需要列表父节点")
            current.insert(max(0, min(index + 1, len(current))), copy.deepcopy(value))
        else:
            if not isinstance(current, MutableMapping):
                raise TypeError(f"路径 {last} 需要字典父节点")
            current[last] = copy.deepcopy(value)

    def delete_path(self, data: Any, path: str) -> bool:
        tokens = self._tokenize(path)
        if not tokens:
            return False
        current = data
        for token in tokens[:-1]:
            kind, index = self._parse_index(token)
            if kind == "index":
                if not isinstance(current, list) or index is None or not (0 <= index < len(current)):
                    return False
                current = current[index]
            elif isinstance(current, Mapping) and token in current:
                current = current[token]
            else:
                return False
        last = tokens[-1]
        kind, index = self._parse_index(last)
        if kind == "index" and isinstance(current, list) and index is not None and 0 <= index < len(current):
            del current[index]
            return True
        if isinstance(current, MutableMapping) and last in current:
            del current[last]
            return True
        return False

    @staticmethod
    def _deep_merge(base: Any, overlay: Any) -> Any:
        if isinstance(base, Mapping) and isinstance(overlay, Mapping):
            result = copy.deepcopy(base)
            for key, value in overlay.items():
                if key in result and isinstance(result[key], Mapping) and isinstance(value, Mapping):
                    result[key] = RimeYamlEngine._deep_merge(result[key], value)
                else:
                    result[key] = copy.deepcopy(value)
            return result
        return copy.deepcopy(overlay)

    def apply_patch(self, schema: Any, patch: Any) -> Any:
        """解析常见 Rime patch：嵌套字典、扁平路径、/+、@索引。"""
        effective = copy.deepcopy(schema if schema is not None else {})
        if not isinstance(patch, Mapping):
            return effective

        # 先应用无斜杠的普通嵌套块，再应用扁平路径，保证扁平路径优先。
        for key, value in patch.items():
            key_text = str(key)
            if "/" in key_text:
                continue
            if isinstance(value, Mapping) and isinstance(effective, Mapping):
                effective[key_text] = self._deep_merge(effective.get(key_text, {}), value)
            elif isinstance(effective, MutableMapping):
                effective[key_text] = copy.deepcopy(value)

        for key, value in patch.items():
            path = str(key)
            if "/" not in path:
                continue
            if path.endswith("/+"):
                target_path = path[:-2]
                existing = self.get_path(effective, target_path, [])
                existing_list = list(existing) if isinstance(existing, Sequence) and not isinstance(existing, (str, bytes)) else []
                append_values = list(value) if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else [value]
                self.set_path(effective, target_path, existing_list + copy.deepcopy(append_values))
            else:
                self.set_path(effective, path, value)
        return effective

    def dump_text(self, data: Any) -> str:
        buffer = StringIO()
        self.yaml.dump(data, buffer)
        return buffer.getvalue()

    def validate_data(self, data: Any) -> None:
        text = self.dump_text(data)
        self.safe_yaml.load(text)

    def validate_file(self, path: str) -> None:
        self.load_file(path, default={})

    def atomic_write_many(self, changes: Mapping[Path | str, Any]) -> None:
        """只对显式登记的高级配置文件执行原子写入。

        本方法不会扫描目录，也不会根据 ``.yaml`` 后缀扩大处理范围。
        ``*.dict.yaml``、user.yaml、installation.yaml 等均会被硬拒绝。
        ``None`` 表示删除目标补丁文件。
        """
        normalized = {Path(path): value for path, value in changes.items()}
        for path in normalized:
            if not is_managed_config_yaml(path):
                raise RimeYamlError(
                    f"高级设置拒绝写入未登记文件：{path.name}",
                    file_path=str(path),
                )

        backups: Dict[Path, Optional[bytes]] = {}
        temp_paths: Dict[Path, Path] = {}

        try:
            for path, value in normalized.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                backups[path] = path.read_bytes() if path.exists() else None
                if value is None:
                    continue

                self.validate_data(value)
                fd, tmp_name = tempfile.mkstemp(
                    prefix=f".{path.name}.",
                    suffix=".tmp",
                    dir=str(path.parent),
                )
                os.close(fd)
                tmp_path = Path(tmp_name)
                tmp_path.write_text(self.dump_text(value), encoding="utf-8")
                # 临时文件名不属于管理白名单，因此直接校验内容，不按文件名分类。
                self.safe_yaml.load(tmp_path.read_text(encoding="utf-8"))
                temp_paths[path] = tmp_path

            for path, value in normalized.items():
                if value is None:
                    if path.exists():
                        path.unlink()
                else:
                    os.replace(temp_paths[path], path)

            for path, value in normalized.items():
                if value is not None and path.exists():
                    self.validate_file(str(path))
        except Exception:
            for path, original in backups.items():
                try:
                    if original is None:
                        if path.exists():
                            path.unlink()
                    else:
                        path.write_bytes(original)
                except Exception:
                    pass
            raise
        finally:
            for tmp_path in temp_paths.values():
                try:
                    if tmp_path.exists():
                        tmp_path.unlink()
                except Exception:
                    pass


class ConflictSeverity(IntEnum):
    INFO = 10
    VARIANT = 20
    WARNING = 30
    ERROR = 40


@dataclass(frozen=True)
class KeySpec:
    base_key: str
    modifiers: frozenset[str] = field(default_factory=frozenset)
    logical_symbol: str = ""
    physical_family: str = ""
    keypad: bool = False
    raw: str = ""

    @property
    def canonical(self) -> str:
        prefix = "+".join(sorted(self.modifiers))
        return f"{prefix}+{self.base_key}" if prefix else self.base_key


@dataclass(frozen=True)
class KeyClaim:
    key: KeySpec
    action: str
    context: str
    source_file: str
    yaml_path: str
    slot: str = ""
    origin: str = "disk"
    match: str = ""
    detail: str = ""

    @property
    def identity(self) -> Tuple[str, str, str, str]:
        return self.source_file, self.yaml_path, self.slot, self.action


@dataclass(frozen=True)
class KeyConflict:
    severity: ConflictSeverity
    left: KeyClaim
    right: KeyClaim
    reason: str

    def format_line(self) -> str:
        return f"[{self.right.source_file}] {self.right.yaml_path}{('[' + self.right.slot + ']') if self.right.slot else ''}: {self.reason}"


_SYMBOL_TO_NAME = {
    " ": "space", "!": "exclam", '"': "quotedbl", "#": "numbersign", "$": "dollar",
    "%": "percent", "&": "ampersand", "'": "apostrophe", "(": "parenleft", ")": "parenright",
    "*": "asterisk", "+": "plus", ",": "comma", "-": "minus", ".": "period", "/": "slash",
    ":": "colon", ";": "semicolon", "<": "less", "=": "equal", ">": "greater", "?": "question",
    "@": "at", "[": "bracketleft", "\\": "backslash", "]": "bracketright", "^": "asciicircum",
    "_": "underscore", "`": "grave", "{": "braceleft", "|": "bar", "}": "braceright", "~": "asciitilde",
}

_SHIFTED = {
    "!": "1", "@": "2", "#": "3", "$": "4", "%": "5", "^": "6", "&": "7", "*": "8", "(": "9", ")": "0",
    "_": "minus", "+": "equal", "{": "bracketleft", "}": "bracketright", "|": "backslash",
    ":": "semicolon", '"': "apostrophe", "<": "comma", ">": "period", "?": "slash", "~": "grave",
}

_NAME_TO_SYMBOL = {value: key for key, value in _SYMBOL_TO_NAME.items()}
_NAME_TO_SYMBOL.update({
    "return": "\n", "enter": "\n", "tab": "\t", "escape": "", "esc": "",
})

_MODIFIER_ALIASES = {
    "ctrl": "control", "control": "control", "shift": "shift", "alt": "alt",
    "super": "super", "meta": "super", "command": "super", "cmd": "super",
}

_CONTEXT_SUPERSETS = {
    "always": {"always", "composing", "has_menu", "paging", "predicting", "accepting"},
    "composing": {"composing", "has_menu", "paging", "predicting", "accepting"},
    "has_menu": {"has_menu", "paging", "predicting"},
    "paging": {"paging"},
    "predicting": {"predicting"},
    "accepting": {"accepting"},
}


class RimeKeyConflictEngine:
    def __init__(self, yaml_engine: Optional[RimeYamlEngine] = None) -> None:
        self.yaml_engine = yaml_engine or RimeYamlEngine()

    def normalize_key(self, value: Any) -> Optional[KeySpec]:
        if value is None:
            return None
        raw = str(value).strip()
        if not raw:
            return None

        text = raw.replace("-", "+") if re.match(r"^(?:(?:Ctrl|Control|Shift|Alt|Meta|Super|Command|Cmd)-)+", raw, re.I) else raw
        parts = [part.strip() for part in text.split("+") if part.strip()]
        modifiers = set()
        key_text = parts[-1] if parts else text
        for part in parts[:-1]:
            alias = _MODIFIER_ALIASES.get(part.lower())
            if alias:
                modifiers.add(alias)

        low = key_text.lower()
        keypad = low.startswith("kp_")
        if keypad:
            base_key = low
            family = low[3:]
            symbol = family if len(family) == 1 else ""
            return KeySpec(base_key, frozenset(modifiers), symbol, family, True, raw)

        if len(key_text) == 1:
            symbol = key_text
            if symbol in _SHIFTED:
                modifiers.add("shift")
                base_key = _SHIFTED[symbol]
                family = base_key
            elif symbol.isalpha():
                base_key = symbol.lower()
                family = base_key
                if symbol.isupper():
                    modifiers.add("shift")
            elif symbol.isdigit():
                base_key = symbol
                family = symbol
            else:
                base_key = _SYMBOL_TO_NAME.get(symbol, symbol.lower())
                family = base_key
            return KeySpec(base_key, frozenset(modifiers), symbol, family, False, raw)

        named_shift_base = {
            "less": "comma", "greater": "period", "colon": "semicolon", "question": "slash",
            "plus": "equal", "underscore": "minus", "braceleft": "bracketleft", "braceright": "bracketright",
            "bar": "backslash", "asciitilde": "grave", "exclam": "1", "at": "2", "numbersign": "3",
            "dollar": "4", "percent": "5", "asciicircum": "6", "ampersand": "7", "asterisk": "8",
            "parenleft": "9", "parenright": "0", "quotedbl": "apostrophe",
        }
        if low in named_shift_base:
            modifiers.add("shift")
            base_key = named_shift_base[low]
            return KeySpec(base_key, frozenset(modifiers), _NAME_TO_SYMBOL.get(low, ""), base_key, False, raw)

        base_key = low
        symbol = _NAME_TO_SYMBOL.get(low, "")
        family = base_key
        return KeySpec(base_key, frozenset(modifiers), symbol, family, False, raw)

    def parse_key_slots(self, value: Any, expected: int = 2) -> List[Optional[KeySpec]]:
        values: List[Any] = []
        if isinstance(value, Mapping):
            for key in ("first", "left", "head", "0", "last", "right", "tail", "1"):
                if key in value:
                    values.append(value[key])
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            values = list(value)
        else:
            text = str(value or "").strip()
            if text:
                # Rime 常见简写 "[,]" 表示左中括号和右中括号两个独立槽位。
                if len(text) == 3 and text[1] == ",":
                    values = [text[0], text[2]]
                    text = ""
                parsed = None
                if text and ((text.startswith("[") and text.endswith("]")) or (text.startswith("{") and text.endswith("}"))):
                    try:
                        parsed = self.yaml_engine.safe_yaml.load(text)
                    except Exception:
                        parsed = None
                if values:
                    pass
                elif isinstance(parsed, Sequence) and not isinstance(parsed, (str, bytes)):
                    values = list(parsed)
                elif "," in text:
                    values = [part.strip() for part in text.strip("[](){}").split(",")]
                elif " " in text:
                    values = [part for part in text.split() if part]
                elif len(text) == expected and all(ch not in "+" for ch in text):
                    values = list(text)
                else:
                    values = [text]

        result = [self.normalize_key(value) for value in values[:expected]]
        while len(result) < expected:
            result.append(None)
        return result

    @staticmethod
    def contexts_overlap(left: str, right: str) -> bool:
        a = (left or "always").strip().lower()
        b = (right or "always").strip().lower()
        if a == b:
            return True
        if a not in _CONTEXT_SUPERSETS or b not in _CONTEXT_SUPERSETS:
            return True
        return b in _CONTEXT_SUPERSETS[a] or a in _CONTEXT_SUPERSETS[b]

    def _claims_for_binding(self, binding: Mapping[str, Any], source_file: str, index: int, origin: str) -> List[KeyClaim]:
        accept = binding.get("accept")
        key = self.normalize_key(accept)
        if key is None:
            return []
        action = ""
        for field_name in ("send", "send_sequence", "toggle", "select", "set_option", "unset_option"):
            if field_name in binding:
                action = f"{field_name}:{binding.get(field_name)}"
                break
        if not action:
            action = "binding"
        return [KeyClaim(
            key=key,
            action=action.lower(),
            context=str(binding.get("when", "always")),
            source_file=source_file,
            yaml_path=f"key_binder/bindings/@{index}",
            origin=origin,
            match=str(binding.get("match", "")),
            detail=str(dict(binding)),
        )]

    def collect_claims(self, effective: Any, source_file: str, *, origin: str = "disk") -> List[KeyClaim]:
        claims: List[KeyClaim] = []
        if not isinstance(effective, Mapping):
            return claims

        for path, action in (
            ("speller/alphabet", "input_alphabet"),
            ("speller/delimiter", "speller_delimiter"),
            ("speller/initials", "speller_initials"),
        ):
            value = self.yaml_engine.get_path(effective, path, "")
            for index, symbol in enumerate(str(value or "")):
                key = self.normalize_key(symbol)
                if key:
                    claims.append(KeyClaim(key, action, "composing", source_file, path, str(index), origin))

        bindings = self.yaml_engine.get_path(effective, "key_binder/bindings", [])
        if isinstance(bindings, Sequence) and not isinstance(bindings, (str, bytes)):
            for index, binding in enumerate(bindings):
                if isinstance(binding, Mapping):
                    claims.extend(self._claims_for_binding(binding, source_file, index, origin))

        select_value = self.yaml_engine.get_path(effective, "super_processor/select_character", _MISSING)
        if select_value is not _MISSING:
            slots = self.parse_key_slots(select_value, 2)
            slot_names = ("first", "last")
            actions = ("select_first_character", "select_last_character")
            for slot_name, action, key in zip(slot_names, actions, slots):
                if key:
                    claims.append(KeyClaim(key, action, "has_menu", source_file, "super_processor/select_character", slot_name, origin))

        known_paths = (
            ("wanxiang_lookup/key", "reverse_lookup"),
            ("wanxiang_reverse/prefix", "reverse_prefix"),
            ("super_tips/tips_key", "super_tips"),
            ("force_upper_aux/hotkey", "force_upper_aux"),
            ("wanxiang_english/trigger", "english_trigger"),
        )
        for path, action in known_paths:
            value = self.yaml_engine.get_path(effective, path, _MISSING)
            if value is _MISSING:
                continue
            key = self.normalize_key(value)
            if key:
                claims.append(KeyClaim(key, action, "composing", source_file, path, origin=origin))

        return claims

    @staticmethod
    def _same_exact_key(left: KeySpec, right: KeySpec) -> bool:
        return left.base_key == right.base_key and left.modifiers == right.modifiers and left.keypad == right.keypad

    @staticmethod
    def _same_physical_family(left: KeySpec, right: KeySpec) -> bool:
        return left.physical_family == right.physical_family and left.physical_family != ""

    @staticmethod
    def _canonical_action(action: str) -> str:
        raw = str(action or "").strip().lower()
        ui_map = {
            "ui:super_tips/tips_key": "super_tips",
            "ui:wanxiang_english/trigger": "english_trigger",
            "ui:wanxiang_lookup/key": "reverse_lookup",
            "ui:wanxiang_reverse/prefix": "reverse_prefix",
            "ui:force_upper_aux/hotkey": "force_upper_aux",
        }
        return ui_map.get(raw, raw)

    @classmethod
    def _cooperative_actions(cls, left: str, right: str) -> bool:
        a = cls._canonical_action(left)
        b = cls._canonical_action(right)
        pair = frozenset((a, b))

        # 这些并不是竞争关系，而是一个功能正常生效所需的协同配置。
        cooperative_pairs = {
            frozenset(("reverse_lookup", "reverse_prefix")),
            frozenset(("input_alphabet", "reverse_lookup")),
            frozenset(("input_alphabet", "reverse_prefix")),
            frozenset(("input_alphabet", "english_trigger")),
            frozenset(("input_alphabet", "force_upper_aux")),
        }
        return pair in cooperative_pairs

    def compare(self, left: KeyClaim, right: KeyClaim) -> Optional[KeyConflict]:
        if left.identity == right.identity and left.origin == right.origin:
            return None

        left_action = self._canonical_action(left.action)
        right_action = self._canonical_action(right.action)

        if self._same_exact_key(left.key, right.key):
            if left_action == right_action:
                return KeyConflict(ConflictSeverity.INFO, left, right, "同一功能的界面值与已加载值一致")
            if self._cooperative_actions(left_action, right_action):
                return KeyConflict(ConflictSeverity.INFO, left, right, "同一按键用于同一功能链路的协同配置")
            if not self.contexts_overlap(left.context, right.context):
                return KeyConflict(ConflictSeverity.INFO, left, right, "同键但静态上下文明确分离")

            reason = "该按键被不同配置复用；实际是否冲突取决于输入状态、处理顺序或 Lua 内部条件"
            if left.match or right.match:
                reason += "（含 match 条件）"
            # 静态 YAML 无法证明运行时必然冲突，因此最高只作为审计警告。
            return KeyConflict(ConflictSeverity.WARNING, left, right, reason)

        if self._same_physical_family(left.key, right.key):
            if left.key.keypad != right.key.keypad:
                return KeyConflict(ConflictSeverity.INFO, left, right, "主键区与小键盘属于关联键，不视为完全冲突")
            return KeyConflict(ConflictSeverity.VARIANT, left, right, "同一物理键的 Shift/修饰变种，仅供检查")
        return None

    def detect(self, claims: Sequence[KeyClaim]) -> List[KeyConflict]:
        conflicts: List[KeyConflict] = []
        seen = set()
        for left_index, left in enumerate(claims):
            for right in claims[left_index + 1:]:
                conflict = self.compare(left, right)
                if conflict is None:
                    continue
                signature = (
                    conflict.severity,
                    conflict.left.identity,
                    conflict.right.identity,
                    conflict.reason,
                )
                if signature not in seen:
                    seen.add(signature)
                    conflicts.append(conflict)
        return sorted(conflicts, key=lambda item: (-int(item.severity), item.right.source_file, item.right.yaml_path, item.right.slot))

    def find_for_targets(
        self,
        target_keys: Iterable[Any],
        claims: Sequence[KeyClaim],
        *,
        ignore_actions: Iterable[str] = (),
        check_alphabet: bool = True,
        source_file: str = "<界面实时值>",
    ) -> List[KeyConflict]:
        ignored = {str(value).lower() for value in ignore_actions}
        targets: List[KeyClaim] = []
        for index, value in enumerate(target_keys):
            key = self.normalize_key(value)
            if key:
                targets.append(KeyClaim(key, "ui_target", "always", source_file, "ui/live", str(index), "ui"))

        results: List[KeyConflict] = []
        for target in targets:
            for claim in claims:
                action_tail = claim.action.split(":", 1)[-1].lower()
                if action_tail in ignored or claim.action.lower() in ignored:
                    continue
                if not check_alphabet and claim.action in {"input_alphabet", "speller_delimiter", "speller_initials"}:
                    continue
                conflict = self.compare(target, claim)
                if conflict and conflict.severity >= ConflictSeverity.VARIANT:
                    results.append(conflict)
        unique: Dict[Tuple[Any, ...], KeyConflict] = {}
        for conflict in results:
            key = (conflict.severity, conflict.right.identity, conflict.reason, conflict.left.key.canonical)
            unique[key] = conflict
        return sorted(unique.values(), key=lambda item: (-int(item.severity), item.right.source_file, item.right.yaml_path, item.right.slot))


class LiveKeyRegistry:
    """保存尚未落盘的界面按键占用，后写入者覆盖同 owner 的旧声明。"""

    def __init__(self) -> None:
        self._claims: Dict[str, List[KeyClaim]] = {}

    def set_claims(self, owner: str, claims: Iterable[KeyClaim]) -> None:
        self._claims[str(owner)] = list(claims)

    def clear(self, owner: Optional[str] = None) -> None:
        if owner is None:
            self._claims.clear()
        else:
            self._claims.pop(str(owner), None)

    def all_claims(self) -> List[KeyClaim]:
        result: List[KeyClaim] = []
        for owner in sorted(self._claims):
            result.extend(self._claims[owner])
        return result


def is_rime_config_yaml(path: Path | str) -> bool:
    """兼容旧接口：仅返回高级设置明确登记的纯 YAML 配置。"""
    return is_managed_config_yaml(path)


class SaveTransaction:
    """显式文件事务。

    调用方必须把本次允许修改的完整路径列表传进来。事务不会 glob、不会扫描
    目录、不会碰触未列入计划的文件。这样词典、用户数据和安装信息天然隔离。
    """

    def __init__(self, paths: Iterable[Path | str]) -> None:
        self.paths = tuple(sorted({Path(path) for path in paths}, key=lambda item: str(item)))
        self.snapshot: Dict[Path, Optional[bytes]] = {}
        self._committed = False

    def __enter__(self) -> "SaveTransaction":
        for path in self.paths:
            self.snapshot[path] = path.read_bytes() if path.exists() else None
        return self

    def changed_paths(self) -> List[Path]:
        changed: List[Path] = []
        for path in self.paths:
            original = self.snapshot.get(path)
            if original is None:
                if path.exists():
                    changed.append(path)
                continue
            if not path.exists():
                changed.append(path)
                continue
            try:
                if path.read_bytes() != original:
                    changed.append(path)
            except OSError:
                changed.append(path)
        return changed

    def commit(self) -> None:
        self._committed = True

    def rollback(self) -> None:
        for path, original in self.snapshot.items():
            try:
                if original is None:
                    if path.exists():
                        path.unlink()
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(original)
            except Exception:
                pass

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is not None or not self._committed:
            self.rollback()
        return False

