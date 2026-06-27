import os
import sys
import gc
import shutil  # [新增] 用于安全移动文件
from pathlib import Path
from pypinyin import lazy_pinyin, Style

# ================= 工业级配置区 =================
INPUT_DIR = r"..\data\corpus"
OUTPUT_BASE_DIR = r"..\xxx"
OUTPUT_BASE_NAME = "model_evolution_data"
MAX_FILE_SIZE_BYTES = 30 * 1024 * 1024
TARGET_VENDOR_KEY = "rime_wanxiang_with_gram"
# ================================================

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from rime_schema_compare.rime_runner import RimeDistroRunner
from rime_schema_compare.config import DEFAULT_VENDORS, resolve_rime_dll
from rime_schema_compare.text_pipeline_evo import process_corpus_to_lines, extract_missed_segments

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
    
    # 1. 敲拼音
    runner._rime.simulate_key_sequence(sid, pinyin)
    
    # 2. 提取首选词
    ctx = runner._rime.get_context(sid)
    res = ""
    if ctx and isinstance(ctx, dict) and ctx.get("candidates"):
        res = ctx["candidates"][0]["text"]
        
    # 3. 灵魂操作：模拟连按两次 Esc 键，强制清空输入栏（不上屏，不写数据库！）
    runner._rime.simulate_key_sequence(sid, "{Escape}{Escape}")
    
    return res


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
    # 只在最开始部署这一次！！绝不再碰它！
    runner.switch_distro(vendor_conf)
    
    # 开启唯一长会话
    runner.begin_decode_batch()
    print(f"✅ 方案加载完毕: {vendor_conf.schema_id}")

    input_dir_path = Path(INPUT_DIR)
    
    # [新增] 定义上一层“完成”目录并确保其存在
    completed_dir = input_dir_path.parent / "完成"
    completed_dir.mkdir(parents=True, exist_ok=True)
    
    txt_files = list(input_dir_path.glob("**/*.txt"))
    if not txt_files:
        return
        
    print(f"📂 扫描到 {len(txt_files)} 个语料文件，引擎全速启动...\n")

    writer = RotatingFileWrapper(OUTPUT_BASE_DIR, OUTPUT_BASE_NAME, MAX_FILE_SIZE_BYTES)
    total_extracted = 0
    
    for file_path in txt_files:
        print(f"📖 开始流式吞吐: {file_path.name}")
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                for raw_line in f:
                    raw_line = raw_line.strip()
                    if not raw_line: continue
                    
                    valid_segments = process_corpus_to_lines(raw_line)
                    for segment in valid_segments:
                        pinyin = "".join(lazy_pinyin(segment, style=Style.NORMAL))
                        
                        # 核心：使用单会话 + Esc清空法
                        output = safe_decode_via_escape(runner, pinyin)
                        
                        if output != segment:
                            missed_parts = extract_missed_segments(segment, output)
                            for part in missed_parts:
                                writer.write_and_flush(f"{part}\n")
                                total_extracted += 1
                                
                                if total_extracted % 2000 == 0:
                                    print(f"  ⚡ 引擎狂飙中... 已累计提取 {total_extracted} 个高质量弱项")
                                    # 顺手回收一下 Python 内存
                                    gc.collect()
            
            # [新增] with open 块结束后（文件已关闭），安全移动文件
            target_path = completed_dir / file_path.name
            shutil.move(str(file_path), str(target_path))
            print(f"  🚚 已完成处理并移动至: {completed_dir.name}/{file_path.name}")
                                    
        except Exception as e:
            print(f"⚠️ 读取/处理 {file_path.name} 时发生错误: {e}")
            continue

    writer.close()
    runner.close()
    print(f"\n🎉 批量大语料处理完毕！本次共提取 {total_extracted} 条精华语料。")

if __name__ == "__main__":
    main()
