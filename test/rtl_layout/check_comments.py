#!/usr/bin/env python3
"""解析模块端口，检查每个端口后的中文功能注释与模块头注释。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

from pyslang import syntax

ROOT = Path(__file__).resolve().parents[2]
COMMENT = re.compile(r'//[^\n]*|/\*[\s\S]*?\*/')
CHINESE = re.compile(r'[\u4e00-\u9fff]')
PROFILES = (('generic', ''), ('synthesis', '`define SYNTHESIS\n'),
            ('riscv_formal', '`define RISCV_FORMAL\n'),
            ('simulation_assertions', '`define NPU_SIM_ASSERT\n'),
            ('synthesis_assertions', '`define SYNTHESIS\n`define NPU_SIM_ASSERT\n'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    modules, ports, hashes = {}, {}, {}
    missing_headers, missing_ports = set(), set()
    for path in sorted((ROOT/'rtl').rglob('*')):
        if path.suffix not in ('.sv', '.v') or 'GV' in path.parts:
            continue
        relative = str(path.relative_to(ROOT))
        original = path.read_text()
        hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        for _, definitions in PROFILES:
            text = definitions+original
            data = text.encode()
            tree = syntax.SyntaxTree.fromText(text)
            root = tree.root
            members = root.members if type(root).__name__ == 'CompilationUnitSyntax' else [root]
            for module in members:
                if type(module).__name__ != 'ModuleDeclarationSyntax':
                    continue
                modules[relative] = module.header.name.rawText
                port_list = module.header.ports
                if port_list is None:
                    continue
                if type(port_list).__name__ != 'AnsiPortListSyntax':
                    raise RuntimeError('端口列表需要 ANSI 声明：'+relative)
                header = data[:port_list.openParen.location.offset].decode()
                if not any(CHINESE.search(comment) for comment in COMMENT.findall(header)):
                    missing_headers.add(relative)
                declarations = [node for node in port_list.ports if hasattr(node, 'declarator')]
                for index, declaration in enumerate(declarations):
                    token = declaration.declarator.name
                    start = token.location.offset+len(token.rawText.encode())
                    end = declarations[index+1].getFirstToken().location.offset if index+1<len(declarations) else port_list.closeParen.location.offset
                    comments = COMMENT.findall(data[start:end].decode())
                    key = (relative, token.rawText)
                    ports[key] = True
                    if not any(CHINESE.search(comment) for comment in comments):
                        missing_ports.add(key)
    result = {'passed': not (missing_headers or missing_ports), 'modules': len(modules),
              'ports': len(ports), 'profiles': [name for name, _ in PROFILES],
              'missing_module_headers': sorted(missing_headers),
              'missing_port_comments': [{'path': path, 'port': port} for path, port in sorted(missing_ports)],
              'source_sha256': hashes}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out/'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({key: value for key, value in result.items() if key != 'source_sha256'}, ensure_ascii=False))
    if not result['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
