"""Thin wrapper: one RimeDllWrapper instance, switch distro dirs between vendors."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .call_librime import RimeDllWrapper
from .config import VendorConfig, shared_data_dir


@dataclass
class DecodeResult:
    prediction: str
    ok: bool
    reason: str


class RimeDistroRunner:
    """
    ``shared_data_dir`` → ``vendor/data`` under repo root; ``user_data_dir`` → each
    vendor checkout (submodule) for per-schema deploy and user state.
    """
    def __init__(self, dll_path: Path) -> None:
        self._dll_path = Path(dll_path)
        self._rime: Optional[RimeDllWrapper] = None
        self._user_dir: Optional[Path] = None
        self._shared_dir: Optional[Path] = None
        self._schema_id: Optional[str] = None
        self._batch_session_id: Optional[int] = None

    @property
    def input_feed_mode(self) -> str:
        """``set_input`` (librime 1.9+ 导出 ``RimeSetInput``) 或 ``simulate_key_sequence``。"""
        if self._rime is None:
            return "uninitialized"
        return "set_input" if self._rime.uses_set_input() else "simulate_key_sequence"

    @property
    def pinyin_feed_mode(self) -> str:
        """Backward-compatible alias for :attr:`input_feed_mode`."""
        return self.input_feed_mode

    def close(self) -> None:
        if self._rime is not None:
            try:
                self.end_decode_batch()
                self._rime.finalize()
            finally:
                self._rime = None
                self._user_dir = None
                self._shared_dir = None
                self._schema_id = None
                self._batch_session_id = None

    def switch_distro(self, vendor: VendorConfig, root: Optional[Path] = None) -> None:
        user_dir = vendor.data_dir(root)
        shared = shared_data_dir(root)
        if not user_dir.is_dir():
            raise FileNotFoundError(f"Vendor data directory missing: {user_dir}")
        shared.mkdir(parents=True, exist_ok=True)
        if (
            self._rime is not None
            and self._user_dir == user_dir
            and self._shared_dir == shared
            and self._schema_id == vendor.schema_id
        ):
            return
        self.close()
        rime = RimeDllWrapper(dll_path=str(self._dll_path))
        rime.initialize(
            app_name="rime.schema.compare",
            shared_data_dir=str(shared),
            user_data_dir=str(user_dir),
        )
        self._rime = rime
        self._user_dir = user_dir
        self._shared_dir = shared
        self._schema_id = vendor.schema_id

    def begin_decode_batch(self, schema_id: Optional[str] = None) -> bool:
        """
        Create one session and select schema; reuse for many :meth:`decode_pinyin_in_batch` calls.
        Call :meth:`end_decode_batch` when done (or rely on :meth:`close` / :meth:`switch_distro`).
        """
        self.end_decode_batch()
        if self._rime is None:
            return False
        sid = schema_id or self._schema_id or ""
        session_id = self._rime.create_session()
        if not session_id:
            return False
        if not self._rime.select_schema(session_id, sid):
            self._rime.destroy_session(session_id)
            return False
        self._batch_session_id = session_id
        return True

    def end_decode_batch(self) -> None:
        if self._rime is not None and self._batch_session_id:
            try:
                self._rime.destroy_session(self._batch_session_id)
            finally:
                self._batch_session_id = None

    def _decode_from_input(self, session_id: int, raw_input: str) -> DecodeResult:
        assert self._rime is not None
        if not self._rime.feed_input(session_id, raw_input):
            return DecodeResult("", False, "feed_input_failed")
        ctx = self._rime.get_context(session_id)
        if not ctx:
            return DecodeResult("", False, "no_context")
        cands: List[dict] = ctx.get("candidates") or []
        top = (cands[0].get("text") or "").strip() if cands else ""
        if not top:
            return DecodeResult("", False, "empty_top_candidate")
        return DecodeResult(top, True, "ok")

    def decode_input_in_batch(self, raw_input: str) -> DecodeResult:
        """Decode one sentence using the session from :meth:`begin_decode_batch`."""
        if self._rime is None or self._batch_session_id is None:
            return DecodeResult("", False, "batch_session_not_open")
        return self._decode_from_input(self._batch_session_id, raw_input)

    def decode_pinyin_in_batch(self, pinyin: str) -> DecodeResult:
        """Backward-compatible alias for :meth:`decode_input_in_batch`."""
        return self.decode_input_in_batch(pinyin)

    def decode_input(self, raw_input: str, schema_id: Optional[str] = None) -> DecodeResult:
        """One-shot: new session per call (e.g. smoke tests)."""
        if self._rime is None or self._user_dir is None:
            return DecodeResult("", False, "rime_not_initialized")
        sid = schema_id or self._schema_id or ""
        session_id = self._rime.create_session()
        if not session_id:
            return DecodeResult("", False, "create_session_failed")
        try:
            if not self._rime.select_schema(session_id, sid):
                return DecodeResult("", False, "select_schema_failed")
            return self._decode_from_input(session_id, raw_input)
        finally:
            self._rime.destroy_session(session_id)

    def decode_pinyin(self, pinyin: str, schema_id: Optional[str] = None) -> DecodeResult:
        """Backward-compatible alias for :meth:`decode_input`."""
        return self.decode_input(pinyin, schema_id=schema_id)
