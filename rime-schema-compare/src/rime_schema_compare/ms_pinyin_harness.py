"""Black-box Windows Pinyin IME automation via Windows APIs."""

from __future__ import annotations

import ctypes
import json
import re
import subprocess
import time
from dataclasses import dataclass
import winreg
from typing import Any, Dict, List, Optional, Set


if ctypes.sizeof(ctypes.c_void_p) == 8:
    ULONG_PTR = ctypes.c_ulonglong
else:
    ULONG_PTR = ctypes.c_ulong

user32 = ctypes.WinDLL("user32", use_last_error=True)
imm32 = ctypes.WinDLL("imm32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

SW_RESTORE = 9
WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E
WM_SETTEXT = 0x000C
WM_CLOSE = 0x0010
WM_INPUTLANGCHANGEREQUEST = 0x0050
WM_CHAR = 0x0102
KEYEVENTF_KEYUP = 0x0002
KLF_ACTIVATE = 0x00000001
VK_LWIN = 0x5B
VK_SPACE = 0x20
VK_ESCAPE = 0x1B

PREFERRED_EDIT_CLASSES = {
    "Edit",
    "RichEdit20W",
    "RichEdit50W",
    "RichEditD2DPT",
    "TextInputHostWindow",
}


LPARAM = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long


@dataclass
class BlackboxDecodeResult:
    prediction: str
    ok: bool
    reason: str


@dataclass(frozen=True)
class InstalledImeProfile:
    ime_key: str
    display_name: str
    input_tip: str
    tip_guid: str
    profile_guid: str
    description: str

    @property
    def list_item_text(self) -> str:
        return self.description or self.display_name


def _normalize_guid(value: str) -> str:
    return str(value or "").strip().strip("{}").upper()


_TSF_HELPER_CSHARP = r"""
using System;
using System.Runtime.InteropServices;

namespace CursorTsfInterop {
    [StructLayout(LayoutKind.Sequential)]
    public struct TF_INPUTPROCESSORPROFILE {
        public uint dwProfileType;
        public ushort langid;
        public Guid clsid;
        public Guid guidProfile;
        public Guid catid;
        public IntPtr hklSubstitute;
        public uint dwCaps;
        public IntPtr hkl;
        public uint dwFlags;
    }

    [ComImport, Guid("71C6E74C-0F28-11D8-A82A-00065B84435C"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface ITfInputProcessorProfileMgr {
        [PreserveSig]
        int ActivateProfile(uint dwProfileType, ushort langid, ref Guid clsid, ref Guid guidProfile, IntPtr hkl, uint dwFlags);

        [PreserveSig]
        int DeactivateProfile(uint dwProfileType, ushort langid, ref Guid clsid, ref Guid guidProfile, IntPtr hkl, uint dwFlags);

        [PreserveSig]
        int GetProfile(uint dwProfileType, ushort langid, ref Guid clsid, ref Guid guidProfile, IntPtr hkl, out TF_INPUTPROCESSORPROFILE profile);

        [PreserveSig]
        int EnumProfiles(ushort langid, out IntPtr enumProfile);

        [PreserveSig]
        int ReleaseInputProcessor(ref Guid clsid, ushort langid, ref Guid guidProfile);

        [PreserveSig]
        int RegisterProfile(ref Guid clsid, ushort langid, ref Guid guidProfile, string description, uint descriptionLength, string iconFile, uint iconFileLength, uint iconIndex);

        [PreserveSig]
        int UnregisterProfile(ref Guid clsid, ushort langid, ref Guid guidProfile, uint flags);

        [PreserveSig]
        int GetActiveProfile(ref Guid catid, out TF_INPUTPROCESSORPROFILE profile);
    }

    [ComImport, Guid("33C53A50-F456-4884-B049-85FD643ECFED")]
    public class TF_InputProcessorProfiles {
    }

    public static class TsfInterop {
        private static readonly Guid GuidTfcatTipKeyboard = new Guid("34745C63-B2F0-4784-8B67-5E12C8701A31");
        private const uint TF_PROFILETYPE_INPUTPROCESSOR = 1;
        private const uint TF_IPPMF_FORSESSION = 0x20000000;
        private const uint TF_IPPMF_DONTCARECURRENTINPUTLANGUAGE = 0x00000004;

        public static string GetActiveProfileJson() {
            var mgr = (ITfInputProcessorProfileMgr)new TF_InputProcessorProfiles();
            var catid = GuidTfcatTipKeyboard;
            TF_INPUTPROCESSORPROFILE profile;
            int hr = mgr.GetActiveProfile(ref catid, out profile);
            if (hr != 0) {
                Marshal.ThrowExceptionForHR(hr);
            }
            return string.Format(
                "{{\"dwProfileType\":{0},\"langid\":{1},\"clsid\":\"{2}\",\"guidProfile\":\"{3}\",\"catid\":\"{4}\",\"hkl\":\"0x{5:X}\",\"dwFlags\":{6}}}",
                profile.dwProfileType,
                profile.langid,
                profile.clsid.ToString("D").ToUpperInvariant(),
                profile.guidProfile.ToString("D").ToUpperInvariant(),
                profile.catid.ToString("D").ToUpperInvariant(),
                profile.hkl.ToInt64(),
                profile.dwFlags
            );
        }

        public static void ActivateTipProfile(string tipGuid, string profileGuid, ushort langid) {
            var mgr = (ITfInputProcessorProfileMgr)new TF_InputProcessorProfiles();
            var clsid = new Guid(tipGuid);
            var guidProfile = new Guid(profileGuid);
            int hr = mgr.ActivateProfile(
                TF_PROFILETYPE_INPUTPROCESSOR,
                langid,
                ref clsid,
                ref guidProfile,
                IntPtr.Zero,
                TF_IPPMF_FORSESSION | TF_IPPMF_DONTCARECURRENTINPUTLANGUAGE
            );
            if (hr != 0) {
                Marshal.ThrowExceptionForHR(hr);
            }
        }
    }
}
"""


def _tsf_powershell(command: str) -> str:
    return (
        'Add-Type -Language CSharp -TypeDefinition @"\n'
        + _TSF_HELPER_CSHARP
        + '\n"@;\n'
        + command
    )


def _wait_until(predicate, timeout_s: float, poll_s: float = 0.05) -> bool:
    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        if predicate():
            return True
        time.sleep(poll_s)
    return False


def _run_powershell(command: str) -> str:
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "").strip() or "powershell_command_failed")
    return (proc.stdout or "").strip()


