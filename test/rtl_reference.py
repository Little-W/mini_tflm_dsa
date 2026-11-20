"""读取指定版本的 RTL，并统一公共模块名称及可选端口。"""
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def optional_shared_write_port(content, path, cwd):
    """让默认关闭的共享写数据接口参与不同版本的完整端口比较。"""
    interfaces = {
        'rtl/npu/loaders/ia_loader.sv': ('ia_loader', 'ram_shared_wr_data', 'output'),
        'rtl/npu/loaders/ia_loader_cache_mgr.sv': ('ia_loader_cache_mgr', 'ram_shared_wr_data', 'output'),
        'rtl/npu/buffers/ia_ps_shared_ram.sv': ('ia_ps_channel_ram', 'i_ia_shared_write_data', 'input'),
    }
    if path not in interfaces:
        return content
    module_name, port, direction = interfaces[path]
    port_bytes = port.encode()
    current = Path(cwd) / path
    if not current.exists() or port_bytes not in current.read_bytes() or port_bytes in content:
        return content
    module = re.search(rb'\bmodule\s+' + module_name.encode() + rb'\b', content)
    if module is None:
        raise ValueError('找不到共享写数据接口对应的模块')
    end = re.search(rb'\)\s*;', content[module.end():])
    if end is None:
        raise ValueError('找不到模块端口列表的结束位置')
    start = module.end() + end.start()
    stop = module.end() + end.end()
    prefix = content[:start].rstrip()
    if not prefix.endswith(b','):
        prefix += b','
    declaration = f'\n    {direction} wire [127:0] {port}'
    if direction == 'input':
        declaration += " = 128'd0"
    body = prefix + declaration.encode() + b'\n' + content[start:stop]
    if direction == 'output':
        body += f"\nassign {port} = 128'd0;\n".encode()
    return body + content[stop:]


def read_rtl_source(revision_path, *, cwd=ROOT, text=False):
    revision, separator, path = str(revision_path).partition(':')
    if not separator or not revision or not path:
        raise ValueError('需要提供版本号和仓库内路径')
    result = subprocess.run(['git', 'show', str(revision_path)], cwd=cwd,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode and path == 'rtl/common/regfile.v':
        result = subprocess.run(['git', 'show', f'{revision}:rtl/common/REGFILE.v'], cwd=cwd,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    result.check_returncode()
    content = result.stdout
    if Path(path).suffix in ('.v', '.sv', '.svh', '.vh'):
        content = re.sub(rb'\bREGFILE\b', b'regfile', content)
        content = optional_shared_write_port(content, path, cwd)
    return content.decode() if text else content
