import os
import sys
import gc
import json
import shutil  # 用于安全移动文件
from datetime import datetime  # 用于获取当前时间
from pathlib import Path
from pypinyin import lazy_pinyin, Style

# ================= 工业级配置区 =================
INPUT_DIR = r"..\data\corpus"
OUTPUT_BASE_DIR = r"..\xxx"
MAX_FILE_SIZE_BYTES = 30 * 1024 * 1024
TARGET_VENDOR_KEY = "rime_wanxiang_with_gram"
STATE_FILE = "resume_state.json"  # 断点进度文件
SAVE_INTERVAL = 1000              # 每处理多少行保存一次进度
# ================================================

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from rime_schema_compare.rime_runner import RimeDistroRunner
from rime_schema_compare.config import DEFAULT_VENDORS, resolve_rime_dll

class RotatingFileWrapper:
    """自动轮转分卷的文件写入器"""
    def __init__(self, base_dir, base_name, max_bytes):
        self.base_dir = Path(base_dir)
        self.base_name = base_name
        self.max_bytes = max_bytes
        self.counter = 1
        self.file_obj = None
        self.current_size = 0
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._open_next_file()

    def _open_next_file(self):
        if self.file_obj:
            self.file_obj.close()
        while True:
            file_path = self.base_dir / f"{self.base_name}_{self.counter}.txt"
            if not file_path.exists() or file_path.stat().st_size < self.max_bytes:
                break
            self.counter += 1
        self.file_path = self.base_dir / f"{self.base_name}_{self.counter}.txt"
        self.file_obj = open(self.file_path, 'a', encoding='utf-8')
        self.current_size = self.file_path.stat().st_size if self.file_path.exists() else 0
        print(f"\n📄 [文件分卷] 接入产物: {self.file_path.name} (当前: {self.current_size / 1024 / 1024:.2f} MB)")

    def write_and_flush(self, text: str):
        encoded = text.encode('utf-8')
        size_to_add = len(encoded)
        if self.current_size + size_to_add > self.max_bytes:
            self.counter += 1
            self._open_next_file()
        self.file_obj.write(text)
        self.file_obj.flush()
        self.current_size += size_to_add

    def close(self):
        if self.file_obj:
            self.file_obj.close()


def safe_decode_via_escape(runner, pinyin: str) -> str:
    """利用原生 Escape 键清空输入框，安全且极速"""
    sid = runner._batch_session_id
    if not sid:
        return ""
    
    runner._rime.simulate_key_sequence(sid, pinyin)
    ctx = runner._rime.get_context(sid)
    res = ""
    if ctx and isinstance(ctx, dict) and ctx.get("candidates"):
        res = ctx["candidates"][0]["text"]
        
    runner._rime.simulate_key_sequence(sid, "{Escape}{Escape}")
    return res


# ================= 断点存档系统 (单文件独立版) =================
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                state = json.load(f)
                print(f"📦 读取到断点: 将从文件 [{state.get('file_name', '无')}] 第 {state.get('line_idx', 0)} 行恢复。")
                return state
        except Exception as e:
            print(f"⚠️ 进度文件读取失败，将重新开始: {e}")
    return {"file_name": "", "line_idx": 0, "file_extracted": 0}

def save_state(file_name, line_idx, file_extracted):
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump({
                "file_name": file_name,
                "line_idx": line_idx,
                "file_extracted": file_extracted
            }, f)
    except Exception as e:
        print(f"⚠️ 保存进度失败: {e}")
# ========================================================