def _run_powershell_json(command: str):
    raw = _run_powershell(command)
    if not raw:
        return None
    return json.loads(raw)


class WindowsImeSwitcher:
    _TIP_RE = re.compile(
        r"^(?P<lang>[0-9A-Fa-f]+):\{(?P<tip>[^}]+)\}\{(?P<profile>[^}]+)\}$"
    )
    _IME_PATTERNS = {
        "microsoft_pinyin": ("microsoft pinyin", "微软拼音"),
        "sogou_pinyin": ("搜狗拼音", "sogou"),
    }
    _IME_DISPLAY = {
        "microsoft_pinyin": "微软拼音",
        "sogou_pinyin": "搜狗拼音",
    }

    def __init__(self) -> None:
        self._language_payload = self._load_language_payload()
        self._profiles = self._build_profiles(self._language_payload)
        self._active_input_tip = self.get_default_input_tip()

    def list_installed_profiles(self, language_tag: str = "zh-Hans-CN") -> List[InstalledImeProfile]:
        return [p for p in self._profiles if p.input_tip.startswith("0804:")]

    def list_input_method_texts(self, language_tag: str = "zh-Hans-CN") -> List[str]:
        return [p.list_item_text for p in self.list_installed_profiles(language_tag)]

    def resolve_profile(self, ime_key: str) -> InstalledImeProfile:
        for profile in self._profiles:
            if profile.ime_key == ime_key:
                return profile
        raise RuntimeError(f"ime_profile_not_found:{ime_key}")

    def get_default_input_tip(self) -> str:
        payload = _run_powershell_json("Get-WinDefaultInputMethodOverride | ConvertTo-Json -Depth 3")
        if isinstance(payload, dict):
            return str(payload.get("InputMethodTip") or payload.get("InputTip") or "").strip()
        if isinstance(payload, str):
            return payload.strip()
        return ""

    def get_active_profile(self) -> Optional[InstalledImeProfile]:
        payload = self.get_active_profile_payload()
        active_tip = _normalize_guid(payload.get("tip_guid"))
        active_profile = _normalize_guid(payload.get("profile_guid"))
        for profile in self._profiles:
            if profile.tip_guid == active_tip and profile.profile_guid == active_profile:
                return profile
        return None

    def get_active_profile_payload(self) -> Dict[str, Any]:
        payload = _run_powershell_json(
            _tsf_powershell('[CursorTsfInterop.TsfInterop]::GetActiveProfileJson()')
        )
        if not isinstance(payload, dict):
            raise RuntimeError("active_ime_profile_unavailable")
        return {
            "dw_profile_type": int(payload.get("dwProfileType") or 0),
            "langid": int(payload.get("langid") or 0),
            "tip_guid": _normalize_guid(payload.get("clsid") or ""),
            "profile_guid": _normalize_guid(payload.get("guidProfile") or ""),
            "catid": _normalize_guid(payload.get("catid") or ""),
            "hkl": str(payload.get("hkl") or ""),
            "dw_flags": int(payload.get("dwFlags") or 0),
        }

    def open_input_method_list(self) -> None:
        self._send_win_space()
        time.sleep(0.2)

    def close_input_method_list(self) -> None:
        self._send_vk(VK_ESCAPE)
        time.sleep(0.05)

    def activate_profile(self, ime_key: str, focus_callback=None) -> InstalledImeProfile:
        profile = self.resolve_profile(ime_key)
        current = self.get_active_profile()
        if current is not None and (
            current.ime_key == profile.ime_key
            and current.tip_guid == profile.tip_guid
            and current.profile_guid == profile.profile_guid
        ):
            self._active_input_tip = current.input_tip
            return current
        if focus_callback is not None:
            focus_callback()
        available_items = self.list_input_method_texts()
        if profile.list_item_text not in available_items:
            raise RuntimeError(f"ime_list_item_not_found:{ime_key}")
        langid = int(profile.input_tip.split(":", 1)[0], 16)
        for _ in range(3):
            _run_powershell(
                _tsf_powershell(
                    f"[CursorTsfInterop.TsfInterop]::ActivateTipProfile('{profile.tip_guid}', '{profile.profile_guid}', {langid})"
                )
            )
            if focus_callback is not None:
                focus_callback()
            confirmed = self._wait_for_active_profile(profile, timeout_s=1.5)
            if confirmed is not None:
                self._active_input_tip = confirmed.input_tip
                return confirmed
            time.sleep(0.1)
        raise RuntimeError(f"ime_switch_not_confirmed:{ime_key}")

    def _wait_for_active_profile(
        self, expected: InstalledImeProfile, timeout_s: float = 3.0
    ) -> Optional[InstalledImeProfile]:
        matched: Optional[InstalledImeProfile] = None

        def probe() -> bool:
            nonlocal matched
            current = self.get_active_profile()
            if current is None:
                return False
            if (
                current.ime_key == expected.ime_key
                and current.tip_guid == expected.tip_guid
                and current.profile_guid == expected.profile_guid
            ):
                matched = current
                return True
            return False

        if _wait_until(probe, timeout_s=timeout_s, poll_s=0.1):
            return matched
        return None

    def _ime_key_for_description(self, description: str) -> Optional[str]:
        desc = (description or "").lower()
        for ime_key, patterns in self._IME_PATTERNS.items():
            if any(p.lower() in desc for p in patterns):
                return ime_key
        return None

    def _lookup_profile_description(self, tip_guid: str, profile_guid: str) -> str:
        key_paths = [
            rf"SOFTWARE\Microsoft\CTF\TIP\{{{tip_guid}}}\LanguageProfile\0x00000804\{{{profile_guid}}}",
            rf"SOFTWARE\WOW6432Node\Microsoft\CTF\TIP\{{{tip_guid}}}\LanguageProfile\0x00000804\{{{profile_guid}}}",
        ]
        hives = (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE)
        for hive in hives:
            for subkey in key_paths:
                try:
                    with winreg.OpenKey(hive, subkey) as k:
                        for value_name in ("Description", "Display Description", "DisplayDescription"):
                            try:
                                value, _ = winreg.QueryValueEx(k, value_name)
                            except FileNotFoundError:
                                continue
                            if value:
                                return str(value)
                except FileNotFoundError:
                    continue
        return ""

    def _load_language_payload(self):
        payload = _run_powershell_json("Get-WinUserLanguageList | ConvertTo-Json -Depth 5")
        if payload is None:
            return []
        return payload if isinstance(payload, list) else [payload]

    def _build_profiles(self, rows) -> List[InstalledImeProfile]:
        out: List[InstalledImeProfile] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            raw_tips = row.get("InputMethodTips") or []
            if not isinstance(raw_tips, list):
                continue
            for tip in raw_tips:
                m = self._TIP_RE.match(str(tip))
                if not m:
                    continue
                tip_guid = m.group("tip").upper()
                profile_guid = m.group("profile").upper()
                desc = self._lookup_profile_description(tip_guid, profile_guid)
                ime_key = self._ime_key_for_description(desc)
                if not ime_key:
                    continue
                out.append(
                    InstalledImeProfile(
                        ime_key=ime_key,
                        display_name=self._IME_DISPLAY[ime_key],
                        input_tip=str(tip),
                        tip_guid=tip_guid,
                        profile_guid=profile_guid,
                        description=desc,
                    )
                )
        return out

    def _send_win_space(self) -> None:
        user32.keybd_event(VK_LWIN, 0, 0, 0)
        time.sleep(0.01)
        user32.keybd_event(VK_SPACE, 0, 0, 0)
        time.sleep(0.01)
        user32.keybd_event(VK_SPACE, 0, KEYEVENTF_KEYUP, 0)
        time.sleep(0.01)
        user32.keybd_event(VK_LWIN, 0, KEYEVENTF_KEYUP, 0)

    def _send_vk(self, vk: int) -> None:
        user32.keybd_event(vk, 0, 0, 0)
        time.sleep(0.005)
        user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


