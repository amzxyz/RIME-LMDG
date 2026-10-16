"""Exact dictionary processing used by the desktop Wanxiang tool.

This intentionally keeps the desktop auxiliary-code alignment rules instead of
assigning codes by a naïve character index. A failed alignment leaves a line
untouched, which prevents silently putting another character's code on a word.
"""
from __future__ import annotations
import re
from typing import Dict, List, Optional, Tuple

AUX_SEP_REGEX = r'[;\[]'
YAML_HEADS = ('---', 'name:', 'version:', 'sort:', '...')
LITE_TONE_MAP = str.maketrans({
    'ā':'a','á':'a','ǎ':'a','à':'a','ē':'e','é':'e','ě':'e','è':'e',
    'ī':'i','í':'i','ǐ':'i','ì':'i','ō':'o','ó':'o','ǒ':'o','ò':'o',
    'ū':'u','ú':'u','ǔ':'u','ù':'u','ǖ':'v','ǘ':'v','ǚ':'v','ǜ':'v','ü':'v',
    'ḿ':'me','ń':'en','ň':'en','ǹ':'en',
})
AUX_CJK_PATTERN = re.compile(r'[〇\u2E80-\u2EFF\u2F00-\u2FDF\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF\U00020000-\U0003347F]')
NON_HAN_TO_HAN = {'0':'零','1':'一','2':'二','3':'三','4':'四','5':'五','6':'六','7':'七','8':'八','9':'九'}


def _is_cjk(ch): return bool(ch and AUX_CJK_PATTERN.fullmatch(ch))
def _visible(word): return [ch for ch in word if not ch.isspace()]
def _han(word): return [ch for ch in word if _is_cjk(ch)]

def _aux_for_char(ch, aux_map, ignore_non_chinese=True):
    if _is_cjk(ch): return aux_map.get(ch, '')
    if ignore_non_chinese: return ''
    if ch in aux_map: return aux_map.get(ch, '')
    mapped = NON_HAN_TO_HAN.get(ch)
    return aux_map.get(mapped, '') if mapped else ''

def _tokenize(word):
    units, buf = [], []
    for ch in word:
        if ch.isspace(): continue
        if _is_cjk(ch):
            if buf: units.append({'type':'non_han','text':''.join(buf)}); buf=[]
            units.append({'type':'han','text':ch})
        else: buf.append(ch)
    if buf: units.append({'type':'non_han','text':''.join(buf)})
    return units

def _align(units, roots, ui, si, aux_map, ignore_non_chinese=True):
    if ui == len(units) and si == len(roots): return []
    if ui == len(units) or si == len(roots): return None
    unit = units[ui]
    if unit['type'] == 'han':
        rest = _align(units, roots, ui + 1, si + 1, aux_map, ignore_non_chinese)
        return None if rest is None else [aux_map.get(unit['text'], '')] + rest
    text = unit['text'].lower(); current = ''
    for k in range(si, len(roots)):
        current += roots[k].lower()
        if current == text:
            rest = _align(units, roots, ui + 1, k + 1, aux_map, ignore_non_chinese)
            if rest is not None:
                return [_aux_for_char(unit['text'], aux_map, ignore_non_chinese)] + [''] * (k - si) + rest
    remaining_han = sum(1 for u in units[ui + 1:] if u['type'] == 'han')
    max_consume = len(roots) - si - remaining_han
    for consume in range(max_consume, 0, -1):
        rest = _align(units, roots, ui + 1, si + consume, aux_map, ignore_non_chinese)
        if rest is not None:
            return [_aux_for_char(unit['text'], aux_map, ignore_non_chinese)] + [''] * (consume - 1) + rest
    return None

def _aligned(word, raw_segs, aux_map, ignore_non_chinese=True):
    if not raw_segs: return []
    roots = [re.split(AUX_SEP_REGEX, seg, maxsplit=1)[0] for seg in raw_segs]
    visible, han = _visible(word), _han(word)
    if len(roots) == len(visible): return [_aux_for_char(ch, aux_map, ignore_non_chinese) for ch in visible]
    if len(roots) == len(han): return [aux_map.get(ch, '') for ch in han]
    result = _align(_tokenize(word), roots, 0, 0, aux_map, ignore_non_chinese)
    return result if result is not None and len(result) == len(raw_segs) else None

def _refresh(cols, word, aux_map, userdb=False, ignore_non_chinese=True):
    before = '\t'.join(cols)
    if not userdb and len(cols) == 1: cols.insert(1, '')
    if userdb and len(cols) < 2: cols.append('')
    idx = 0 if userdb else 1
    if not userdb and idx < len(cols) and len(cols) == 2 and cols[idx].strip().isdigit(): return cols, False
    raw = cols[idx].strip().split() if idx < len(cols) else []
    aux = _aligned(word, raw, aux_map, ignore_non_chinese)
    if aux is None: return cols, False
    merged = [f"{re.split(AUX_SEP_REGEX, seg, maxsplit=1)[0]};{aux[i] if i < len(aux) else ''}" for i, seg in enumerate(raw)]
    if userdb:
        cols[0] = ' '.join(merged)
        if not cols[0].endswith(' '): cols[0] += ' '
    else: cols[idx] = ' '.join(merged)
    return cols, ('\t'.join(cols) != before)

def parse_aux_metadata_text(text: str) -> Dict[str, str]:
    result = {}
    for line in text.splitlines():
        if not line.strip() or line.startswith('#'): continue
        parts = line.split('\t')
        if len(parts) < 2 or len(parts[0]) != 1: continue
        pieces = re.split(AUX_SEP_REGEX, parts[1], maxsplit=1)
        result[parts[0]] = (pieces[1].strip() if len(pieces) > 1 else parts[1].strip())
        if result[parts[0]] == ';': result[parts[0]] = ''
    return result

def strip_lite_tones(text: str) -> str:
    return text.replace('m̀', 'me').translate(LITE_TONE_MAP)

def _rewrite_name(line, name):
    return f'name: {name}' if line.lstrip().startswith('name:') else line

def process_extra_file(src: str, dst: str, scheme_type: str, aux_text: str = '') -> str:
    original = src.rsplit('/', 1)[-1]
    base = original[:-len('.dict.yaml')] if original.lower().endswith('.dict.yaml') else original
    suffix = '.lite' if scheme_type == 'lite' else ('.pro' if scheme_type == 'pro' else '')
    output_name = base + suffix + '.dict.yaml'
    aux_map = parse_aux_metadata_text(aux_text) if scheme_type == 'pro' else {}
    userdb = False; changed = 0; total = 0
    with open(src, encoding='utf-8') as source, open(dst, 'w', encoding='utf-8') as out:
        for raw in source:
            total += 1
            line = raw.rstrip('\n')
            if line.startswith(YAML_HEADS) or line.startswith('#'):
                if '#@/db_type\tuserdb' in line or '# Rime user dictionary' in line: userdb = True
                out.write(_rewrite_name(line, base + suffix) + '\n'); continue
            if not line.strip(): out.write('\n'); continue
            cols = line.split('\t')
            if scheme_type == 'pro':
                word = cols[1] if userdb and len(cols) > 1 else cols[0]
                new_cols, did = _refresh(cols, word, aux_map, userdb, True)
            elif scheme_type == 'lite':
                new_cols, did = cols, False
                if len(cols) >= 2:
                    new_cols = list(cols); new_cols[1] = ' '.join(strip_lite_tones(x) for x in cols[1].split())
                    did = new_cols != cols
            else: new_cols, did = cols, False
            changed += int(did); out.write('\t'.join(new_cols) + '\n')
    return f"{output_name}|{total}|{changed}"
