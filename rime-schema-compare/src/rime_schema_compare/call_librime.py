"""
Vendored from librime-bert-gram (or upstream equivalent). See NOTICE in repo root.

调用 librime 的 Python 接口
支持两种方式：
1. 通过 subprocess 调用 rime_api_console.exe（简单方式）
2. 通过 ctypes 直接调用 rime.dll（高级方式，需要完整实现）

使用方法：

1. 交互式模式（推荐）：
   python call_librime.py --mode interactive
   或
   python call_librime.py

2. 使用控制台包装器：
   from call_librime import RimeConsoleWrapper
   
   wrapper = RimeConsoleWrapper()
   wrapper.start()
   result = wrapper.simulate_key_sequence("congmingdeRime shurufa")
   print(result)
   wrapper.stop()

3. 命令行测试：
   python call_librime.py --mode test
   python call_librime.py --mode console --input "congmingdeRime shurufa"

示例命令：
  - "congmingdeRime shurufa" - 输入拼音
  - "print schema list" - 打印方案列表
  - "select schema luna_pinyin" - 切换方案
  - "exit" - 退出
"""

import os
import sys
import subprocess
import ctypes
from pathlib import Path
from typing import Optional, List, Dict, Any


class RimeConsoleWrapper:
    """
    通过 subprocess 调用 rime_api_console.exe 的包装器
    简单易用，适合快速测试和交互式使用
    """
    
    def __init__(self, console_exe_path: Optional[str] = None):
        """
        初始化 Rime 控制台包装器
        
        Args:
            console_exe_path: rime_api_console.exe 的路径
                            如果为 None，会自动查找
        """
        if console_exe_path is None:
            # 自动查找 rime_api_console.exe
            # 假设在 librime/build/bin/Release/ 目录下
            project_root = Path(__file__).parent.parent.parent
            possible_paths = [
                project_root / "librime" / "build" / "bin" / "Release" / "rime_api_console.exe",
                project_root / "librime" / "build" / "bin" / "rime_api_console.exe",
                Path("librime/build/bin/Release/rime_api_console.exe"),
                Path("build/bin/Release/rime_api_console.exe"),
            ]
            
            for path in possible_paths:
                if path.exists():
                    console_exe_path = str(path.resolve())
                    break
            
            if console_exe_path is None:
                raise FileNotFoundError(
                    "找不到 rime_api_console.exe。请指定完整路径。\n"
                    "尝试的路径：\n" + "\n".join(str(p) for p in possible_paths)
                )
        
        if not os.path.exists(console_exe_path):
            raise FileNotFoundError(f"找不到文件: {console_exe_path}")
        
        self.console_exe_path = console_exe_path
        self.process: Optional[subprocess.Popen] = None
        self.work_dir = os.path.dirname(console_exe_path)
    
    def start(self) -> bool:
        """
        启动 rime_api_console.exe 进程
        
        Returns:
            是否成功启动
        """
        try:
            self.process = subprocess.Popen(
                [self.console_exe_path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=self.work_dir,
                bufsize=1
            )
            # 等待初始化完成（读取 "ready." 消息）
            output = ""
            while "ready." not in output.lower():
                line = self.process.stderr.readline()
                if not line:
                    break
                output += line
            return True
        except Exception as e:
            print(f"启动 rime_api_console.exe 失败: {e}")
            return False
    
    def send_command(self, command: str, timeout: float = 5.0) -> str:
        """
        发送命令到 rime_api_console.exe
        
        Args:
            command: 要发送的命令（例如："congmingdeRime shurufa"）
            timeout: 超时时间（秒）
        
        Returns:
            命令的输出
        """
        if self.process is None:
            raise RuntimeError("进程未启动，请先调用 start()")
        
        if not command.endswith('\n'):
            command += '\n'
        
        try:
            import time
            import threading
            
            output_lines = []
            output_lock = threading.Lock()
            
            def read_output():
                """在后台线程中读取输出"""
                try:
                    while True:
                        line = self.process.stdout.readline()
                        if not line:
                            break
                        with output_lock:
                            output_lines.append(line)
                except:
                    pass
            
            # 启动读取线程
            read_thread = threading.Thread(target=read_output, daemon=True)
            read_thread.start()
            
            # 发送命令
            self.process.stdin.write(command)
            self.process.stdin.flush()
            
            # 等待输出（简单实现）
            time.sleep(0.2)  # 给程序一些时间处理
            
            # 收集输出
            with output_lock:
                output = ''.join(output_lines)
                output_lines.clear()
            
            return output
        except Exception as e:
            print(f"发送命令失败: {e}")
            return ""
    
    def simulate_key_sequence(self, key_sequence: str) -> str:
        """
        模拟按键序列
        
        Args:
            key_sequence: 按键序列（例如："congmingdeRime shurufa"）
        
        Returns:
            输出结果
        """
        return self.send_command(key_sequence)
    
    def stop(self):
        """停止进程"""
        if self.process:
            try:
                self.process.stdin.write("exit\n")
                self.process.stdin.flush()
                self.process.wait(timeout=5)
            except:
                self.process.terminate()
            finally:
                self.process = None
    
    def __enter__(self):
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


class RimeDllWrapper:
    """
    通过 ctypes 直接调用 rime.dll 的包装器
    更灵活，可以直接访问所有 Rime API
    
    ⚠️ 注意: 当前为简化实现版本，部分功能可能不完整。
    建议先使用 RimeConsoleWrapper 进行测试。
    
    使用示例：
        from call_librime import RimeDllWrapper
        
        # 1. 创建包装器（自动查找 rime.dll）
        rime = RimeDllWrapper()
        # 或手动指定路径:
        # rime = RimeDllWrapper(dll_path="path/to/rime.dll")
        
        # 2. 初始化
        rime.initialize(app_name="rime.python")
        
        # 3. 创建会话
        session_id = rime.create_session()
        if session_id:
            # 4. 输入拼音
            rime.simulate_key_sequence(session_id, "congmingdeRime shurufa")
            
            # 5. 获取上下文（候选词）
            context = rime.get_context(session_id)
            if context:
                print(f"输入: {context.get('input', '')}")
                for i, candidate in enumerate(context.get('candidates', [])):
                    print(f"{i+1}. {candidate.get('text', '')}")
            
            # 6. 清理会话
            rime.destroy_session(session_id)
        
        # 7. 清理资源
        rime.finalize()
    
    更多示例请参考:
        - example_use_dll_wrapper.py
        - USAGE_RIME_DLL.md
    """
    
    def __init__(self, dll_path: Optional[str] = None):
        """
        初始化 Rime DLL 包装器
        
        Args:
            dll_path: Rime 动态库路径（Windows: ``rime.dll``；macOS: ``librime*.dylib``；
                      Linux: ``librime.so*``）
                    如果为 None，会自动查找
        """
        if dll_path is None:
            # 自动查找 Rime 动态库
            project_root = Path(__file__).parent.parent.parent
            possible_paths = []

            if sys.platform == "darwin":
                for pattern_root in (project_root, project_root / "lib"):
                    for candidate in sorted(pattern_root.glob("librime*.dylib")):
                        if candidate not in possible_paths:
                            possible_paths.append(candidate)
                for candidate in (
                    project_root / "lib" / "librime.dylib",
                    project_root / "librime.dylib",
                ):
                    if candidate not in possible_paths:
                        possible_paths.append(candidate)
            elif sys.platform.startswith("linux"):
                for pattern_root in (project_root, project_root / "lib"):
                    for pattern in ("librime.so", "librime.so.*", "librime*.so", "librime*.so.*"):
                        for candidate in sorted(pattern_root.glob(pattern)):
                            if candidate not in possible_paths:
                                possible_paths.append(candidate)
            else:
                possible_paths.extend(
                    [
                        project_root / "rime.dll",
                        project_root / "lib" / "rime.dll",
                        project_root / "librime" / "build" / "bin" / "Release" / "rime.dll",
                        project_root / "librime" / "build" / "bin" / "rime.dll",
                        Path("librime/build/bin/Release/rime.dll"),
                        Path("build/bin/Release/rime.dll"),
                    ]
                )

            for env_var in ("RIME_LIBRARY", "RIME_DLL"):
                env_path = os.environ.get(env_var, "").strip()
                if env_path:
                    dll_path = env_path
                    break
            
            if dll_path is None:
                for path in possible_paths:
                    if path.exists():
                        dll_path = str(path.resolve())
                        break
            
            if dll_path is None:
                raise FileNotFoundError(
                    "找不到 Rime 动态库。请指定完整路径。\n"
                    "尝试的路径：\n" + "\n".join(str(p) for p in possible_paths)
                )
        
        if not os.path.exists(dll_path):
            raise FileNotFoundError(f"找不到文件: {dll_path}")
        
        # 加载动态库
        try:
            # Windows 下先把动态库目录加入搜索路径，确保能找到依赖。
            dll_dir = os.path.dirname(dll_path)
            if sys.platform == 'win32':
                os.add_dll_directory(dll_dir)
            
            self.dll = ctypes.CDLL(dll_path)
        except Exception as e:
            raise RuntimeError(
                f"加载 Rime 动态库失败: {e}\n"
                "提示: 确保所选动态库及其依赖位于可加载路径中"
            )
        
        self.dll_path = dll_path
        self.session_id = 0
        self.api = None
        self._rime_set_input = None  # RimeSetInput(session_id, utf8) if DLL supports it
        self._setup_api()
        self._bind_set_input()
    
    def _setup_api(self):
        """设置 API 函数签名"""
        # rime_get_api() 返回 RimeApi* 指针
        self.dll.rime_get_api.restype = ctypes.c_void_p
        self.dll.rime_get_api.argtypes = []
        
        # 获取 API 指针
        try:
            self.api_ptr = self.dll.rime_get_api()
            if not self.api_ptr:
                raise RuntimeError("无法获取 RimeApi 指针")
        except Exception as e:
            raise RuntimeError(f"调用 rime_get_api() 失败: {e}")
        
        # 检查 DLL 导出的函数
        self._check_exported_functions()
        
        # 定义 RimeApi 结构体的关键函数指针
        # 注意：这是简化版本，完整实现需要定义所有函数指针
        self._setup_function_pointers()

    def _bind_set_input(self) -> None:
        """Prefer RimeSetInput (librime 1.9+) over RimeSimulateKeySequence for bulk pinyin."""
        for name in ("RimeSetInput", "rime_set_input"):
            if hasattr(self.dll, name):
                try:
                    fn = getattr(self.dll, name)
                    fn.argtypes = [ctypes.c_uint64, ctypes.c_char_p]
                    fn.restype = ctypes.c_int
                    self._rime_set_input = fn
                    return
                except Exception:
                    continue

    def uses_set_input(self) -> bool:
        return self._rime_set_input is not None

    def _check_exported_functions(self):
        """检查 DLL 导出的函数"""
        exported_funcs = []
        for name in dir(self.dll):
            if not name.startswith('_'):
                try:
                    attr = getattr(self.dll, name)
                    if isinstance(attr, ctypes._FuncPtr):
                        exported_funcs.append(name)
                except:
                    pass
        
        # 检查关键函数
        self.has_direct_functions = any(
            name in exported_funcs 
            for name in ['RimeSetup', 'RimeInitialize', 'RimeCreateSession']
        )
        
        if not self.has_direct_functions:
            # 打印可用的函数（用于调试）
            if exported_funcs:
                print(f"提示: DLL 导出的函数: {', '.join(exported_funcs[:10])}...")
            else:
                print("提示: 未找到导出的函数，可能需要通过 API 结构体访问")
    
    def _setup_function_pointers(self):
        """设置函数指针（简化版本）"""
        # 定义基本类型
        RimeSessionId = ctypes.c_uint64
        Bool = ctypes.c_int
        
        # 从 API 结构体中提取函数指针
        # 由于 RimeApi 是一个包含函数指针的结构体，我们需要通过偏移量访问
        # 这里使用一个更实用的方法：直接定义需要的函数
        
        # setup
        self._setup = self._get_function_pointer(0, 
            [ctypes.c_void_p], None)
        
        # initialize
        self._initialize = self._get_function_pointer(1,
            [ctypes.c_void_p], None)
        
        # finalize
        self._finalize = self._get_function_pointer(2,
            [], None)
        
        # create_session
        self._create_session = self._get_function_pointer(3,
            [], RimeSessionId)
        
        # destroy_session
        self._destroy_session = self._get_function_pointer(4,
            [RimeSessionId], Bool)
        
        # simulate_key_sequence
        self._simulate_key_sequence = self._get_function_pointer(5,
            [RimeSessionId, ctypes.c_char_p], Bool)
        
        # get_context (简化版本)
        self._get_context = self._get_function_pointer(6,
            [RimeSessionId, ctypes.c_void_p], Bool)
        
        # free_context
        self._free_context = self._get_function_pointer(7,
            [ctypes.c_void_p], Bool)
        
        # get_commit
        self._get_commit = self._get_function_pointer(8,
            [RimeSessionId, ctypes.c_void_p], Bool)
        
        # free_commit
        self._free_commit = self._get_function_pointer(9,
            [ctypes.c_void_p], Bool)
    
    def _get_function_pointer(self, offset, argtypes, restype):
        """从 API 结构体中获取函数指针（简化实现）"""
        # 这是一个简化的实现
        # 实际使用时，建议使用更直接的方法
        return None
    
    def initialize(self, app_name: str = "rime.python", 
                   shared_data_dir: Optional[str] = None,
                   user_data_dir: Optional[str] = None):
        """
        初始化 Rime
        
        Args:
            app_name: 应用程序名称
            shared_data_dir: 共享数据目录（可选，默认使用 DLL 所在目录）
            user_data_dir: 用户数据目录（可选，默认使用 DLL 所在目录）
        """
        # 定义 RimeTraits 结构
        class RimeTraits(ctypes.Structure):
            _fields_ = [
                ("data_size", ctypes.c_int),
                ("shared_data_dir", ctypes.c_char_p),
                ("user_data_dir", ctypes.c_char_p),
                ("distribution_name", ctypes.c_char_p),
                ("distribution_code_name", ctypes.c_char_p),
                ("distribution_version", ctypes.c_char_p),
                ("app_name", ctypes.c_char_p),
            ]
        
        # 设置 traits
        traits = RimeTraits()
        traits.data_size = ctypes.sizeof(RimeTraits) - ctypes.sizeof(ctypes.c_int)
        traits.app_name = app_name.encode('utf-8')
        
        # 设置数据目录（如果提供）
        if shared_data_dir:
            traits.shared_data_dir = shared_data_dir.encode('utf-8')
        elif self.dll_path:
            # DLL 在 Release 目录，但数据文件在上一级目录（build/bin/）
            dll_dir = os.path.dirname(self.dll_path)  # build/bin/Release
            parent_dir = os.path.dirname(dll_dir)  # build/bin
            
            # 检查数据文件位置
            # 优先检查 parent_dir（build/bin），因为数据文件通常在那里
            if os.path.exists(os.path.join(parent_dir, 'luna_pinyin.schema.yaml')):
                traits.shared_data_dir = parent_dir.encode('utf-8')
                print(f"提示: 使用数据目录: {parent_dir}")
            elif os.path.exists(os.path.join(dll_dir, 'build', 'luna_pinyin.schema.yaml')):
                # 数据在 build/bin/Release/build/ 目录
                traits.shared_data_dir = dll_dir.encode('utf-8')
                print(f"提示: 使用数据目录: {dll_dir}")
            else:
                # 默认使用 DLL 所在目录
                traits.shared_data_dir = dll_dir.encode('utf-8')
                print(f"警告: 未找到数据文件，使用: {dll_dir}")
        
        if user_data_dir:
            traits.user_data_dir = user_data_dir.encode('utf-8')
        elif self.dll_path:
            dll_dir = os.path.dirname(self.dll_path)
            parent_dir = os.path.dirname(dll_dir)
            # 用户数据目录通常和共享数据目录相同
            if os.path.exists(os.path.join(parent_dir, 'luna_pinyin.schema.yaml')):
                traits.user_data_dir = parent_dir.encode('utf-8')
            else:
                traits.user_data_dir = dll_dir.encode('utf-8')
        
        # 尝试直接调用导出的函数（如果 DLL 导出了这些函数）
        # 检查可用的函数名
        setup_func_name = None
        init_func_name = None
        
        # 检查各种可能的函数名
        for name in ['RimeSetup', 'rime_setup', 'RimeSetupLogging']:
            if hasattr(self.dll, name):
                try:
                    # 尝试调用以验证
                    func = getattr(self.dll, name)
                    if callable(func):
                        setup_func_name = name
                        break
                except:
                    pass
        
        for name in ['RimeInitialize', 'rime_initialize']:
            if hasattr(self.dll, name):
                try:
                    func = getattr(self.dll, name)
                    if callable(func):
                        init_func_name = name
                        break
                except:
                    pass
        
        if not setup_func_name or not init_func_name:
            # 如果没有直接导出的函数，尝试通过 API 结构体访问
            try:
                self._initialize_via_api(traits)
                print(f"✓ Rime 初始化完成 (通过 API 结构体, app_name: {app_name})")
                return
            except Exception as api_error:
                # 如果 API 方式也失败，提示用户使用替代方案
                available = []
                for name in dir(self.dll):
                    if 'rime' in name.lower() or 'Rime' in name:
                        try:
                            attr = getattr(self.dll, name)
                            if callable(attr):
                                available.append(name)
                        except:
                            pass
                
                error_msg = (
                    "无法找到 RimeSetup 或 RimeInitialize 函数。\n"
                    f"找到的相关函数: {', '.join(available[:5]) if available else '无'}\n"
                    f"API 结构体访问也失败: {api_error}\n\n"
                    "提示: RimeDllWrapper 当前为简化实现，建议使用 RimeConsoleWrapper:\n"
                    "  from call_librime import RimeConsoleWrapper\n"
                    "  wrapper = RimeConsoleWrapper()\n"
                    "  wrapper.start()\n"
                    "  result = wrapper.simulate_key_sequence('your input')\n"
                    "  wrapper.stop()"
                )
                raise RuntimeError(error_msg)
        
        # 调用 setup
        try:
            setup_func = getattr(self.dll, setup_func_name)
            setup_func.argtypes = [ctypes.POINTER(RimeTraits)]
            setup_func.restype = None
            setup_func(ctypes.byref(traits))
        except Exception as e:
            raise RuntimeError(f"调用 {setup_func_name} 失败: {e}")
        
        # 调用 initialize
        try:
            init_func = getattr(self.dll, init_func_name)
            init_func.argtypes = [ctypes.POINTER(RimeTraits)]
            init_func.restype = None
            init_func(None)  # 可以传 None
        except Exception as e:
            raise RuntimeError(f"调用 {init_func_name} 失败: {e}")
        
        # 启动维护模式（加载数据）
        self._start_maintenance()
        
        print(f"✓ Rime 初始化完成 (app_name: {app_name})")
    
    def _start_maintenance(self):
        """启动维护模式，加载数据文件"""
        try:
            if hasattr(self.dll, 'RimeStartMaintenance'):
                self.dll.RimeStartMaintenance.argtypes = [ctypes.c_int]
                self.dll.RimeStartMaintenance.restype = ctypes.c_int
                full_check = 1  # True
                if self.dll.RimeStartMaintenance(full_check):
                    # 等待维护线程完成
                    if hasattr(self.dll, 'RimeJoinMaintenanceThread'):
                        self.dll.RimeJoinMaintenanceThread.restype = None
                        self.dll.RimeJoinMaintenanceThread()
                    print("提示: 维护模式完成，数据文件已加载")
                else:
                    print("提示: 维护模式未启动（可能数据已加载）")
            else:
                # 尝试通过 API 结构体访问
                print("提示: 无法直接调用维护函数，尝试通过 API...")
        except Exception as e:
            # 如果失败，不影响主要功能，但给出提示
            print(f"提示: 启动维护模式失败: {e}")
            print("提示: 如果无候选词，请确保已运行 rime_deployer.exe 编译数据文件")
    
    def _initialize_via_api(self, traits):
        """通过 API 结构体初始化（备用方案）"""
        # 定义函数指针类型
        SetupFunc = ctypes.CFUNCTYPE(None, ctypes.POINTER(type(traits)))
        InitFunc = ctypes.CFUNCTYPE(None, ctypes.POINTER(type(traits)))
        
        # 在64位系统上，指针大小为8字节；32位为4字节
        ptr_size = ctypes.sizeof(ctypes.c_void_p)
        int_size = ctypes.sizeof(ctypes.c_int)
        
        # RimeApi 结构体布局：
        # - data_size: int (4或8字节，取决于系统)
        # - setup: 函数指针 (ptr_size 字节)
        # - set_notification_handler: 函数指针
        # - initialize: 函数指针
        # ...
        
        # 将 API 指针转换为可访问的内存
        # 创建一个足够大的缓冲区来读取前几个函数指针
        buffer_size = int_size + ptr_size * 10
        api_buffer = (ctypes.c_byte * buffer_size).from_address(self.api_ptr)
        
        # 读取 setup 函数指针（跳过 data_size）
        setup_ptr_bytes = bytes(api_buffer[int_size:int_size + ptr_size])
        setup_ptr = int.from_bytes(setup_ptr_bytes, byteorder='little', signed=False)
        
        # 读取 initialize 函数指针（跳过 data_size + setup + set_notification_handler）
        # set_notification_handler 在 initialize 之前
        init_offset = int_size + ptr_size * 2  # data_size + setup + set_notification_handler
        init_ptr_bytes = bytes(api_buffer[init_offset:init_offset + ptr_size])
        init_ptr = int.from_bytes(init_ptr_bytes, byteorder='little', signed=False)
        
        if not setup_ptr or not init_ptr:
            raise RuntimeError("无法从 API 结构体中提取函数指针")
        
        # 创建函数对象并调用
        try:
            setup = SetupFunc(setup_ptr)
            setup(ctypes.byref(traits))
        except Exception as e:
            raise RuntimeError(f"调用 setup 函数失败: {e}")
        
        try:
            init = InitFunc(init_ptr)
            init(None)
        except Exception as e:
            raise RuntimeError(f"调用 initialize 函数失败: {e}")
    
    def create_session(self) -> int:
        """
        创建会话
        
        Returns:
            会话 ID
        """
        # 简化实现：直接调用 DLL 函数
        # 注意：这需要正确的函数签名
        try:
            # 尝试直接调用（如果 DLL 导出了这些函数）
            if hasattr(self.dll, 'RimeCreateSession'):
                self.dll.RimeCreateSession.restype = ctypes.c_uint64
                session_id = self.dll.RimeCreateSession()
                self.session_id = session_id
                
                # 尝试选择默认的输入方案（如果当前没有方案）
                if session_id:
                    self._ensure_schema_selected(session_id)
                
                return session_id
            else:
                # 使用 API 结构体中的函数指针
                # 这里需要更复杂的实现
                print("警告: 无法直接创建会话，请使用完整实现")
                return 0
        except Exception as e:
            print(f"创建会话失败: {e}")
            return 0
    
    def _ensure_schema_selected(self, session_id: int):
        """确保已选择输入方案"""
        try:
            # 检查当前方案
            if hasattr(self.dll, 'RimeGetCurrentSchema'):
                schema_buffer = (ctypes.c_char * 100)()
                self.dll.RimeGetCurrentSchema.argtypes = [ctypes.c_uint64, ctypes.c_char_p, ctypes.c_size_t]
                self.dll.RimeGetCurrentSchema.restype = ctypes.c_int
                
                if self.dll.RimeGetCurrentSchema(session_id, schema_buffer, 100):
                    current_schema = schema_buffer.value.decode('utf-8') if schema_buffer.value else None
                    if current_schema:
                        return  # 已有方案，不需要选择
            
            # 尝试选择 luna_pinyin（最常见的方案）
            if hasattr(self.dll, 'RimeSelectSchema'):
                self.dll.RimeSelectSchema.argtypes = [ctypes.c_uint64, ctypes.c_char_p]
                self.dll.RimeSelectSchema.restype = ctypes.c_int
                
                # 尝试几个常见的方案
                for schema in ['luna_pinyin', 'pinyin_simp', 'cangjie5']:
                    if self.dll.RimeSelectSchema(session_id, schema.encode('utf-8')):
                        print(f"提示: 已选择输入方案: {schema}")
                        return
        except Exception as e:
            # 如果失败，不影响主要功能
            pass
    
    def select_schema(self, session_id: int, schema_id: str) -> bool:
        """
        选择输入方案
        
        Args:
            session_id: 会话 ID
            schema_id: 方案 ID（例如：'luna_pinyin'）
        
        Returns:
            是否成功
        """
        try:
            if hasattr(self.dll, 'RimeSelectSchema'):
                self.dll.RimeSelectSchema.argtypes = [ctypes.c_uint64, ctypes.c_char_p]
                self.dll.RimeSelectSchema.restype = ctypes.c_int
                return bool(self.dll.RimeSelectSchema(session_id, schema_id.encode('utf-8')))
            return False
        except Exception as e:
            print(f"选择方案失败: {e}")
            return False
    
    def get_current_schema(self, session_id: int) -> Optional[str]:
        """
        获取当前输入方案
        
        Args:
            session_id: 会话 ID
        
        Returns:
            方案 ID，失败返回 None
        """
        try:
            if hasattr(self.dll, 'RimeGetCurrentSchema'):
                schema_buffer = (ctypes.c_char * 100)()
                self.dll.RimeGetCurrentSchema.argtypes = [ctypes.c_uint64, ctypes.c_char_p, ctypes.c_size_t]
                self.dll.RimeGetCurrentSchema.restype = ctypes.c_int
                
                if self.dll.RimeGetCurrentSchema(session_id, schema_buffer, 100):
                    return schema_buffer.value.decode('utf-8') if schema_buffer.value else None
            return None
        except Exception as e:
            print(f"获取当前方案失败: {e}")
            return None
    
    def destroy_session(self, session_id: int) -> bool:
        """销毁会话"""
        try:
            if hasattr(self.dll, 'RimeDestroySession'):
                self.dll.RimeDestroySession.argtypes = [ctypes.c_uint64]
                self.dll.RimeDestroySession.restype = ctypes.c_int
                return bool(self.dll.RimeDestroySession(session_id))
            return False
        except Exception as e:
            print(f"销毁会话失败: {e}")
            return False
    
    def set_input(self, session_id: int, raw_input: str) -> bool:
        """
        直接设置会话的原始输入（与 Rime 内部 buffer 一致），一次调用完成。

        需要较新的 librime（导出 ``RimeSetInput``）。整句拼音评测应优先用本方法，
        避免 :meth:`simulate_key_sequence` 在 C++ 层对字符串逐键 ``ProcessKey`` 的开销。
        """
        if self._rime_set_input is None:
            return False
        try:
            return bool(self._rime_set_input(session_id, raw_input.encode("utf-8")))
        except Exception as e:
            print(f"RimeSetInput 失败: {e}")
            return False

    def feed_input(self, session_id: int, raw_input: str) -> bool:
        """Set raw input in one shot when supported, else fall back to key simulation."""
        if self.set_input(session_id, raw_input):
            return True
        return self.simulate_key_sequence(session_id, raw_input)

    def feed_pinyin(self, session_id: int, pinyin: str) -> bool:
        """Backward-compatible alias for :meth:`feed_input`."""
        return self.feed_input(session_id, pinyin)

    def simulate_key_sequence(self, session_id: int, key_sequence: str) -> bool:
        """
        调用 ``RimeSimulateKeySequence``：Python 侧只调一次 DLL，但 librime 内部仍会
        把 ``key_sequence`` 拆成按键并逐键处理；长拼音串时比 :meth:`set_input` 慢。
        
        Args:
            session_id: 会话 ID
            key_sequence: 按键序列（例如："congmingdeRime shurufa"）
        
        Returns:
            是否成功
        """
        try:
            if hasattr(self.dll, 'RimeSimulateKeySequence'):
                self.dll.RimeSimulateKeySequence.argtypes = [
                    ctypes.c_uint64, ctypes.c_char_p
                ]
                self.dll.RimeSimulateKeySequence.restype = ctypes.c_int
                return bool(self.dll.RimeSimulateKeySequence(
                    session_id, key_sequence.encode('utf-8')
                ))
            else:
                print("警告: RimeSimulateKeySequence 函数不可用")
                return False
        except Exception as e:
            print(f"模拟按键序列失败: {e}")
            return False
    
    def get_context(self, session_id: int) -> Optional[Dict[str, Any]]:
        """
        获取输入上下文（候选词等）
        
        Args:
            session_id: 会话 ID
        
        Returns:
            包含输入和候选词的字典，失败返回 None
        """
        try:
            # 定义 RimeComposition 结构
            class RimeComposition(ctypes.Structure):
                _fields_ = [
                    ("length", ctypes.c_int),
                    ("cursor_pos", ctypes.c_int),
                    ("sel_start", ctypes.c_int),
                    ("sel_end", ctypes.c_int),
                    ("preedit", ctypes.c_char_p),
                ]
            
            # 定义 RimeCandidate 结构
            class RimeCandidate(ctypes.Structure):
                _fields_ = [
                    ("text", ctypes.c_char_p),
                    ("comment", ctypes.c_char_p),
                    ("reserved", ctypes.c_void_p),
                ]
            
            # 定义 RimeMenu 结构
            class RimeMenu(ctypes.Structure):
                _fields_ = [
                    ("num_candidates", ctypes.c_int),
                    ("candidates", ctypes.POINTER(RimeCandidate)),
                    ("page_no", ctypes.c_int),
                    ("page_size", ctypes.c_int),
                    ("is_last_page", ctypes.c_int),
                    ("highlighted_candidate_index", ctypes.c_int),
                    ("select_keys", ctypes.c_char_p),
                ]
            
            # 定义 RimeContext 结构
            class RimeContext(ctypes.Structure):
                _fields_ = [
                    ("data_size", ctypes.c_int),
                    ("composition", RimeComposition),
                    ("menu", RimeMenu),
                    ("commit_text_preview", ctypes.c_char_p),
                    ("select_labels", ctypes.POINTER(ctypes.c_char_p)),
                ]
            
            # 尝试通过 API 获取上下文
            context_func_name = None
            for name in ['RimeGetContext', 'rime_get_context']:
                if hasattr(self.dll, name):
                    try:
                        func = getattr(self.dll, name)
                        if callable(func):
                            context_func_name = name
                            break
                    except:
                        pass
            
            if not context_func_name:
                print("   调试: 未找到 RimeGetContext 函数，尝试通过 API 结构体访问")
                # 可以尝试通过 API 结构体访问，但这里先返回基本信息
                # 尝试使用 RimeGetInput 作为备选
                if hasattr(self.dll, 'RimeGetInput'):
                    self.dll.RimeGetInput.argtypes = [ctypes.c_uint64]
                    self.dll.RimeGetInput.restype = ctypes.c_char_p
                    input_text = self.dll.RimeGetInput(session_id)
                    
                    return {
                        'input': input_text.decode('utf-8') if input_text else '',
                        'candidates': []
                    }
                return None
            
            # 创建并初始化 RimeContext
            # 注意：RimeContext 使用版本控制结构，data_size 需要正确设置
            context = RimeContext()
            # data_size 应该是结构体大小减去 data_size 字段本身的大小
            # 但为了兼容性，我们使用完整的结构体大小
            context.data_size = ctypes.sizeof(RimeContext) - ctypes.sizeof(ctypes.c_int)
            
            # 清零结构体，确保所有字段都是初始化的
            ctypes.memset(ctypes.byref(context), 0, ctypes.sizeof(RimeContext))
            context.data_size = ctypes.sizeof(RimeContext) - ctypes.sizeof(ctypes.c_int)
            
            # 调用 get_context
            get_context_func = getattr(self.dll, context_func_name)
            get_context_func.argtypes = [ctypes.c_uint64, ctypes.POINTER(RimeContext)]
            get_context_func.restype = ctypes.c_int
            
            # 调试模式（需要在调用前定义）
            debug_mode = os.environ.get('RIME_DEBUG', '').lower() in ('1', 'true', 'yes')
            
            result = get_context_func(session_id, ctypes.byref(context))
            if debug_mode:
                print(f"   调试: get_context 返回值 = {result}")
                print(f"   调试: context.data_size = {context.data_size}")
                print(f"   调试: context.composition.length = {context.composition.length}")
                print(f"   调试: context.menu.num_candidates = {context.menu.num_candidates}")
                # 检查 candidates 指针的实际值
                if context.menu.candidates:
                    ptr_val = ctypes.cast(context.menu.candidates, ctypes.c_void_p).value
                    print(f"   调试: context.menu.candidates 实际值 = {hex(ptr_val) if ptr_val else 'NULL'}")
                else:
                    print(f"   调试: context.menu.candidates 为 None")
            
            if not result:
                if debug_mode:
                    print("   调试: get_context 函数返回 False")
                return None
            
            candidates_ptr_value = 0
            if context.menu.candidates:
                try:
                    candidates_ptr_value = ctypes.cast(context.menu.candidates, ctypes.c_void_p).value or 0
                except Exception:
                    candidates_ptr_value = 0

            # 某些方案会返回非空但明显无效的候选指针（如 0x1）；此时改走迭代器，避免直接解引用崩溃。
            invalid_candidates_ptr = candidates_ptr_value < 4096

            # 如果 candidates 指针为空或明显无效，尝试使用候选词列表迭代器
            candidates = []  # 初始化为空列表
            if invalid_candidates_ptr:
                if debug_mode:
                    print(
                        f"   调试: candidates 指针无效 ({hex(candidates_ptr_value) if candidates_ptr_value else 'NULL'})，"
                        " 尝试使用候选词列表迭代器"
                    )
                candidates = self._get_candidates_via_iterator(session_id, debug_mode)
                if candidates:
                    if debug_mode:
                        print(f"   调试: 通过迭代器成功获取 {len(candidates)} 个候选词")
                    # 使用迭代器获取的候选词，跳过从 context.menu 获取
                    use_iterator_candidates = True
                else:
                    if debug_mode:
                        print("   调试: 迭代器也失败，尝试从 context.menu 获取")
                    use_iterator_candidates = False
            else:
                use_iterator_candidates = False
            
            # 提取输入文本
            input_text = ""
            if context.composition.preedit:
                input_text = context.composition.preedit.decode('utf-8')
            
            # 调试信息（仅在开发时启用）
            debug_mode = os.environ.get('RIME_DEBUG', '').lower() in ('1', 'true', 'yes')
            if debug_mode:
                print(f"   调试: composition.length = {context.composition.length}")
                print(f"   调试: menu.num_candidates = {context.menu.num_candidates}")
                print(
                    f"   调试: menu.candidates 指针 = "
                    f"{hex(candidates_ptr_value) if candidates_ptr_value else 'None'}"
                )
            
            # 提取候选词（如果还没有通过迭代器获取）
            if not use_iterator_candidates:
                # 检查是否有候选词 - 需要检查指针是否有效（不为 None 且不为 0）
                candidates_ptr = context.menu.candidates
                num_candidates = context.menu.num_candidates
                
                # 调试：检查条件
                if debug_mode:
                    print(f"   调试: candidates_ptr = {candidates_ptr}")
                    print(f"   调试: candidates_ptr_value = {hex(candidates_ptr_value) if candidates_ptr_value else 'None'}")
                    print(f"   调试: num_candidates > 0 = {num_candidates > 0}")
                
                has_candidates = (
                    candidates_ptr is not None
                    and candidates_ptr_value >= 4096
                    and num_candidates > 0
                )
                
                if has_candidates:
                    if debug_mode:
                        print(f"   调试: 开始提取 {num_candidates} 个候选词")
                        # 检查指针的实际值
                        try:
                            ptr_value = ctypes.cast(candidates_ptr, ctypes.c_void_p).value
                            print(f"   调试: 指针值 = {hex(ptr_value) if ptr_value else 'NULL'}")
                        except:
                            pass
                    
                    # candidates 是指向 RimeCandidate 数组的指针，需要正确访问
                    # 方法1: 直接使用指针索引访问
                    try:
                        # 将指针转换为指向单个 RimeCandidate 的指针
                        candidate_ptr_type = ctypes.POINTER(RimeCandidate)
                        base_ptr = ctypes.cast(candidates_ptr, candidate_ptr_type)
                        
                        for i in range(num_candidates):
                            try:
                                # 通过指针偏移访问数组元素
                                cand = base_ptr[i]
                                text = cand.text.decode('utf-8') if cand.text else ""
                                comment = cand.comment.decode('utf-8') if cand.comment else ""
                                candidates.append({
                                    'text': text,
                                    'comment': comment
                                })
                                if debug_mode:
                                    print(f"   调试: 候选词 {i+1}: {text}")
                            except Exception as e:
                                if debug_mode:
                                    print(f"   调试: 提取候选词 {i} 失败: {e}")
                                    import traceback
                                    traceback.print_exc()
                                break
                    except Exception as e:
                        if debug_mode:
                            print(f"   调试: 方法1失败，尝试方法2: {e}")
                        # 方法2: 使用数组类型转换
                        try:
                            candidates_array = ctypes.cast(
                                candidates_ptr,
                                ctypes.POINTER(RimeCandidate * num_candidates)
                            ).contents
                            
                            for i in range(num_candidates):
                                try:
                                    cand = candidates_array[i]
                                    text = cand.text.decode('utf-8') if cand.text else ""
                                    comment = cand.comment.decode('utf-8') if cand.comment else ""
                                    candidates.append({
                                        'text': text,
                                        'comment': comment
                                    })
                                    if debug_mode:
                                        print(f"   调试: 候选词 {i+1}: {text}")
                                except Exception as e2:
                                    if debug_mode:
                                        print(f"   调试: 提取候选词 {i} 失败: {e2}")
                                    break
                        except Exception as e2:
                            if debug_mode:
                                print(f"   调试: 方法2也失败: {e2}")
                                import traceback
                                traceback.print_exc()
                else:
                    if debug_mode:
                        print(f"   调试: 无候选词 (candidates={context.menu.candidates}, num={context.menu.num_candidates})")
            else:
                if debug_mode:
                    print(f"   调试: 无候选词 (candidates={context.menu.candidates}, num={context.menu.num_candidates})")
            
            commit_preview = ""
            try:
                if context.commit_text_preview:
                    commit_preview = context.commit_text_preview.decode("utf-8")
            except Exception:
                commit_preview = ""

            result = {
                'input': input_text,
                'commit_text_preview': commit_preview,
                'candidates': candidates,
                'composition': {
                    'length': context.composition.length,
                    'cursor_pos': context.composition.cursor_pos,
                    'sel_start': context.composition.sel_start,
                    'sel_end': context.composition.sel_end,
                },
                'menu': {
                    'page_no': context.menu.page_no,
                    'page_size': context.menu.page_size,
                    'is_last_page': bool(context.menu.is_last_page),
                    'highlighted_index': context.menu.highlighted_candidate_index,
                }
            }
            
            # 释放上下文（如果 DLL 导出了 free_context）
            if hasattr(self.dll, 'RimeFreeContext'):
                free_func = getattr(self.dll, 'RimeFreeContext')
                free_func.argtypes = [ctypes.POINTER(RimeContext)]
                free_func.restype = ctypes.c_int
                free_func(ctypes.byref(context))
            elif hasattr(self.dll, 'rime_free_context'):
                free_func = getattr(self.dll, 'rime_free_context')
                free_func.argtypes = [ctypes.POINTER(RimeContext)]
                free_func.restype = ctypes.c_int
                free_func(ctypes.byref(context))
            
            return result
            
        except Exception as e:
            print(f"获取上下文失败: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def finalize(self):
        """清理资源"""
        try:
            if hasattr(self.dll, 'RimeFinalize'):
                self.dll.RimeFinalize()
                print("✓ Rime 已清理")
        except Exception as e:
            print(f"清理失败: {e}")
    
    def _get_candidates_via_iterator(self, session_id: int, debug_mode: bool = False) -> List[Dict[str, str]]:
        """
        使用候选词列表迭代器获取候选词（备用方法）
        
        Args:
            session_id: 会话 ID
            debug_mode: 是否启用调试模式
        
        Returns:
            候选词列表
        """
        candidates = []
        try:
            # 定义 RimeCandidate 结构（如果还没有定义）
            class RimeCandidate(ctypes.Structure):
                _fields_ = [
                    ("text", ctypes.c_char_p),
                    ("comment", ctypes.c_char_p),
                    ("reserved", ctypes.c_void_p),
                ]
            
            # 定义 RimeCandidateListIterator 结构
            class RimeCandidateListIterator(ctypes.Structure):
                _fields_ = [
                    ("ptr", ctypes.c_void_p),
                    ("index", ctypes.c_int),
                    ("candidate", RimeCandidate),
                ]
            
            # 检查是否有迭代器函数
            if not hasattr(self.dll, 'RimeCandidateListBegin'):
                if debug_mode:
                    print("   调试: 未找到 RimeCandidateListBegin 函数")
                return candidates
            
            # 初始化迭代器
            iterator = RimeCandidateListIterator()
            ctypes.memset(ctypes.byref(iterator), 0, ctypes.sizeof(RimeCandidateListIterator))
            
            # 调用 candidate_list_begin
            begin_func = getattr(self.dll, 'RimeCandidateListBegin')
            begin_func.argtypes = [ctypes.c_uint64, ctypes.POINTER(RimeCandidateListIterator)]
            begin_func.restype = ctypes.c_int
            
            if not begin_func(session_id, ctypes.byref(iterator)):
                if debug_mode:
                    print("   调试: candidate_list_begin 返回 False")
                return candidates
            
            # 调用 candidate_list_next 遍历候选词
            if hasattr(self.dll, 'RimeCandidateListNext'):
                next_func = getattr(self.dll, 'RimeCandidateListNext')
                next_func.argtypes = [ctypes.POINTER(RimeCandidateListIterator)]
                next_func.restype = ctypes.c_int
                
                while next_func(ctypes.byref(iterator)):
                    try:
                        text = iterator.candidate.text.decode('utf-8') if iterator.candidate.text else ""
                        comment = iterator.candidate.comment.decode('utf-8') if iterator.candidate.comment else ""
                        candidates.append({
                            'text': text,
                            'comment': comment
                        })
                        if debug_mode:
                            print(f"   调试: 迭代器候选词 {iterator.index + 1}: {text}")
                    except Exception as e:
                        if debug_mode:
                            print(f"   调试: 提取迭代器候选词失败: {e}")
                        break
                
                # 清理迭代器
                if hasattr(self.dll, 'RimeCandidateListEnd'):
                    end_func = getattr(self.dll, 'RimeCandidateListEnd')
                    end_func.argtypes = [ctypes.POINTER(RimeCandidateListIterator)]
                    end_func.restype = None
                    end_func(ctypes.byref(iterator))
        except Exception as e:
            if debug_mode:
                print(f"   调试: 使用迭代器获取候选词失败: {e}")
                import traceback
                traceback.print_exc()
        
        return candidates


def test_console_wrapper():
    """测试控制台包装器"""
    print("=" * 60)
    print("测试 Rime 控制台包装器")
    print("=" * 60)
    
    try:
        wrapper = RimeConsoleWrapper()
        print(f"找到 rime_api_console.exe: {wrapper.console_exe_path}")
        
        if wrapper.start():
            print("✓ 成功启动 rime_api_console.exe")
            print("\n提示：")
            print("  - 使用 wrapper.simulate_key_sequence('your input') 来输入")
            print("  - 使用 wrapper.send_command('command') 来发送命令")
            print("  - 使用 wrapper.stop() 来停止")
            print("\n示例命令：")
            print("  - 'congmingdeRime shurufa' - 输入拼音")
            print("  - 'print schema list' - 打印方案列表")
            print("  - 'exit' - 退出")
            
            # 示例：输入拼音
            print("\n尝试输入: congmingdeRime shurufa")
            result = wrapper.simulate_key_sequence("congmingdeRime shurufa")
            if result:
                print(f"输出:\n{result}")
            else:
                print("（无输出，可能需要使用交互式模式查看结果）")
            
            wrapper.stop()
        else:
            print("✗ 启动失败")
    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()


def test_dll_wrapper():
    """测试 DLL 包装器"""
    print("=" * 60)
    print("测试 Rime DLL 包装器")
    print("=" * 60)
    
    try:
        wrapper = RimeDllWrapper()
        print(f"找到 rime.dll: {wrapper.dll_path}")
        
        # 初始化
        print("\n初始化 Rime...")
        wrapper.initialize()
        
        # 创建会话
        print("创建会话...")
        session_id = wrapper.create_session()
        if session_id:
            print(f"✓ 会话创建成功，ID: {session_id}")
            
            # 测试输入
            print("\n测试输入: congmingdeRime shurufa")
            if wrapper.simulate_key_sequence(session_id, "congmingdeRime shurufa"):
                print("✓ 输入成功")
                
                # 获取上下文
                context = wrapper.get_context(session_id)
                if context:
                    print(f"输入文本: {context.get('input', '')}")
                    candidates = context.get('candidates', [])
                    if candidates:
                        print("候选词:")
                        for i, cand in enumerate(candidates):
                            print(f"  {i+1}. {cand.get('text', '')}")
                    else:
                        print("（需要完整实现才能获取候选词）")
                else:
                    print("（无法获取上下文，可能需要完整实现）")
            else:
                print("✗ 输入失败")
            
            # 清理
            wrapper.destroy_session(session_id)
        else:
            print("✗ 会话创建失败")
            print("注意: DLL 包装器需要完整的 API 定义才能正常工作")
            print("建议使用 RimeConsoleWrapper 进行测试")
        
        wrapper.finalize()
    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()


def interactive_mode():
    """交互式模式：直接调用 rime_api_console.exe"""
    print("=" * 60)
    print("Rime 交互式模式")
    print("=" * 60)
    print("提示：")
    print("  - 输入拼音或命令（例如：congmingdeRime shurufa）")
    print("  - 输入 'exit' 退出")
    print("  - 输入 'reload' 重新加载")
    print("  - 输入 'print schema list' 查看方案列表")
    print("  - 输入 'select schema <schema_id>' 切换方案")
    print("=" * 60)
    
    # 查找 rime_api_console.exe
    project_root = Path(__file__).parent.parent.parent
    console_path = project_root / "librime" / "build" / "bin" / "Release" / "rime_api_console.exe"
    
    if not console_path.exists():
        console_path = project_root / "librime" / "build" / "bin" / "rime_api_console.exe"
    
    if not console_path.exists():
        print(f"\n错误: 找不到 rime_api_console.exe")
        print(f"请确保已构建 librime")
        print(f"\n尝试的路径：")
        print(f"  - {project_root / 'librime' / 'build' / 'bin' / 'Release' / 'rime_api_console.exe'}")
        print(f"  - {project_root / 'librime' / 'build' / 'bin' / 'rime_api_console.exe'}")
        print(f"\n构建方法：")
        print(f"  cd librime")
        print(f"  mkdir build && cd build")
        print(f"  cmake ..")
        print(f"  cmake --build . --config Release")
        return
    
    work_dir = console_path.parent
    
    print(f"\n启动: {console_path}")
    print(f"工作目录: {work_dir}\n")
    
    # 直接启动交互式进程
    try:
        subprocess.run([str(console_path)], cwd=str(work_dir))
    except KeyboardInterrupt:
        print("\n\n已退出")
    except Exception as e:
        print(f"错误: {e}")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='调用 librime')
    parser.add_argument('--mode', type=str, choices=['console', 'dll', 'interactive', 'test'],
                       default='interactive',
                       help='运行模式: console(控制台包装器), dll(DLL包装器), interactive(交互式), test(测试)')
    parser.add_argument('--console-exe', type=str, default=None,
                       help='rime_api_console.exe 的路径')
    parser.add_argument('--dll', type=str, default=None,
                       help='rime.dll 的路径')
    parser.add_argument('--input', type=str, default=None,
                       help='要输入的文本（仅在 console 模式下使用）')
    
    args = parser.parse_args()
    
    if args.mode == 'interactive':
        interactive_mode()
    elif args.mode == 'console':
        wrapper = RimeConsoleWrapper(args.console_exe)
        if wrapper.start():
            if args.input:
                result = wrapper.simulate_key_sequence(args.input)
                print(result)
            else:
                print("使用 --input 参数指定要输入的文本")
            wrapper.stop()
    elif args.mode == 'dll':
        test_dll_wrapper()
    elif args.mode == 'test':
        test_console_wrapper()
        print("\n")
        test_dll_wrapper()

