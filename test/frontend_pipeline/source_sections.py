"""读取前端各职责模块，并将端口名转换为数学验证使用的局部变量名。"""
from pathlib import Path
import re
import runpy


def without_comments(text):
    """移除注释后分析声明，端口功能说明保留在原始 RTL 中。"""
    return re.sub(r'/\*[\s\S]*?\*/|//[^\n]*', '', text)


def read_module(root, part):
    directory = Path(root).resolve()/'rtl/npu/conv'
    path = directory/(part+'.sv' if part.startswith('conv_') else f'conv_im2col_{part}.sv')
    if not path.is_file():
        if part.startswith('conv_'):
            raise FileNotFoundError(path)
        path = directory/'conv_im2col_frontend.sv'
    text = path.read_text()
    if path.name == 'conv_im2col_frontend.sv':
        return path, text
    header = without_comments(text[:text.index('\n);')+3])
    aliases = {}
    for line in header.splitlines():
        declaration = line.strip().rstrip(',')
        if not declaration.startswith(('input ', 'output ')):
            continue
        names = re.findall(r'\b([io]_[A-Za-z_]\w*)\b',declaration)
        for name in names:
            aliases[name] = name[2:]
    for name in ('size', 'slot_w', 'lanes', 'line_bytes', 'bus_width', 'narrow_lanes',
                 'register_cache_request', 'register_descriptor', 'register_row_address',
                 'preview_registered',
                 'rw', 'tile_count_w', 'chunk_count_w', 'coord_w', 'prepared_tile_width'):
        aliases['p_'+name] = name.upper()
    for name, local in sorted(aliases.items(), key=lambda pair: -len(pair[0])):
        text = re.sub(r'(?<![\w.$])'+re.escape(name)+r'\b', local, text)
    return path, text


def declarations(text, names):
    """提取指定内部信号的完整声明，保留实际位宽和符号属性。"""
    result = []
    for name in names:
        match = re.search(r'^\s*(?:\(\*[^\n]*\*\)\s*)?(?:logic|wire|reg)\s+'
                          r'[^;\n]*\b'+re.escape(name)+r'\b[^;\n]*;', text, re.M)
        if match is None:
            raise ValueError('找不到信号声明：'+name)
        if match[0] not in result:
            result.append(match[0])
    return '\n'.join(result)+'\n'


def dependencies(root, sources):
    """将真实模块及生成模型的实例依赖统一展开为可编译源文件列表。"""
    repository=Path(__file__).resolve().parents[2]
    resolve=runpy.run_path(str(repository/'scripts/rtl/source_files.py'))['with_dependencies']
    return resolve([Path(path).resolve() for path in sources],Path(root).resolve())
