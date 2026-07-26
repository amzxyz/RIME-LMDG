from __future__ import annotations

import os
import shutil
import subprocess
import time
from typing import Callable, Optional, Tuple

LogCallback = Optional[Callable[[str], None]]


def _emit(log: LogCallback, message: str) -> None:
    if log is None:
        return
    try:
        log(message)
    except Exception:
        pass


def detect_linux_im_system() -> str:
    """沿用原程序逻辑：根据正在运行的进程识别 Fcitx5 或 IBus。"""
    pgrep = shutil.which("pgrep")
    if not pgrep:
        return "unknown"

    try:
        if subprocess.run(
            [pgrep, "fcitx5"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode == 0:
            return "fcitx5"

        if subprocess.run(
            [pgrep, "ibus-daemon"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode == 0:
            return "ibus"
    except Exception:
        return "unknown"

    return "unknown"


def _deploy_linux_fcitx5(log: LogCallback = None) -> Tuple[bool, str]:
    """沿用原程序的 Fcitx5 D-Bus 部署方式，不改成 fcitx5-remote。"""
    dbus_tool = shutil.which("dbus-send")
    if not dbus_tool:
        return False, "未找到 dbus-send，无法向 Fcitx5 Rime 发送部署指令。"

    command = [
        dbus_tool,
        "--session",
        "--dest=org.fcitx.Fcitx5",
        "--type=method_call",
        "/controller",
        "org.fcitx.Fcitx.Controller1.SetConfig",
        "string:fcitx://config/addon/rime/deploy",
        "variant:string:",
    ]

    clean_env = os.environ.copy()
    if "LD_LIBRARY_PATH" in clean_env:
        clean_env["LD_LIBRARY_PATH"] = clean_env.get("LD_LIBRARY_PATH_ORIG", "")

    _emit(log, "📡 [Fcitx5] 正在通过 D-Bus 触发 Rime 部署……")
    try:
        subprocess.run(
            command,
            env=clean_env,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return True, "Fcitx5 Rime 部署指令已发送。"
    except subprocess.CalledProcessError as error:
        details = (
            error.stderr.decode("utf-8", errors="ignore").strip()
            if error.stderr else "无详细错误信息"
        )
        return False, f"Fcitx5 部署失败（返回码 {error.returncode}）：{details}"
    except Exception as error:
        return False, f"Fcitx5 部署调用异常：{error}"


def _deploy_linux_ibus(log: LogCallback = None) -> Tuple[bool, str]:
    """沿用原程序的 IBus 重启方式。"""
    ibus = shutil.which("ibus")
    if not ibus:
        return False, "未找到 ibus 命令，无法触发 IBus 重载。"

    _emit(log, "📡 [IBus] 正在重启 IBus 以触发 Rime 重载……")
    try:
        subprocess.run([ibus, "restart"], check=True)
        return True, "IBus 已重新启动，Rime 配置将重新加载。"
    except Exception as error:
        return False, f"IBus 重启失败：{error}"


def deploy_rime_platform(
    system_type: str,
    *,
    log: LogCallback = None,
    server_path: str = "",
    deployer_path: str = "",
) -> Tuple[bool, str]:
    """统一平台部署入口。

    行为与原程序保持一致：
    - Windows：启动 WeaselServer 后调用 WeaselDeployer /deploy；
    - macOS：通知 Squirrel reload configuration；
    - Linux：识别 Fcitx5/IBus，再调用原有对应部署方式。
    """
    if system_type == "windows":
        try:
            if server_path and os.path.isfile(server_path):
                subprocess.Popen([server_path], creationflags=0x08000000)
                time.sleep(3)

            if not deployer_path:
                return False, "未检测到 WeaselDeployer.exe。"
            if not os.path.isfile(deployer_path):
                return False, f"部署器路径无效：{deployer_path}"

            subprocess.Popen(
                [deployer_path, "/deploy"],
                creationflags=0x08000000,
            )
            return True, "Windows 小狼毫部署指令已发送。"
        except Exception as error:
            return False, f"Windows 部署调用失败：{error}"

    if system_type == "macos":
        try:
            subprocess.run(
                [
                    "osascript",
                    "-e",
                    'tell application "Squirrel" to reload configuration',
                ],
                check=True,
            )
            return True, "macOS 鼠须管部署通知已发送。"
        except Exception as error:
            return False, f"macOS 部署调用失败：{error}"

    if system_type == "android/linux":
        im_system = detect_linux_im_system()
        _emit(log, f"🔎 Linux 输入法框架检测结果：{im_system}")

        if im_system == "fcitx5":
            return _deploy_linux_fcitx5(log)
        if im_system == "ibus":
            return _deploy_linux_ibus(log)

        return False, "未检测到正在运行的 Fcitx5 或 IBus，未执行部署。"

    return False, f"当前系统类型不支持自动部署：{system_type}"
