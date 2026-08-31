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


class _RootNodeRef:
    """可替换的根节点引用。

    librime 的 EditNode() 操作的是 ConfigItemRef，因此 path 为空时也能直接
    替换当前节点。Python 的 list/dict 只是值对象，不能用赋值替换调用方持有的
    根对象；这里用一层引用盒模拟 ConfigItemRef。
    """

    __slots__ = ("value",)

    def __init__(self, value: Any) -> None:
        self.value = value


# 高级设置只允许接触原始代码 FILE_INDEX_META 中登记的纯配置文件。
# 这是硬边界，不使用“只要后缀是 .yaml 就处理”的泛化规则。
MANAGED_RIME_SOURCE_FILES = frozenset({
    "default.yaml",
    "wanxiang_algebra.yaml",
    "wanxiang.schema.yaml",
    "wanxiang_pro.schema.yaml",
    "wanxiang_lite.schema.yaml",
    "wanxiang_english.schema.yaml",
    "wanxiang_mixedcode.schema.yaml",
    "wanxiang_reverse.schema.yaml",
    "wanxiang_t9.schema.yaml",
    "wanxiang_t9i.schema.yaml",
})

MANAGED_RIME_CUSTOM_FILES = frozenset({
    "default.custom.yaml",
    "wanxiang.custom.yaml",
    "wanxiang_pro.custom.yaml",
    "wanxiang_lite.custom.yaml",
    "wanxiang_english.custom.yaml",
    "wanxiang_mixedcode.custom.yaml",
    "wanxiang_reverse.custom.yaml",
    "wanxiang_t9.custom.yaml",
    "wanxiang_t9i.custom.yaml",
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
    source_effective: Any
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

        # Rime ConfigCompiler 兼容层的单次编译状态。
        # raw / compiled 严格分离：编译结果只供读取，不参与原文件回写。
        self._compile_root = Path.cwd()
        self._raw_resource_cache: Dict[str, Any] = {}
        self._compiled_resource_cache: Dict[str, Any] = {}
        self._compiled_reference_cache: Dict[Tuple[str, str], Any] = {}
        self._compile_stack: List[Tuple[str, str]] = []

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

    @staticmethod
    def _custom_path_for_source(path: Path) -> Path:
        name = path.name
        if name.endswith(".custom.yaml"):
            return path
        if name.endswith(".schema.yaml"):
            return path.with_name(name[:-len(".schema.yaml")] + ".custom.yaml")
        if name.endswith(".yaml"):
            return path.with_name(name[:-len(".yaml")] + ".custom.yaml")
        return path.with_name(name + ".custom.yaml")

    def _begin_compile_session(self, root_dir: Path | str) -> None:
        self._compile_root = Path(root_dir).resolve()
        self._raw_resource_cache.clear()
        self._compiled_resource_cache.clear()
        self._compiled_reference_cache.clear()
        self._compile_stack.clear()

    def begin_compile_session(self, root_dir: Path | str) -> None:
        """开始一次目录级 Rime 编译会话。

        同一次目录扫描中的多个 schema 共用 raw / compiled / reference 缓存，
        避免 default、wanxiang_algebra、symbols 等共享资源被每个方案重复编译。
        文件发生外部变化或用户主动重新扫描时，应重新开始会话。
        """
        self._begin_compile_session(root_dir)

    def _resource_path(self, resource_id: str, current_file: Path) -> Path:
        """按 Rime ResourceResolver 的常见配置资源写法定位 YAML。

        外部引用可写 config:/node、config.yaml:/node；省略的仅是末尾 .yaml。
        高级设置只在当前 Rime 目录及当前文件目录中解析资源，不越界扫描磁盘。
        """
        resource_id = str(resource_id or "").strip()
        if not resource_id:
            return current_file.resolve()

        candidate = Path(resource_id)
        if not str(candidate).endswith(".yaml"):
            candidate = Path(str(candidate) + ".yaml")

        if candidate.is_absolute():
            return candidate.resolve()

        candidates = [
            (current_file.parent / candidate).resolve(),
            (self._compile_root / candidate).resolve(),
        ]
        for path in candidates:
            if path.exists():
                return path
        return candidates[-1]

    def _parse_reference(self, text: str, current_file: Path) -> Tuple[Path, str, bool]:
        """复刻 ConfigCompiler::CreateReference() 的资源/局部路径拆分。"""
        ref = str(text or "").strip()
        optional = ref.endswith("?")
        if optional:
            ref = ref[:-1]

        if ":" in ref:
            resource_id, local_path = ref.split(":", 1)
            resource_path = self._resource_path(resource_id, current_file)
        else:
            resource_path = current_file.resolve()
            local_path = ref

        if local_path == "/":
            local_path = ""
        return resource_path, local_path, optional

    def _load_resource_raw(self, path: Path) -> Any:
        key = str(path.resolve())
        if key not in self._raw_resource_cache:
            self._raw_resource_cache[key] = self.load_file(key, default={})
        return self._raw_resource_cache[key]

    def _raw_node(self, raw_root: Any, path: str) -> Any:
        if path in {"", "/"}:
            return raw_root
        return self.get_path(raw_root, path, _MISSING)

    def _resolve_reference(self, reference: str, current_file: Path) -> Tuple[bool, Any]:
        resource_path, local_path, optional = self._parse_reference(reference, current_file)
        resource_key = str(resource_path.resolve())
        cache_key = (resource_key, local_path or "")

        if cache_key in self._compiled_reference_cache:
            return True, copy.deepcopy(self._compiled_reference_cache[cache_key])

        if not resource_path.exists():
            if optional:
                return False, None
            raise RimeYamlError(
                f"Rime 引用资源不存在：{reference} -> {resource_path}",
                file_path=str(current_file),
            )

        if cache_key in self._compile_stack:
            chain = " -> ".join(
                f"{Path(file_name).name}:{node_path or '/'}"
                for file_name, node_path in self._compile_stack + [cache_key]
            )
            raise RimeYamlError(
                f"Rime 配置存在循环引用：{chain}",
                file_path=str(current_file),
            )

        # 外部资源与 librime 一样先完整 Compile，再从编译结果取引用节点；
        # 因而它自己的 <config>.custom.yaml 也会先自动生效。
        if resource_path.resolve() != current_file.resolve():
            compiled_root = self._compile_resource(
                resource_path,
                auto_custom=not resource_path.name.endswith(".custom.yaml"),
            )
            compiled = self.get_path(compiled_root, local_path, _MISSING)
            if compiled is _MISSING:
                if optional:
                    return False, None
                raise RimeYamlError(
                    f"Rime 引用节点不存在：{reference}",
                    file_path=str(resource_path),
                )
            self._compiled_reference_cache[cache_key] = copy.deepcopy(compiled)
            return True, compiled

        # 同资源局部引用不能重新编译整个根节点，否则会制造伪循环；
        # 直接对原始节点建立依赖并编译，等价于 ConfigCompiler 的本资源引用。
        raw_root = self._load_resource_raw(resource_path)
        raw_node = self._raw_node(raw_root, local_path)
        if raw_node is _MISSING:
            if optional:
                return False, None
            raise RimeYamlError(
                f"Rime 引用节点不存在：{reference}",
                file_path=str(resource_path),
            )

        self._compile_stack.append(cache_key)
        try:
            compiled = self._compile_node(
                raw_node,
                current_file=resource_path,
                node_path=local_path or "",
            )
        finally:
            self._compile_stack.pop()

        self._compiled_reference_cache[cache_key] = copy.deepcopy(compiled)
        return True, compiled

    def _compile_patch_value(self, value: Any, *, current_file: Path, node_path: str) -> Any:
        # Patch literal 本身也是 YAML 节点树；其 value 中仍可出现编译指令。
        if isinstance(value, Mapping):
            # ConvertFromYaml 会照常解析 patch literal 内部出现的编译指令。
            return self._compile_node(
                value, current_file=current_file, node_path=node_path
            )
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return [
                self._compile_patch_value(
                    child, current_file=current_file, node_path=f"{node_path}/@{index}".strip("/")
                )
                if isinstance(child, (Mapping, list, tuple)) else copy.deepcopy(child)
                for index, child in enumerate(value)
            ]
        return copy.deepcopy(value)

    def _apply_patch_directive(self, target: Any, directive: Any, *, current_file: Path) -> Any:
        """解析 __patch: literal / reference / sequence，按列表顺序执行。"""
        items = (
            list(directive)
            if isinstance(directive, Sequence) and not isinstance(directive, (str, bytes, bytearray, Mapping))
            else [directive]
        )
        result = copy.deepcopy(target)

        for item in items:
            if isinstance(item, str):
                found, patch_node = self._resolve_reference(item, current_file)
                if not found:
                    continue
                if not isinstance(patch_node, Mapping):
                    raise RimeYamlError(
                        f"__patch 引用必须指向 map：{item}",
                        file_path=str(current_file),
                    )
                result = self.apply_patch(result, patch_node)
            elif isinstance(item, Mapping):
                result = self.apply_patch(result, item)
            else:
                raise RimeYamlError(
                    "__patch 只接受补丁 map、节点引用，或它们组成的列表",
                    file_path=str(current_file),
                )
        return result

    def _implicit_import_preset(self, raw: Mapping[str, Any], node_path: str) -> Optional[str]:
        """实现 Rime 组件 import_preset 插件的常见形式。

        <component>/import_preset: <config>
        等价于在该根组件节点先 __include: <config>:/<component>。
        """
        preset = raw.get("import_preset")
        tokens = self._tokenize(node_path)
        if (
            isinstance(preset, str)
            and len(tokens) == 1
            and not self._is_list_reference(tokens[0])
        ):
            return f"{preset}:/{tokens[0]}"
        return None

    def _compile_node(self, raw: Any, *, current_file: Path, node_path: str) -> Any:
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray, Mapping)):
            return [
                self._compile_node(
                    child,
                    current_file=current_file,
                    node_path=f"{node_path}/@{index}".strip("/"),
                )
                for index, child in enumerate(raw)
            ]

        if not isinstance(raw, Mapping):
            return copy.deepcopy(raw)

        explicit_include = raw.get("__include", _MISSING)
        implicit_include = self._implicit_import_preset(raw, node_path)
        include_value = explicit_include if explicit_include is not _MISSING else implicit_include
        patch_value = raw.get("__patch", _MISSING)

        # PendingChild：先解析普通子节点中的依赖，再处理本节点 include / patch。
        literals: Dict[str, Any] = {}
        for key, child in raw.items():
            key_text = str(key)
            if key_text in {"__include", "__patch"}:
                continue
            if implicit_include is not None and key_text == "import_preset":
                continue
            literals[key_text] = self._compile_node(
                child,
                current_file=current_file,
                node_path=f"{node_path}/{key_text}".strip("/"),
            )

        result: Any = literals

        # 同一节点固定顺序：include -> 合并字面值 -> patch。
        if include_value is not _MISSING and include_value is not None:
            if not isinstance(include_value, str):
                raise RimeYamlError(
                    "__include 只接受一个节点引用字符串",
                    file_path=str(current_file),
                )
            found, included = self._resolve_reference(include_value, current_file)
            if found:
                holder = {"__rime_target__": copy.deepcopy(included)}
                if literals:
                    if not self._merge_tree(holder, "__rime_target__", literals):
                        raise RimeYamlError(
                            f"__include 后无法合并当前节点：{include_value}",
                            file_path=str(current_file),
                        )
                result = holder["__rime_target__"]

        if patch_value is not _MISSING and patch_value is not None:
            compiled_patch = self._compile_patch_value(
                patch_value,
                current_file=current_file,
                node_path=f"{node_path}/__patch".strip("/"),
            )
            result = self._apply_patch_directive(
                result, compiled_patch, current_file=current_file
            )

        return result

    def _compile_resource(self, source_path: Path, *, auto_custom: bool = True) -> Any:
        source_path = source_path.resolve()
        resource_key = str(source_path)
        cache_key = resource_key + ("|custom" if auto_custom else "|raw")
        if cache_key in self._compiled_resource_cache:
            return copy.deepcopy(self._compiled_resource_cache[cache_key])

        root_marker = (resource_key, "")
        if root_marker in self._compile_stack:
            raise RimeYamlError(
                f"Rime 配置存在循环资源引用：{source_path.name}",
                file_path=str(source_path),
            )

        raw_key = str(source_path.resolve())
        if raw_key in self._raw_resource_cache:
            raw = self._raw_resource_cache[raw_key]
        else:
            raw = self._load_resource_raw(source_path)
        self._compile_stack.append(root_marker)
        try:
            result = self._compile_node(raw, current_file=source_path, node_path="")
        finally:
            self._compile_stack.pop()

        # AutoPatchConfigPlugin：根节点没有显式 __patch 时，自动应用 <config>.custom:/patch?。
        if (
            auto_custom
            and isinstance(raw, Mapping)
            and "__patch" not in raw
            and not source_path.name.endswith(".custom.yaml")
        ):
            custom_path = self._custom_path_for_source(source_path)
            custom_key = str(custom_path.resolve())
            if custom_path.exists() or custom_key in self._raw_resource_cache:
                custom_compiled = self._compile_resource(custom_path, auto_custom=False)
                patch_node = (
                    custom_compiled.get("patch", _MISSING)
                    if isinstance(custom_compiled, Mapping) else _MISSING
                )
                if patch_node is not _MISSING and patch_node is not None:
                    if not isinstance(patch_node, Mapping):
                        raise RimeYamlError(
                            f"{custom_path.name}:/patch 必须是 map",
                            file_path=str(custom_path),
                        )
                    result = self.apply_patch(result, patch_node)

        # DefaultConfigPlugin：输入方案未定义 menu/page_size 时，从已编译的 default.yaml 继承。
        if source_path.name.endswith(".schema.yaml"):
            page_size = self.get_path(result, "menu/page_size", _MISSING)
            if page_size is _MISSING:
                default_path = (self._compile_root / "default.yaml").resolve()
                if default_path.exists() and default_path != source_path:
                    default_compiled = self._compile_resource(default_path, auto_custom=True)
                    inherited = self.get_path(default_compiled, "menu/page_size", _MISSING)
                    if inherited is not _MISSING:
                        self.set_path(result, "menu/page_size", inherited)

        self._compiled_resource_cache[cache_key] = copy.deepcopy(result)
        return result

    def compile_file(self, path: str, *, auto_custom: bool = True) -> Any:
        """编译一个 Rime 配置源文件，返回不含编译指令的最终节点树。"""
        source_path = Path(path).resolve()
        self._begin_compile_session(source_path.parent)
        return self._compile_resource(source_path, auto_custom=auto_custom)

    def load_pair(self, schema_path: str, custom_path: str = "", *, reuse_compile_session: bool = False) -> LoadedRimeDocument:
        """加载 raw schema/custom，并独立生成 Rime 编译后的 effective。

        schema / patch 保持原始结构供保存；effective 只读，绝不反写。
        """
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

        schema_path_obj = Path(schema_path).resolve()
        compile_root = schema_path_obj.parent.resolve()

        # 单文件读取默认开启全新会话；批量扫描可显式复用同目录会话。
        if (
            not reuse_compile_session
            or self._compile_root != compile_root
        ):
            self._begin_compile_session(compile_root)
        else:
            # 上一个资源若异常退出，不能把依赖栈泄漏给下一个顶层 schema。
            self._compile_stack.clear()

        schema_key = str(schema_path_obj)
        if reuse_compile_session and schema_key in self._raw_resource_cache:
            schema = copy.deepcopy(self._raw_resource_cache[schema_key])
        else:
            schema = self.load_file(str(schema_path_obj), default={})
            self._raw_resource_cache[schema_key] = copy.deepcopy(schema)

        custom_obj = Path(custom_path).resolve() if custom_path and Path(custom_path).exists() else None
        if custom_obj is not None:
            custom_key = str(custom_obj)
            if reuse_compile_session and custom_key in self._raw_resource_cache:
                custom = copy.deepcopy(self._raw_resource_cache[custom_key])
            else:
                custom = self.load_file(str(custom_obj), default={})
                self._raw_resource_cache[custom_key] = copy.deepcopy(custom)
        else:
            custom = {}

        patch = custom.get("patch", {}) if isinstance(custom, Mapping) else {}
        patch = patch or {}

        # source_effective：只按 Rime literal patch 将 schema + custom 合成，
        # 但保留 __include / __patch 等编译指令。它用于编辑“编译指令本身”的 UI。
        # runtime effective 则继续由完整 ConfigCompiler 兼容层生成。
        source_effective = self.apply_patch(schema, patch)

        # 如果调用方给了非标准 custom 路径，仍以它作为当前 schema 的自动补丁资源。
        derived_custom = self._custom_path_for_source(schema_path_obj)
        if custom_obj is not None and custom_obj != derived_custom:
            self._raw_resource_cache[str(derived_custom)] = copy.deepcopy(custom)

        effective = self._compile_resource(schema_path_obj, auto_custom=True)

        return LoadedRimeDocument(
            file_name=schema_path_obj.name,
            schema_path=str(schema_path_obj),
            custom_path=custom_path,
            schema=schema,
            patch=patch,
            source_effective=source_effective,
            effective=effective,
        )

    @staticmethod
    def _tokenize(path: str) -> List[str]:
        """按 librime ConfigData::SplitPath() 规则切分配置路径。"""
        text = str(path or "").lstrip("/")
        if text == "":
            return []
        return text.split("/")

    @staticmethod
    def _is_list_reference(token: str) -> bool:
        """对应 ConfigData::IsListItemReference()：@ 后首字符为 ASCII 字母/数字。"""
        if len(token) <= 1 or token[0] != "@":
            return False
        ch = token[1]
        return ("0" <= ch <= "9") or ("A" <= ch <= "Z") or ("a" <= ch <= "z")

    @staticmethod
    def _parse_list_reference(token: str, size: int) -> Tuple[int, bool]:
        """复刻 ConfigData::ResolveListIndex() 的索引计算。

        返回 (index, will_insert)。
        支持：
          @0 / @12
          @last
          @next
          @before 0 / @before last
          @after 0 / @after last
        """
        if not RimeYamlEngine._is_list_reference(token):
            raise ValueError(f"不是 Rime 列表路径：{token}")

        body = token[1:]
        index = 0
        will_insert = False

        if body.startswith("next"):
            # librime 中 @next 直接定位 size，不额外 Insert；
            # 后续 SetAt(size) 会自然扩展为末尾新项。
            body = body[4:]
            index = size
        elif body.startswith("before"):
            body = body[6:]
            will_insert = True
        elif body.startswith("after"):
            body = body[5:]
            index += 1
            will_insert = True

        if body.startswith(" "):
            body = body[1:]

        if body.startswith("last"):
            index += size
            if index != 0:
                index -= 1
            body = body[4:]
        else:
            # std::strtoul() 对空串/非法起始内容得到 0；
            # 这里保留 Rime 对合法配置的行为，同时拒绝明显拼错的列表表达式，
            # 避免工具静默把 typo 当 @0。
            match = re.match(r"^[0-9]+", body)
            if match:
                index += int(match.group(0))
            elif token not in {"@next", "@last"}:
                raise ValueError(f"无效的 Rime 列表路径：{token}")

        return index, will_insert

    @staticmethod
    def _node_kind_for_token(token: str) -> str:
        return "list" if RimeYamlEngine._is_list_reference(token) else "map"

    @staticmethod
    def _resize_list(items: list, size: int) -> None:
        if len(items) < size:
            items.extend([None] * (size - len(items)))

    def _resolve_list_for_read(self, items: Any, token: str) -> Optional[int]:
        if not isinstance(items, list):
            return None
        try:
            index, _ = self._parse_list_reference(token, len(items))
        except ValueError:
            return None
        return index if 0 <= index < len(items) else None

    @staticmethod
    def _root_value(data: Any) -> Any:
        return data.value if isinstance(data, _RootNodeRef) else data

    @staticmethod
    def _is_empty_node(value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, (Mapping, list, tuple, str, bytes, bytearray)):
            return len(value) == 0
        return False

    def get_path(self, data: Any, path: str, default: Any = None) -> Any:
        """读取 Rime 配置路径；空路径表示当前根节点本身。"""
        current = self._root_value(data)
        tokens = self._tokenize(path)
        if not tokens:
            return current

        for token in tokens:
            if self._is_list_reference(token):
                index = self._resolve_list_for_read(current, token)
                if index is None:
                    return default
                current = current[index]
            elif isinstance(current, Mapping) and token in current:
                current = current[token]
            else:
                return default
        return current

    def _ensure_child(self, parent: Any, token: str, next_token: Optional[str]) -> Any:
        """写路径时取得/创建子节点，模拟 TraverseCopyOnWrite + Cow。"""
        want_list = bool(next_token and self._is_list_reference(next_token))

        if self._is_list_reference(token):
            if not isinstance(parent, list):
                raise TypeError(f"路径 {token} 需要列表父节点")

            index, will_insert = self._parse_list_reference(token, len(parent))
            if will_insert:
                # ConfigList::Insert(i, nullptr)：i 超界时先 resize(i)，再插入。
                self._resize_list(parent, index)
                parent.insert(index, None)
            else:
                # ConfigList::SetAt() 可自动扩展，包括 @next。
                self._resize_list(parent, index + 1)

            child = parent[index]
            if child is None:
                child = [] if want_list else {}
                parent[index] = child
                return child

            expected = list if want_list else Mapping
            if want_list:
                if not isinstance(child, list):
                    raise TypeError(f"路径 {token} 下级需要列表节点")
            elif not isinstance(child, Mapping):
                raise TypeError(f"路径 {token} 下级需要字典节点")
            return child

        if not isinstance(parent, MutableMapping):
            raise TypeError(f"路径 {token} 需要字典父节点")

        if token not in parent or parent[token] is None:
            parent[token] = [] if want_list else {}
            return parent[token]

        child = parent[token]
        if want_list:
            if not isinstance(child, list):
                raise TypeError(f"路径 {token} 下级需要列表节点")
        elif not isinstance(child, Mapping):
            raise TypeError(f"路径 {token} 下级需要字典节点")
        return child

    def set_path(self, data: Any, path: str, value: Any) -> None:
        """按 Rime 路径语义写值；空路径可替换 _RootNodeRef 根节点。"""
        tokens = self._tokenize(path)
        if not tokens:
            if isinstance(data, _RootNodeRef):
                data.value = copy.deepcopy(value)
                return
            raise ValueError("空路径只能用于可替换的 Rime 根节点引用")

        current = self._root_value(data)
        for idx, token in enumerate(tokens[:-1]):
            current = self._ensure_child(current, token, tokens[idx + 1])

        last = tokens[-1]
        copied = copy.deepcopy(value)

        if self._is_list_reference(last):
            if not isinstance(current, list):
                raise TypeError(f"路径 {last} 需要列表父节点")

            index, will_insert = self._parse_list_reference(last, len(current))
            if will_insert:
                self._resize_list(current, index)
                current.insert(index, None)
            else:
                self._resize_list(current, index + 1)
            current[index] = copied
            return

        if not isinstance(current, MutableMapping):
            raise TypeError(f"路径 {last} 需要字典父节点")
        current[last] = copied

    def delete_path(self, data: Any, path: str) -> bool:
        """删除路径；读取列表索引时不触发 @before/@after 的插入副作用。"""
        tokens = self._tokenize(path)
        if not tokens:
            return False

        current = self._root_value(data)
        for token in tokens[:-1]:
            if self._is_list_reference(token):
                index = self._resolve_list_for_read(current, token)
                if index is None:
                    return False
                current = current[index]
            elif isinstance(current, Mapping) and token in current:
                current = current[token]
            else:
                return False

        last = tokens[-1]
        if self._is_list_reference(last):
            index = self._resolve_list_for_read(current, last)
            if index is None or not isinstance(current, list):
                return False
            del current[index]
            return True

        if isinstance(current, MutableMapping) and last in current:
            del current[last]
            return True
        return False

    @staticmethod
    def _parse_indexed_append(key: str) -> Optional[int]:
        """对应 librime ParseIndexedAppend()：path/2+ 或纯 2+。"""
        if not key or not key.endswith("+"):
            return None
        match = re.search(r"(?:^|/)([0-9]+)\+$", key)
        return int(match.group(1)) if match else None

    @staticmethod
    def _strip_patch_operator(
        key: str,
        *,
        appending: bool,
        indexed_append: Optional[int],
    ) -> str:
        if key in {"__append", "__merge"}:
            return ""
        if indexed_append is not None:
            slash_suffix = f"/{indexed_append}+"
            plain_suffix = f"{indexed_append}+"
            if key.endswith(slash_suffix):
                return key[:-len(slash_suffix)]
            if key.endswith(plain_suffix):
                return key[:-len(plain_suffix)]
        suffix = "/+" if appending else "/="
        return key[:-len(suffix)] if key.endswith(suffix) else key

    def _append_value(
        self,
        target: Any,
        path: str,
        value: Any,
        indexed_append: Optional[int],
    ) -> bool:
        """对应 AppendToString()/AppendToList()。

        关键点：Rime 的 target 是 ConfigItemRef，所以 path 为空时也能替换
        当前节点；空节点在追加 list 时可原位转成 list。
        """
        existing = self.get_path(target, path, _MISSING)
        if existing is _MISSING or existing is None:
            self.set_path(target, path, value)
            return True

        if isinstance(value, str):
            if isinstance(existing, str) and indexed_append is None:
                self.set_path(target, path, existing + value)
                return True
            return False

        if isinstance(value, Sequence) and not isinstance(
            value, (str, bytes, bytearray, Mapping)
        ):
            incoming = copy.deepcopy(list(value))

            if isinstance(existing, list):
                result = copy.deepcopy(existing)
            elif self._is_empty_node(existing):
                # librime AppendToList(): 空节点（常见为只含编译指令、
                # 指令解析后留下的空 map）允许转换为 list。
                result = []
            else:
                return False

            if indexed_append is None:
                result.extend(incoming)
            else:
                if indexed_append > len(result):
                    return False
                result[indexed_append:indexed_append] = incoming

            self.set_path(target, path, result)
            return True

        return False

    def _merge_tree(self, target: Any, path: str, overlay: Any) -> bool:
        """对应 librime MergeTree()；子键继续按 EditNode(merge_tree=true) 解释。"""
        if not isinstance(overlay, Mapping):
            return False

        existing = self.get_path(target, path, _MISSING)
        if existing is _MISSING or existing is None:
            self.set_path(target, path, {})
            existing = self.get_path(target, path, _MISSING)

        # librime 的 MergeTree 明确允许 target 当前为任意类型；
        # 例如 include 得到 list 后，overlay 的 __append 可以直接追加。
        for child_key in sorted(overlay.keys(), key=lambda item: str(item)):
            key_text = str(child_key)
            if key_text == "__append":
                append_path = f"{path}/+" if path else "/+"
                if not self._edit_node(target, append_path, overlay[child_key], merge_tree=True):
                    return False
                continue
            if key_text == "__merge":
                if not self._merge_tree(target, path, overlay[child_key]):
                    return False
                continue
            child_path = key_text if not path else f"{path}/{key_text}"
            if not self._edit_node(target, child_path, overlay[child_key], merge_tree=True):
                return False
        return True

    def _edit_node(self, target: Any, key: str, value: Any, *, merge_tree: bool) -> bool:
        """Python 版 ConfigCompiler::EditNode()。"""
        key = str(key)
        indexed_append = self._parse_indexed_append(key)
        plain_add = key.endswith("/+") and indexed_append is None
        appending = (
            key == "__append"
            or key.endswith("/+")
            or indexed_append is not None
        )
        merging = (
            key == "__merge"
            or plain_add
            or (
                merge_tree
                and (value is None or isinstance(value, Mapping))
                and not key.endswith("/=")
            )
        )

        path = self._strip_patch_operator(
            key,
            appending=(appending or merging),
            indexed_append=indexed_append,
        )

        existing = self.get_path(target, path, _MISSING)

        if (appending or merging) and existing is not _MISSING and existing is not None:
            if value is None:
                return True
            if appending and self._append_value(target, path, value, indexed_append):
                return True
            if merging and self._merge_tree(target, path, value):
                return True
            return False

        # Rime 在目标不存在时直接以 value 覆盖/创建目标。
        if path:
            self.set_path(target, path, value)
            return True

        # path 为空时等价于给 ConfigItemRef 本身赋值。
        if isinstance(target, _RootNodeRef):
            self.set_path(target, "", value)
            return True

        # 兼容内部仍以普通容器作为 target 的旧调用。
        if isinstance(target, MutableMapping) and isinstance(value, Mapping):
            target.clear()
            target.update(copy.deepcopy(value))
            return True
        if isinstance(target, list) and isinstance(value, list):
            target[:] = copy.deepcopy(value)
            return True
        return False

    def apply_patch_entry(self, data: Any, path: str, value: Any) -> Any:
        """应用一条 Rime literal patch，并返回可能被替换后的根节点。

        对普通子路径通常仍是原对象；对根 __append/__merge 或根覆盖，
        返回值可能从空 map 变为 list，这与 ConfigItemRef 的可替换语义一致。
        """
        box = data if isinstance(data, _RootNodeRef) else _RootNodeRef(data)
        if not self._edit_node(box, str(path), value, merge_tree=False):
            raise TypeError(f"无法按 Rime 补丁语义应用路径：{path}")
        return box.value

    def apply_patch(self, schema: Any, patch: Any) -> Any:
        """按 librime ConfigCompiler 的 literal patch 语义生成最终配置。

        支持：
          - 普通路径覆盖
          - @0 / @last / @next / @before / @after
          - /+（字符串追加、列表追加、映射合并）
          - /=（强制覆盖）
          - /N+（在列表第 N 位插入一组元素）
          - __append / __merge
          - patch 为单个 mapping，或由多个 mapping 组成的 sequence

        本函数只负责 literal patch；__include / __patch 引用由 compile_file/load_pair
        的 ConfigCompiler 兼容层解析。
        """
        root = _RootNodeRef(copy.deepcopy(schema if schema is not None else {}))

        patch_groups: List[Mapping[str, Any]] = []
        if isinstance(patch, Mapping):
            patch_groups = [patch]
        elif isinstance(patch, Sequence) and not isinstance(patch, (str, bytes, bytearray)):
            for item in patch:
                if isinstance(item, Mapping):
                    patch_groups.append(item)

        # librime ConfigMap 使用 std::map；同一 literal patch 内按 key 排序遍历。
        # 多个 patch literal 之间则按 sequence 顺序执行。
        for group in patch_groups:
            for key in sorted(group.keys(), key=lambda item: str(item)):
                self.apply_patch_entry(root, str(key), group[key])

        return root.value

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

