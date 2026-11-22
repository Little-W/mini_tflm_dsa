"""读取前端各职责模块，并将端口名转换为数学验证使用的局部变量名。"""
from pathlib import Path
import re


def read_module(root, part):
    directory = Path(root).resolve()/'rtl/npu/conv'
    path = directory/f'conv_im2col_{part}.sv'
    if not path.is_file():
        path = directory/'conv_im2col_frontend.sv'
    text = path.read_text()
    if path.name == 'conv_im2col_frontend.sv':
        return path, text
    header = text[:text.index('\n);')+3]
    aliases = {}
    for line in header.splitlines():
        declaration = line.strip().rstrip(',')
        if not declaration.startswith(('input ', 'output ')):
            continue
        name = re.sub(r'\s*(?:\[[^\]]+\]\s*)+$', '', declaration).split()[-1]
        if name.startswith(('i_', 'o_')):
            aliases[name] = name[2:]
    for name in ('size', 'slot_w', 'lanes', 'line_bytes', 'bus_width', 'narrow_lanes',
                 'register_cache_request', 'register_descriptor', 'register_row_address',
                 'rw', 'tile_count_w', 'chunk_count_w', 'coord_w', 'prepared_tile_width'):
        aliases['p_'+name] = name.upper()
    for name, local in sorted(aliases.items(), key=lambda pair: -len(pair[0])):
        text = re.sub(r'(?<![\w.$])'+re.escape(name)+r'\b', local, text)
    return path, text


def declarations(text, names):
    """提取指定内部信号的完整声明，保留实际位宽和符号属性。"""
    result = []
    for name in names:
        match = re.search(r'^  (?:\(\*[^\n]*\*\)\s*)?(?:logic|wire|reg)\s+'
                          r'[^;\n]*\b'+re.escape(name)+r'\b[^;\n]*;', text, re.M)
        if match is None:
            raise ValueError('找不到信号声明：'+name)
        if match[0] not in result:
            result.append(match[0])
    return '\n'.join(result)+'\n'
