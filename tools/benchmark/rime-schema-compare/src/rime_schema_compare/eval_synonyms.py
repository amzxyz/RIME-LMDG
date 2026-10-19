"""Optional text normalization before sentence/CER metrics (equivalent wording)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

# Built-in defaults when no JSON file is present
DEFAULT_PHRASES: List[Tuple[str, str]] = [
    ("其它", "其他"),
]
DEFAULT_CHAR_GROUPS: List[List[str]] = [
    ["他", "她", "它"],
    ["的", "地", "得"],
]


def _build_translate_table(char_groups: Sequence[Sequence[str]]) -> Dict[int, int]:
    m: Dict[int, int] = {}
    for group in char_groups:
        if not group:
            continue
        canon = group[0]
        if len(canon) != 1:
            raise ValueError(f"eval_synonyms: canonical must be one char, got {canon!r}")
        d0 = ord(canon)
        for c in group:
            if len(c) != 1:
                raise ValueError(f"eval_synonyms: group member must be one char, got {c!r}")
            m[ord(c)] = d0
    return m


@dataclass
class EvalSynonymConfig:
    """
    Normalize gold/prediction before exact match and Levenshtein/CER.

    - phrases: (variant, canonical) — replace all occurrences of variant with canonical
      (longer variants first).
    - char_groups: each list maps every character to the first character of that list.
    """

    phrases: List[Tuple[str, str]] = field(default_factory=lambda: list(DEFAULT_PHRASES))
    char_groups: List[List[str]] = field(default_factory=lambda: [list(g) for g in DEFAULT_CHAR_GROUPS])
    _trans: Dict[int, int] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._trans = _build_translate_table(self.char_groups)

    def normalize(self, s: str) -> str:
        t = s.strip()
        for a, b in sorted(self.phrases, key=lambda ab: -len(ab[0])):
            if a:
                t = t.replace(a, b)
        if self._trans:
            t = t.translate(self._trans)
        return t

    def summary_line(self) -> str:
        parts = [f"{a}→{b}" for a, b in self.phrases]
        for g in self.char_groups:
            if g:
                parts.append("/".join(g) + f"→{g[0]}")
        return "；".join(parts) if parts else "（无）"


def _parse_json_payload(data: Any) -> EvalSynonymConfig:
    if not isinstance(data, dict):
        raise ValueError("eval_synonyms.json root must be an object")
    phrases: List[Tuple[str, str]] = []
    raw_p = data.get("phrases")
    if raw_p is not None:
        if not isinstance(raw_p, list):
            raise ValueError("phrases must be a list")
        for item in raw_p:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                a, b = str(item[0]), str(item[1])
                phrases.append((a, b))
            elif isinstance(item, dict) and "from" in item and "to" in item:
                phrases.append((str(item["from"]), str(item["to"])))
            else:
                raise ValueError(f"invalid phrase entry: {item!r}")
    groups: List[List[str]] = []
    raw_g = data.get("character_groups")
    if raw_g is not None:
        if not isinstance(raw_g, list):
            raise ValueError("character_groups must be a list")
        for g in raw_g:
            if not isinstance(g, list) or not g:
                raise ValueError(f"invalid character_groups entry: {g!r}")
            groups.append([str(c) for c in g])
    return EvalSynonymConfig(
        phrases=phrases or list(DEFAULT_PHRASES),
        char_groups=groups or [list(g) for g in DEFAULT_CHAR_GROUPS],
    )


def load_eval_synonyms_config(path: Path) -> EvalSynonymConfig:
    """
    Load from JSON. If file is missing or empty, return built-in defaults.
    """
    if not path.is_file():
        return EvalSynonymConfig()
    try:
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return EvalSynonymConfig()
        data = json.loads(raw)
        return _parse_json_payload(data)
    except (json.JSONDecodeError, ValueError) as e:
        raise ValueError(f"Invalid eval synonyms file {path}: {e}") from e