class WindowsPinyinImeHarness:
    """Drive a foreground Windows Pinyin IME in a Notepad window."""

    def __init__(
        self,
        *,
        host_command: Optional[List[str]] = None,
        launch_timeout_s: float = 10.0,
        settle_timeout_s: float = 3.0,
        inter_key_delay_s: float = 0.012,
        commit_delay_s: float = 0.12,
        probe_input: str = "a",
        max_prepare_attempts: int = 2,
    ) -> None:
        self.host_command = host_command or ["notepad.exe"]
        self.launch_timeout_s = launch_timeout_s
        self.settle_timeout_s = settle_timeout_s
        self.inter_key_delay_s = inter_key_delay_s
        self.commit_delay_s = commit_delay_s
        self.probe_input = probe_input
        self.max_prepare_attempts = max(1, max_prepare_attempts)
        self._proc: Optional[subprocess.Popen[str]] = None
        self._window_hwnd: Optional[int] = None
        self._edit_hwnd: Optional[int] = None
        self._window_pid: Optional[int] = None
        self._layout_hkl: Optional[int] = None

    @property
    def process_pid(self) -> Optional[int]:
        return self._proc.pid if self._proc is not None else None

    def start(self) -> None:
        if self._proc is not None and self._window_hwnd and self._edit_hwnd:
            return
        baseline = set(self._candidate_top_windows())
        self._proc = subprocess.Popen(self.host_command)
        ok = _wait_until(lambda: self._refresh_window_handles(baseline), timeout_s=self.launch_timeout_s)
        if not ok:
            raise RuntimeError("notepad_window_not_found")
        self.reset_host()

    def close(self) -> None:
        if self._edit_hwnd:
            try:
                user32.SendMessageW(self._edit_hwnd, WM_SETTEXT, 0, "")
            except Exception:
                pass
        if self._window_hwnd:
            try:
                user32.PostMessageW(self._window_hwnd, WM_CLOSE, 0, 0)
            except Exception:
                pass
        if self._proc is not None:
            try:
                self._proc.wait(timeout=0.5)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
        self._proc = None
        self._window_hwnd = None
        self._edit_hwnd = None
        self._window_pid = None

    def reset_host(self) -> None:
        if not self._refresh_window_handles():
            raise RuntimeError("host_window_unavailable")
        self._focus_host()
        self._press_escape()
        user32.SendMessageW(self._edit_hwnd, WM_SETTEXT, 0, "")
        time.sleep(0.05)

    def focus_host(self) -> None:
        if not self._refresh_window_handles():
            raise RuntimeError("host_window_unavailable")
        self._focus_host()

    def self_check(self) -> None:
        if not self._refresh_window_handles():
            raise RuntimeError("host_window_unavailable")
        self.reset_host()
        if not self._ensure_chinese_mode():
            raise RuntimeError("ime_not_ready")
        user32.SendMessageW(self._edit_hwnd, WM_SETTEXT, 0, "abc")
        time.sleep(0.05)
        committed = self._read_host_text().strip()
        if committed != "abc":
            raise RuntimeError(f"host_ascii_probe_failed:{committed!r}")
        self.reset_host()

    def decode(self, raw_input: str) -> BlackboxDecodeResult:
        if not raw_input:
            return BlackboxDecodeResult("", False, "empty_input")
        try:
            self.reset_host()
        except Exception as exc:
            return BlackboxDecodeResult("", False, f"reset_failed:{exc}")
        if not self._ensure_chinese_mode():
            return BlackboxDecodeResult("", False, "ime_not_ready")
        self.reset_host()
        self._focus_host()
        try:
            self._send_ascii_keys(raw_input)
            time.sleep(self.commit_delay_s)
            self._press_space()
            committed = self._wait_for_committed_text().strip()
        except Exception as exc:
            return BlackboxDecodeResult("", False, f"send_keys_failed:{exc}")
        if not committed:
            return BlackboxDecodeResult("", False, "empty_committed_text")
        lowered = committed.lower().strip()
        if lowered == raw_input.lower() or lowered == (raw_input.lower() + " "):
            return BlackboxDecodeResult(committed, False, "ime_not_in_chinese_mode")
        return BlackboxDecodeResult(committed, True, "ok")

    def _refresh_window_handles(self, baseline_hwnds: Optional[Set[int]] = None) -> bool:
        if self._window_hwnd and user32.IsWindow(self._window_hwnd):
            hwnd = self._window_hwnd
        else:
            hwnd = None
        if not hwnd and self._proc is not None and self._proc.poll() is None:
            hwnd = self._find_main_window_for_pid(self._proc.pid)
        if not hwnd:
            hwnd = self._find_new_top_window(baseline_hwnds or set())
        if not hwnd:
            return False
        edit_hwnd = self._find_text_control(hwnd)
        if not edit_hwnd:
            return False
        proc_id = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(proc_id))
        self._window_hwnd = hwnd
        self._edit_hwnd = edit_hwnd
        self._window_pid = int(proc_id.value) if proc_id.value else None
        return True

    def _find_main_window_for_pid(self, pid: int) -> Optional[int]:
        found: List[int] = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, LPARAM)
        def enum_proc(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            proc_id = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(proc_id))
            if proc_id.value != pid:
                return True
            if user32.GetWindow(hwnd, 4):  # GW_OWNER
                return True
            found.append(int(hwnd))
            return False

        user32.EnumWindows(enum_proc, 0)
        return found[0] if found else None

    def _candidate_top_windows(self) -> List[int]:
        found: List[int] = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, LPARAM)
        def enum_proc(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            class_name = self._class_name(int(hwnd))
            if class_name != "Notepad":
                return True
            found.append(int(hwnd))
            return True

        user32.EnumWindows(enum_proc, 0)
        return found

    def _find_new_top_window(self, baseline_hwnds: Set[int]) -> Optional[int]:
        current = self._candidate_top_windows()
        for hwnd in current:
            if hwnd not in baseline_hwnds:
                return hwnd
        fg = int(user32.GetForegroundWindow() or 0)
        if fg and self._class_name(fg) == "Notepad":
            return fg
        return current[0] if current else None

    def _find_text_control(self, parent_hwnd: int) -> Optional[int]:
        matches: List[int] = []

        def scan(hwnd: int) -> None:
            children: List[int] = []

            @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, LPARAM)
            def enum_proc(child_hwnd, _lparam):
                children.append(int(child_hwnd))
                return True

            user32.EnumChildWindows(hwnd, enum_proc, 0)
            for child in children:
                class_name = self._class_name(child)
                if class_name in PREFERRED_EDIT_CLASSES:
                    matches.append(child)
                scan(child)

        scan(parent_hwnd)
        if matches:
            return matches[0]
        return None

    def _class_name(self, hwnd: int) -> str:
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, len(buf))
        return buf.value

    def _focus_host(self) -> None:
        if not self._window_hwnd or not self._edit_hwnd:
            raise RuntimeError("host_window_unavailable")
        user32.ShowWindow(self._window_hwnd, SW_RESTORE)
        user32.SetForegroundWindow(self._window_hwnd)
        time.sleep(0.05)
        user32.SetForegroundWindow(self._edit_hwnd)
        time.sleep(0.05)

    def _ensure_chinese_mode(self) -> bool:
        for _ in range(self.max_prepare_attempts):
            try:
                self._focus_host()
                self._open_ime()
                time.sleep(0.08)
                if self._probe_hanzi_commit():
                    return True
            finally:
                try:
                    self.reset_host()
                except Exception:
                    pass
        return False

    def _activate_chinese_layout(self) -> None:
        if not self._window_hwnd:
            raise RuntimeError("host_window_unavailable")
        hkl = user32.LoadKeyboardLayoutW("00000804", KLF_ACTIVATE)
        if not hkl:
            raise RuntimeError("load_zh_cn_layout_failed")
        self._layout_hkl = int(hkl)
        user32.PostMessageW(self._window_hwnd, WM_INPUTLANGCHANGEREQUEST, 0, self._layout_hkl)
        if self._edit_hwnd:
            user32.PostMessageW(self._edit_hwnd, WM_INPUTLANGCHANGEREQUEST, 0, self._layout_hkl)

    def _open_ime(self) -> None:
        if not self._edit_hwnd:
            return
        himc = imm32.ImmGetContext(self._edit_hwnd)
        if not himc:
            return
        try:
            imm32.ImmSetOpenStatus(himc, True)
        finally:
            imm32.ImmReleaseContext(self._edit_hwnd, himc)

    def _probe_hanzi_commit(self) -> bool:
        self.reset_host()
        self._focus_host()
        self._send_ascii_keys(self.probe_input)
        time.sleep(self.commit_delay_s)
        self._press_space()
        committed = self._wait_for_committed_text().strip()
        if not committed:
            return False
        if committed.lower() == self.probe_input.lower():
            return False
        return any("\u4e00" <= ch <= "\u9fff" for ch in committed)

    def _send_ascii_keys(self, text: str) -> None:
        for ch in text:
            if not ch.isascii() or not ch.isprintable():
                raise ValueError(f"unsupported_key:{ch!r}")
            vk = ord(ch.upper())
            self._send_vk(vk)
            time.sleep(self.inter_key_delay_s)

    def _press_space(self) -> None:
        self._send_vk(VK_SPACE)

    def _press_escape(self) -> None:
        self._send_vk(VK_ESCAPE)

    def _send_vk(self, vk: int) -> None:
        user32.keybd_event(vk, 0, 0, 0)
        time.sleep(0.005)
        user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)

    def _wait_for_committed_text(self) -> str:
        stable = ""
        stable_count = 0
        deadline = time.perf_counter() + self.settle_timeout_s
        while time.perf_counter() < deadline:
            current = self._read_host_text().strip()
            if current and current == stable:
                stable_count += 1
                if stable_count >= 2:
                    return current
            else:
                stable = current
                stable_count = 0
            time.sleep(0.05)
        return self._read_host_text()

    def _read_host_text(self) -> str:
        if not self._edit_hwnd:
            raise RuntimeError("host_window_unavailable")
        length = int(user32.SendMessageW(self._edit_hwnd, WM_GETTEXTLENGTH, 0, 0))
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.SendMessageW(self._edit_hwnd, WM_GETTEXT, length + 1, buf)
        return buf.value


# Backward-compatible alias for older imports.
MicrosoftPinyinHarness = WindowsPinyinImeHarness
