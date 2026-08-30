from pathlib import Path

from pypinyin import Style, pinyin


def _convert_line(line: str) -> str:
    if not line:
        return ""

    result = pinyin(
        line,
        style=Style.TONE,
        heteronym=False,
        errors="default",
    )
    return " ".join(item[0] for item in result if item and item[0])


def convert_text(text: str) -> str:
    """多行文本 -> 带声调、空格分隔拼音；保留原换行。"""
    if not text:
        return ""

    return "\n".join(_convert_line(line) for line in text.split("\n"))


def convert_file(input_path: str, output_path: str) -> str:
    """读取 UTF-8 文本文件，转换后写入 UTF-8 输出文件。"""
    src = Path(str(input_path).strip()).expanduser()
    dst = Path(str(output_path).strip()).expanduser()

    if not str(src):
        raise ValueError("输入文件路径为空")
    if not str(dst):
        raise ValueError("输出文件路径为空")
    if not src.is_file():
        raise FileNotFoundError(f"输入文件不存在：{src}")

    source = src.read_text(encoding="utf-8")
    converted = convert_text(source)

    if dst.parent != Path("."):
        dst.parent.mkdir(parents=True, exist_ok=True)

    dst.write_text(converted, encoding="utf-8")

    line_count = source.count("\n") + (1 if source else 0)
    return f"转换完成：{line_count} 行 → {dst}"