def main():
    print("🚀 正在初始化 Rime 引擎 (Windows 键盘模拟防爆版)...")
    
    try:
        dll_path = resolve_rime_dll()
    except Exception as e:
        print(f"❌ 找不到 rime.dll: {e}")
        return

    vendor_conf = next((v for v in DEFAULT_VENDORS if v.key == TARGET_VENDOR_KEY), None)
    if not vendor_conf:
        return

    runner = RimeDistroRunner(dll_path)
    runner.switch_distro(vendor_conf)
    
    runner.begin_decode_batch()
    print(f"✅ 方案加载完毕: {vendor_conf.schema_id}")

    input_dir_path = Path(INPUT_DIR)
    completed_dir = input_dir_path.parent / "完成"
    completed_dir.mkdir(parents=True, exist_ok=True)
    
    txt_files = list(input_dir_path.glob("**/*.txt"))
    if not txt_files:
        return
        
    print(f"📂 扫描到 {len(txt_files)} 个语料文件，引擎全速启动...\n")

    # 启动时加载进度
    state = load_state()
    resume_file = state.get("file_name", "")
    resume_line = state.get("line_idx", 0)
    resume_extracted = state.get("file_extracted", 0)
    
    writer = None  
    
    global_processed_this_run = 0
    global_extracted_this_run = 0
    
    # 增加寻址标志位
    seeking_resume = bool(resume_file) 
    
    try:
        # 给文件列表排个序，防止乱序
        txt_files = sorted(txt_files) 
        
        for file_path in txt_files:
            file_name = file_path.name
            file_stem = file_path.stem 
            
            # 寻址快进逻辑
            if seeking_resume:
                if file_name != resume_file:
                    print(f"⏭️ 寻址快进... 跳过文件: {file_name}")
                    continue
                else:
                    seeking_resume = False # 找到了！解除快进状态
            
            # 为每个文件重置独立的计数器
            file_processed = 0
            file_extracted = 0
            current_resume_line = 0  # 🌟 修复点：确保这个变量在任何情况下都已定义！
            
            # 预先扫描行数
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f_count:
                    file_total_lines = sum(1 for _ in f_count)
            except Exception as e:
                print(f"⚠️ 获取文件 {file_name} 行数失败: {e}")
                continue

            # 继承断点数据
            if file_name == resume_file:
                current_resume_line = resume_line
                file_processed = resume_line           # 已经跳过的行就算作已处理
                file_extracted = resume_extracted      # 继承提取出的数量
                
                # 继承完毕后清空记录，防止影响下一个文件
                resume_file = "" 
                resume_line = 0
                resume_extracted = 0
                
            print(f"📖 开始流式吞吐: {file_name}" + (f" (从第 {current_resume_line} 行开始)" if current_resume_line > 0 else ""))
            
            if writer:
                writer.close()
            writer = RotatingFileWrapper(OUTPUT_BASE_DIR, file_stem, MAX_FILE_SIZE_BYTES)
            
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    for current_line_idx, raw_line in enumerate(f):
                        # 快进
                        if current_line_idx < current_resume_line:
                            continue
                            
                        raw_line = raw_line.strip()
                        if not raw_line: continue
                        
                        parts = raw_line.split('\t')
                        target_text = parts[0].strip()
                        
                        if not target_text: continue
                        
                        # 计数器更新
                        file_processed += 1
                        global_processed_this_run += 1
                        
                        pinyin = "".join(lazy_pinyin(target_text, style=Style.NORMAL))
                        output = safe_decode_via_escape(runner, pinyin)
                        
                        if output != target_text:
                            writer.write_and_flush(f"{raw_line}\n")
                            file_extracted += 1
                            global_extracted_this_run += 1
                            
                        # 打印当前文件的进度
                        if file_processed % 10000 == 0:
                            ratio = (file_extracted / file_processed) * 100 if file_processed > 0 else 0
                            current_time = datetime.now().strftime("%H:%M:%S")
                            print(f"  ⚡ [{current_time}]: {file_name} | 进度 {file_processed}/{file_total_lines} 行 | 本文件打不出 {file_extracted} 行 | 剔除率 {ratio:.2f}%")
                            gc.collect()
                            
                        # 保存单文件断点
                        if current_line_idx % SAVE_INTERVAL == 0:
                            save_state(file_name, current_line_idx, file_extracted)
                                        
            except Exception as e:
                print(f"⚠️ 读取/处理 {file_name} 时发生错误: {e}")
                continue
            finally:
                if writer:
                    writer.close()
                    writer = None

            # 移动完成的文件
            target_path = completed_dir / file_name
            shutil.move(str(file_path), str(target_path))
            print(f"  🚚 [{datetime.now().strftime('%H:%M:%S')}] 已完成处理并移动至: {completed_dir.name}/{file_name}")
            
            # 切换文件时，清空当前进度
            save_state("", 0, 0)

    except KeyboardInterrupt:
        print(f"\n🛑 [{datetime.now().strftime('%H:%M:%S')}] 收到手动停止指令 (Ctrl+C)！正在保存断点并安全退出...")
        
    finally:
        if writer:
            writer.close()
        runner.close()
        
        # 打印本次运行的总结数据
        final_ratio = (global_extracted_this_run / global_processed_this_run) * 100 if global_processed_this_run > 0 else 0
        print(f"\n🎉 本次执行结束！累计处理 {global_processed_this_run} 行，提取打不出的语料 {global_extracted_this_run} 行，总占比 {final_ratio:.2f}%。")
        
        remaining_files = list(Path(INPUT_DIR).glob("**/*.txt"))
        if not remaining_files and os.path.exists(STATE_FILE):
            os.remove(STATE_FILE)
            print("✨ 所有文件已全部处理完毕，已清理断点记录文件。")

if __name__ == "__main__":
    main()
