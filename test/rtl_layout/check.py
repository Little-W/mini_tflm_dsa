#!/usr/bin/env python3
"""检查独立模块文件、普通算术接口和生产源文件依赖。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--max-module-lines', type=int, default=1500)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    definitions = {}
    packages = {}
    hashes = {}
    source_lines = {}
    for path in sorted((ROOT / 'rtl').rglob('*')):
        if path.suffix not in ('.v', '.sv') or 'GV' in path.relative_to(ROOT / 'rtl').parts:
            continue
        text = path.read_text()
        code = re.sub(r'//[^\n]*|/\*.*?\*/', ' ', text, flags=re.S)
        modules = re.findall(r'\bmodule\s+(\w+)\b', code)
        package_names = re.findall(r'\bpackage\s+(\w+)\b', code)
        if len(modules) + len(package_names) != 1:
            raise RuntimeError(f'Expected one module or package: {path}')
        if re.search(r'\b(?:use_dsp|p_use_dsp|p_use_lut|p_infer_dsp|p_\w*dsp\w*)\b', text):
            raise RuntimeError(f'Resource-selection flag: {path}')
        if re.search(r'\b(?:LUT[1-6](?:_2)?|RAMB(?:18|36)E[12]|DSP48E[12]|URAM288(?:_BASE)?)\s*(?:#\s*\(|\w+\s*\()', code):
            raise RuntimeError(f'Explicit FPGA primitive: {path}')
        relative = str(path.relative_to(ROOT))
        hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        source_lines[relative] = len(text.splitlines())
        if relative.startswith('rtl/npu/') and source_lines[relative] >= args.max_module_lines:
            raise RuntimeError(f'NPU source exceeds preferred length: {path}: {source_lines[relative]}')
        for name, target in ((modules, definitions), (package_names, packages)):
            if name:
                if name[0] in target:
                    raise RuntimeError(f'Duplicate definition: {name[0]}')
                if path.stem != name[0] and (path.name, name[0]) != ('picorv32_npu.v', 'picorv32'):
                    raise RuntimeError(f'Module and filename differ: {path}')
                target[name[0]] = relative
    obsolete = {'vec_requant_full', 'vec_requant_tensor_ws', 'vec_requant_s64',
                'requant_registered_sum', 'requant_activation_compare'}
    if obsolete & definitions.keys():
        raise RuntimeError('Unexpected quantization wrapper')
    resolver = runpy.run_path(str(ROOT / 'scripts/rtl/source_files.py'))['with_dependencies']
    filelists = []
    for name in ('asic/synthesis/filelists/npu_top.f', 'veri/flist/dut_axil.f'):
        path = ROOT / name
        entries = []
        for line in path.read_text().splitlines():
            match = re.search(r'\b((?:rtl|picorv32)/.*\.(?:sv|v))$', line.strip())
            if match:
                entries.append(ROOT / match[1])
        expanded = resolver(entries, ROOT)
        missing = set(expanded) - set(entries)
        if missing:
            raise RuntimeError(f'Incomplete filelist {name}: {sorted(map(str, missing))}')
        package_order = [entry for entry in entries if str(entry.relative_to(ROOT)) in packages.values()]
        if entries[:len(package_order)] != package_order:
            raise RuntimeError(f'Packages must precede modules: {name}')
        filelists.append({'path': name, 'sources': len(entries),
                          'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    tcl = args.out / 'sources.tcl'
    tcl.write_text('source {' + str(ROOT / 'fpga/vivado/tflm_ai_dsa_soc/scripts/sources.tcl') + '}\n' +
                   'foreach source_file $design_sources {puts $source_file}\n')
    result = subprocess.run(['tclsh', str(tcl)], cwd=ROOT, text=True, capture_output=True, check=True)
    vivado_sources = [Path(line) for line in result.stdout.splitlines() if line.startswith('/')]
    if not vivado_sources or len(vivado_sources) != len(set(vivado_sources)):
        raise RuntimeError('Invalid Vivado source list')
    report = {'passed': True, 'design_rtl_files': len(hashes), 'modules': len(definitions),
              'packages': len(packages), 'resource_flags': 0, 'explicit_fpga_primitives': 0,
              'multiple_definition_files': 0, 'filelists': filelists,
              'preferred_module_lines': args.max_module_lines,
              'maximum_npu_source_lines': max(count for path, count in source_lines.items()
                                              if path.startswith('rtl/npu/')),
              'sources_above_preferred_length': {path: count for path, count in source_lines.items()
                                                if count >= args.max_module_lines},
              'source_lines': source_lines,
              'vivado_sources': len(vivado_sources), 'definitions': definitions,
              'package_definitions': packages, 'source_sha256': hashes}
    (args.out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({key: value for key, value in report.items()
                      if key not in ('definitions', 'package_definitions', 'source_sha256', 'source_lines')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
