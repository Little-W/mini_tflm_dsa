"""读取指定版本的 RTL，并统一公共模块名称。"""
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


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
    return content.decode() if text else content
