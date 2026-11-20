#!/usr/bin/env python3
"""比较实际 DMA 的全部公开输出并检查错误响应、排空和任务恢复。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SOURCE = Path('rtl/npu/dma/axi_block_dma_arbiter.sv')
sys.path.insert(0, str(ROOT / 'test'))
from rtl_reference import read_rtl_source


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def instrument(current):
    header = current[:re.search(r'^\s*\);', current, re.M).end()]
    parameters = re.findall(r'parameter\s+int\s+unsigned\s+(\w+)\s*=', header)
    outputs = []
    for line in header.splitlines():
        match = re.match(r'\s*output\s+logic\s+(signed\s+)?(\[[^\]]*\]\s*)?(.*)', line)
        if match is None:
            continue
        signed, width, names = match.groups()
        for item in names.rstrip(', ').split(','):
            parsed = re.fullmatch(r'\s*(\w+)\s*(\[[^\]]*\])?\s*', item)
            if parsed is None:
                raise ValueError('Unrecognized output declaration: ' + line)
            outputs.append((parsed[1], signed or '', width or '', parsed[2] or ''))
    declarations = [f'logic {signed}{width}reference_{name}{array};'
                    for name, signed, width, array in outputs]
    connections = [f'.{name}(reference_{name})' for name, _, _, _ in outputs]
    connections += ['.abort(abort || reference_bus_error)', '.*']
    parameter_map = ','.join(f'.{name}({name})' for name in parameters)
    checks = []
    for name, _, _, array in outputs:
        if name == 'bus_error':
            checks.append('if (bus_error !== expected_report) '
                          '$fatal(1,"Registered bus-error timing differs cycle=%0d",compared_cycles);')
        elif array:
            checks.append(f'for(integer i=0;i<$size({name});i=i+1) '
                          f'if({name}[i] !== reference_{name}[i]) '
                          f'$fatal(1,"DMA {name} mismatch cycle=%0d lane=%0d",compared_cycles,i);')
        else:
            checks.append(f'if({name} !== reference_{name}) '
                          f'$fatal(1,"DMA {name} mismatch cycle=%0d",compared_cycles);')
    monitor = '\n' + '\n'.join(declarations) + f'''
logic expected_report;
integer compared_cycles=0;
reference_axi_block_dma_arbiter #({parameter_map}) u_reference (
{','.join(connections)}
);
always @(posedge clk) begin
  if (!rst_n) expected_report <= 1'b0;
  else expected_report <= reference_bus_error;
end
always @(posedge clk) begin
  #1;
  if(rst_n) begin
    compared_cycles=compared_cycles+1;
    {chr(10).join(checks)}
  end
end
final $display("REGISTERED_ERROR_COMPARE_PASS outputs={len(outputs)} cycles=%0d",compared_cycles);
'''
    index = current.rindex('endmodule')
    return current[:index] + monitor + current[index:], len(outputs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-ref', default='9a6437f48722b3f53d4084b48c72cfb1d4b1fa5a')
    parser.add_argument('--verilator', default='verilator-modern')
    parser.add_argument('--bus-widths', nargs='+', type=int, choices=(32, 64), default=[32, 64])
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    original = read_rtl_source(f'{args.reference_ref}:{SOURCE}', cwd=ROOT, text=True)
    current = (ROOT / SOURCE).read_text()
    reference = out / 'reference_axi_block_dma_arbiter.sv'
    reference.write_text(original.replace('module axi_block_dma_arbiter',
                                         'module reference_axi_block_dma_arbiter', 1))
    compared = out / 'axi_block_dma_arbiter.sv'
    text, output_count = instrument(current)
    compared.write_text(text)
    packages = [ROOT / 'rtl/npu/conv/conv_im2col_pkg.sv', ROOT / 'rtl/npu/conv/vector_engine_pkg.sv']
    sources = packages + [p for p in sorted((ROOT / 'rtl/npu/conv').glob('*.sv')) if p not in packages]
    sources += sorted((ROOT / 'rtl/npu/dma').rglob('*.sv'))
    sources += sorted((ROOT / 'rtl/common').glob('*.v'))
    sources += [ROOT / 'rtl/common/add_equal.sv', ROOT / 'rtl/common/onehot_check.sv']
    sources = [compared if p == ROOT / SOURCE else p for p in sources]
    sources += [reference, HERE / 'registered_error_tb.sv']
    hashes = {str(p): digest(p) for p in sources}
    report = {'reference_ref': args.reference_ref, 'source_sha256': hashes,
              'production_arbiter_sha256': digest(ROOT / SOURCE), 'public_outputs': output_count,
              'reference_composition': 'Original arbiter receives its own immediate bus-error feedback; '
                                       'new arbiter receives the same external abort input',
              'runs': [], 'passed': False}
    for bus in args.bus_widths:
        folder = out / f'bus{bus}'
        folder.mkdir(exist_ok=True)
        command = [args.verilator, '--binary', '--timing', '--assert', '-sv',
                   '--top-module', 'registered_error_tb', f'-GBUS_WIDTH={bus}',
                   '-Wno-fatal', '-Wno-PINMISSING', '--Mdir', str(folder / 'obj'), '-j', '1',
                   '--output-groups', '0', '--output-split', '10000',
                   '-CFLAGS', '-std=c++20 -O1 -fsanitize=undefined -fno-sanitize-recover=all',
                   '-LDFLAGS', '-fsanitize=undefined',
                   '-MAKEFLAGS', 'OPT_FAST=-O1 OPT_SLOW=-O0 VK_PCH_I_FAST= VK_PCH_I_SLOW= CFG_CXXFLAGS_PCH=-E',
                   *map(str, sources)]
        with (folder / 'compile.log').open('w') as stream:
            subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                           check=True, timeout=900)
        binary = folder / 'obj/Vregistered_error_tb'
        result = subprocess.run([str(binary)], cwd=ROOT, capture_output=True, text=True, timeout=30)
        log = folder / 'run.log'
        log.write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(log.read_text())
        rows = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{"passed":')]
        comparison = re.search(r'REGISTERED_ERROR_COMPARE_PASS outputs=(\d+) cycles=(\d+)', result.stdout)
        if len(rows) != 1 or not rows[0]['passed'] or not comparison:
            raise RuntimeError('Incomplete actual-DMA error verification')
        row = dict(rows[0], public_outputs=int(comparison[1]), compared_cycles=int(comparison[2]),
                   binary_sha256=digest(binary), log_sha256=digest(log),
                   compile_command=command, undefined_behavior_sanitizer=True)
        report['runs'].append(row)
        print(json.dumps({k: v for k, v in row.items() if k != 'compile_command'}), flush=True)
        for path in binary.parent.iterdir():
            if path != binary and path.is_file() and path.suffix in ('.h', '.cpp', '.o', '.a', '.d', '.mk', '.gch'):
                path.unlink()
    if hashes != {str(p): digest(p) for p in sources} or current != (ROOT / SOURCE).read_text():
        raise RuntimeError('Sources changed during verification')
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
