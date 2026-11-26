#!/usr/bin/env python3
"""按模块读取缓存 RTL，保留拆分前后的完整定义及源文件散列。"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
import runpy


def source_files(root: Path, relative: Path):
    root = Path(root).resolve()
    resolver = runpy.run_path(str(root / 'scripts/rtl/source_files.py'))
    selected = resolver['with_dependencies']([root / relative], root)
    # 局部验证还覆盖原文件中独立定义的组合函数。
    selected += sorted((root / 'rtl/npu/dma/cache').glob('conv_cache_*.sv'))
    return list(dict.fromkeys(selected))


def read_sources(root: Path, relative: Path):
    return '\n'.join(path.read_text() for path in source_files(root, relative))


def source_manifest(root: Path, relative: Path):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in source_files(root, relative)}


def module_definition(source: str, name: str):
    expression = re.compile(r'(?m)^(?:\(\*[^\n]*\*\)\s*)?module\s+' + re.escape(name) + r'\b')
    definitions = []
    for match in expression.finditer(source):
        end = source.index('endmodule', match.end()) + len('endmodule')
        definitions.append(source[match.start():end])
    if not definitions:
        raise ValueError('未找到模块定义：' + name)
    if any(text != definitions[0] for text in definitions[1:]):
        raise ValueError('同名模块包含不同定义：' + name)
    return definitions[0]


def request_module(source: str):
    if re.search(r'\bmodule\s+conv_cache_request_path\b', source):
        return module_definition(source, 'conv_cache_request_path')
    return module_definition(source, 'conv_windowed_cache')


def controller_module(source: str):
    return module_definition(source, 'conv_windowed_cache')
