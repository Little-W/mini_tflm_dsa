#!/usr/bin/env python3
"""综合统一寄存 PE，检查并行乘法器数量及通用逻辑规模。"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
METADATA_CELL_TYPES = {'$scopeinfo'}


def counts(path):
    design = json.loads(path.read_text())
    cells = design['modules']['vector_pe_bank']['cells']
    result = {}
    metadata = {}
    for cell in cells.values():
        kind = cell['type']
        selected = metadata if kind in METADATA_CELL_TYPES else result
        selected[kind] = selected.get(kind, 0) + 1
    return result, metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--yosys')
    parser.add_argument('--counts', type=int, nargs='+', default=[1, 2, 4, 8, 16])
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    source = ROOT / 'rtl/npu/conv/vector_pe.sv'
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    yosys = args.yosys or shutil.which('yosys')
    if yosys:
        tool = subprocess.check_output([yosys, '-V'], text=True).strip()
    else:
        from importlib.metadata import version
        tool = 'pyosys ' + version('pyosys')
    summary = {
        'scope': '统一寄存 PE 及其运算逻辑，统计通用逻辑单元和寄存器。',
        'tool': tool,
        'source_sha256': digest,
        'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'metadata_cell_types': sorted(METADATA_CELL_TYPES),
        'configurations': [],
    }
    for count in args.counts:
        if count < 1:
            raise ValueError('PE count must be positive')
        out = args.out / f'pe{count}'
        out.mkdir(exist_ok=True)
        wrapper = out / 'vector_pe_bank.sv'
        wrapper.write_text(f'''module vector_pe_bank (
  input wire clk, i_en,
  input wire [2:0] op,
  input wire [{count * 16 - 1}:0] a, b,
  input wire [{count * 32 - 1}:0] acc,
  output wire [{count * 32 - 1}:0] result
);
  genvar lane;
  generate for(lane=0; lane<{count}; lane=lane+1) begin: pe
    vector_pe #(.ENABLE_EXTENDED_MULTIPLY(1'b0)) unit(
      .clk(clk), .i_en(i_en), .i_op(op), .i_a(a[lane*16+:16]), .i_b(b[lane*16+:16]),
      .i_acc(acc[lane*32+:32]), .o_result(result[lane*32+:32]));
  end endgenerate
endmodule
''')
        script = out / 'synth.ys'
        script.write_text(
            'read_verilog -sv '+shlex.join(map(str, (source, wrapper)))+'\n'
            'hierarchy -check -top vector_pe_bank\n'
            'proc; flatten; opt\n'
            f'write_json {shlex.quote(str(out / "arithmetic.json"))}\n'
            'synth -top vector_pe_bank\n'
            'check -assert\n'
            f'write_json {shlex.quote(str(out / "generic.json"))}\n'
            'stat\n')
        with (out / 'synth.log').open('w') as log:
            command = [yosys, '-s', str(script)] if yosys else [sys.executable,
                str(ROOT / 'scripts/fpga/open_fpga_synth.py'), '--worker', str(script)]
            subprocess.run(command, stdout=log,
                           stderr=subprocess.STDOUT, check=True, timeout=600)
        arithmetic, arithmetic_metadata = counts(out / 'arithmetic.json')
        generic, generic_metadata = counts(out / 'generic.json')
        if arithmetic.get('$mul') != count:
            raise RuntimeError(f'Expected {count} signed multipliers: {arithmetic}')
        summary['configurations'].append({
            'pe_count': count, 'arithmetic_cells': arithmetic,
            'arithmetic_metadata_cells': arithmetic_metadata,
            'generic_cells': generic, 'generic_cell_count': sum(generic.values()),
            'generic_metadata_cells': generic_metadata,
            'passed': True,
        })
        (args.out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
        print(f'PE_SYNTH_PASS pe_count={count} multipliers={arithmetic["$mul"]} generic_cells={sum(generic.values())}', flush=True)
    if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
        raise RuntimeError('PE source changed during synthesis')
    summary['passed'] = True
    (args.out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
