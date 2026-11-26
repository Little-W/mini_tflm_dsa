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
VERILOG_TEXT = re.compile(
    r'(?P<escaped>\\[^\s]+)|(?P<string>"(?:\\[\s\S]|[^"\\])*")|'
    r'(?P<line>//[^\n]*)|(?P<block>/\*[\s\S]*?\*/)')
VERILOG_TOKENS = re.compile(r'\\[^\s]+|[A-Za-z_][A-Za-z0-9_$]*|[^\s]')
VERILOG_IDENTIFIER = re.compile(r'[A-Za-z_][A-Za-z0-9_$]*')
FPGA_PRIMITIVE = re.compile(
    r'LUT[1-6](?:_2)?|RAMB(?:18|36)E[12]|DSP48E[12]|URAM288(?:_BASE)?')
INFERENCE_ATTRIBUTE = re.compile(r'\b(?:use_dsp|ram_style|rom_style)\s*=')


def mask_verilog_text(text: str, *, strings: bool = True) -> str:
    """保留代码位置，屏蔽注释及可选的字符串，转义标识符作为完整词元保留。"""
    def replace(match):
        if match.lastgroup == 'escaped' or (match.lastgroup == 'string' and not strings):
            return match[0]
        return re.sub(r'[^\r\n]', ' ', match[0])
    return VERILOG_TEXT.sub(replace, text)


def skip_balanced(tokens: list[str], position: int, opening: str, closing: str) -> int:
    """跳过参数括号或实例数组维度，返回结束符之后的位置。"""
    depth = 0
    while position < len(tokens):
        token = tokens[position]
        depth += token == opening
        depth -= token == closing
        position += 1
        if depth == 0:
            return position
    return position


def explicit_primitives(code: str) -> list[str]:
    """识别带可选参数和数组维度的原语实例，接受普通及转义实例名。"""
    tokens = VERILOG_TOKENS.findall(code)
    found = []
    for index, token in enumerate(tokens):
        primitive = token.removeprefix('\\')
        if not FPGA_PRIMITIVE.fullmatch(primitive):
            continue
        position = index + 1
        if position < len(tokens) and tokens[position] == '#':
            position += 1
            if position >= len(tokens) or tokens[position] != '(':
                continue
            position = skip_balanced(tokens, position, '(', ')')
        if position >= len(tokens):
            continue
        instance = tokens[position]
        if not (VERILOG_IDENTIFIER.fullmatch(instance) or
                (instance.startswith('\\') and len(instance) > 1)):
            continue
        position += 1
        while position < len(tokens) and tokens[position] == '[':
            position = skip_balanced(tokens, position, '[', ']')
        if position < len(tokens) and tokens[position] == '(':
            found.append(primitive)
    return found


def synthesis_attributes(text: str) -> list[str]:
    """记录允许的综合推断属性，包括同一属性列表中的多个键值。"""
    uncommented = mask_verilog_text(text, strings=False)
    return [attribute.strip() for attribute in re.findall(r'\(\*(.*?)\*\)', uncommented, flags=re.S)
            if INFERENCE_ATTRIBUTE.search(mask_verilog_text(attribute))]


def check_detection_examples() -> int:
    """检查原语实例语法、字符串与注释，以及允许的资源推断属性。"""
    cases = (
        ('LUT6 u_lut (.O(y));', ['LUT6']),
        ("LUT6 #(.INIT(64'h0)) u_lut (.O(y));", ['LUT6']),
        ('LUT6 u_lut [0:3] (.O(y));', ['LUT6']),
        ('RAMB36E1 #(.READ_WIDTH_A(9)) u_mem [1:0][2:0] (.CLKARDCLK(clk));', ['RAMB36E1']),
        (r'DSP48E1 \mac.output  (.CLK(clk));', ['DSP48E1']),
        (r'\LUT6 \lane.0  [3:0] (.O(y));', ['LUT6']),
        (r'LUT6 \lane//0  (.O(y));', ['LUT6']),
        ('// LUT6 u_debug (.O(y));\n/* DSP48E1 u_debug (.CLK(clk)); */', []),
        ('$display("LUT6 u_debug (");', []),
        (r'$display("quoted \"RAMB36E1 u_debug (\" // text");', []),
        ('(* use_dsp = "simd" *) logic [16:0] sum;', []),
        ('(* ram_style = "block", rom_style = "distributed" *) logic [7:0] memory [256];', []),
    )
    for text, expected in cases:
        actual = explicit_primitives(mask_verilog_text(text))
        if actual != expected:
            raise RuntimeError(f'Primitive detection self-check: {text!r}: {actual!r}')
    attributes = synthesis_attributes('(* keep = "true", use_dsp = "simd" *) logic [16:0] sum;')
    if attributes != ['keep = "true", use_dsp = "simd"']:
        raise RuntimeError('Inference-attribute detection self-check')
    return len(cases) + 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--max-module-lines', type=int, default=1500)
    args = parser.parse_args()
    detection_examples = check_detection_examples()
    args.out.mkdir(parents=True, exist_ok=True)
    definitions = {}
    packages = {}
    hashes = {}
    source_lines = {}
    inference_attributes = {}
    for path in sorted((ROOT / 'rtl').rglob('*')):
        if path.suffix not in ('.v', '.sv') or 'GV' in path.relative_to(ROOT / 'rtl').parts:
            continue
        text = path.read_text()
        code = mask_verilog_text(text)
        modules = re.findall(r'\bmodule\s+(\w+)\b', code)
        package_names = re.findall(r'\bpackage\s+(\w+)\b', code)
        if len(modules) + len(package_names) != 1:
            raise RuntimeError(f'Expected one module or package: {path}')
        # 资源类型选择参数与普通算术结构参数分别检查；综合推断属性单独记录。
        if re.search(r'\bparameter\s+(?:(?:bit|logic|int|integer|unsigned|signed)\s+)*'
                     r'(?:p_use_dsp|p_use_lut|p_infer_dsp)\b', code):
            raise RuntimeError(f'Resource-selection flag: {path}')
        if explicit_primitives(code):
            raise RuntimeError(f'Explicit FPGA primitive: {path}')
        relative = str(path.relative_to(ROOT))
        attributes = synthesis_attributes(text)
        if attributes:
            inference_attributes[relative] = attributes
        hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        source_lines[relative] = len(text.splitlines())
        if relative.startswith('rtl/npu/') and source_lines[relative] > args.max_module_lines:
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
            match = re.search(r'\b((?:rtl|picorv32|test/models)/.*\.(?:sv|v))$', line.strip())
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
    report = {'passed': True, 'detection_examples': detection_examples,
              'design_rtl_files': len(hashes), 'modules': len(definitions),
              'packages': len(packages), 'resource_flags': 0, 'explicit_fpga_primitives': 0,
              'synthesis_inference_attributes': inference_attributes,
              'multiple_definition_files': 0, 'filelists': filelists,
              'preferred_module_lines': args.max_module_lines,
              'maximum_npu_source_lines': max(count for path, count in source_lines.items()
                                              if path.startswith('rtl/npu/')),
              'sources_above_preferred_length': {path: count for path, count in source_lines.items()
                                                if count > args.max_module_lines},
              'source_lines': source_lines,
              'vivado_sources': len(vivado_sources), 'definitions': definitions,
              'package_definitions': packages, 'source_sha256': hashes}
    (args.out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({key: value for key, value in report.items()
                      if key not in ('definitions', 'package_definitions', 'source_sha256', 'source_lines')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
