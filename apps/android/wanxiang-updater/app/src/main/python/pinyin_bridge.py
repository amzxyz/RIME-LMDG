from pypinyin import pinyin, Style


def convert_text(text: str) -> str:
    """多行汉字 -> 带声调、空格分隔拼音；保留原换行。"""
    if not text:
        return ""

    output_lines = []
    for line in text.split("\n"):
        if not line:
            output_lines.append("")
            continue

        result = pinyin(
            line,
            style=Style.TONE,
            heteronym=False,
            errors="default",
        )
        output_lines.append(" ".join(item[0] for item in result if item and item[0]))

    return "\n".join(output_lines)
