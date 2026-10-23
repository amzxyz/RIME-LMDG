"""Small dependency-light wrapper for surfacing full Python import/runtime errors to Android."""
from __future__ import annotations
import importlib
import json
import sys
import traceback
from typing import Any


def invoke_json(method_name: str, args_json: str) -> str:
    """Call advanced_settings_mobile lazily and return either result or full traceback.

    This module deliberately imports no YAML/metadata dependencies at module import
    time, so it remains available to report failures while importing the main bridge.
    """
    try:
        args = json.loads(args_json or "[]")
        if not isinstance(args, list):
            raise TypeError("调用参数必须是 JSON 数组")
        module = importlib.import_module("advanced_settings_mobile")
        function = getattr(module, str(method_name))
        result = function(*args)
        return json.dumps({"ok": True, "result": result}, ensure_ascii=False)
    except BaseException as exc:  # report Python import errors too, not just normal exceptions
        module = sys.modules.get("advanced_settings_mobile")
        return json.dumps({
            "ok": False,
            "errorType": type(exc).__name__,
            "error": str(exc) or repr(exc),
            "traceback": traceback.format_exc(),
            "method": str(method_name),
            "pythonVersion": sys.version,
            "moduleFile": getattr(module, "__file__", None),
        }, ensure_ascii=False)
