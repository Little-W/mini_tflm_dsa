#!/usr/bin/env python3
"""验证配置检查器的全部原有输出和状态保持逐周期一致。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/conv/vector_config_check.sv')
sys.path.insert(0, str(ROOT/'test'))
sys.path.insert(0, str(ROOT/'scripts/fpga'))
from rtl_reference import read_rtl_source
from open_fpga_synth import run_stage


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def instrument(source, name, registers, current):
    source = source.replace('module vector_config_check #(', f'module {name} #(', 1)
    if not current:
        source = source.replace('  input logic clk,rst_n,start,',
                                '  input logic clk,rst_n,start,\n  input logic i_input_range,', 1)
    boundary = source.index('\n);')
    source = source[:boundary]+',\n  output logic [2047:0] formal_state,\n  output logic formal_invariant'+source[boundary:]
    extra = '\n  assign formal_state = {'+', '.join(registers)+'};\n'
    if current:
        extra += '''
  assign formal_invariant = state != RANGE_ADD ||
      ({range_end_carry, range_end_low} ==
       {1'b0, range_base_q[7:0]} + {1'b0, range_bytes_q[7:0]});
  always_comb assert(formal_invariant);
'''
    else:
        extra += "  assign formal_invariant = 1'b1;\n"
    return source.replace('endmodule', extra+'\nendmodule', 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='2297cb12')
    parser.add_argument('--tiles', nargs='+', type=int, default=[8, 16, 32])
    args = parser.parse_args()
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    reference = read_rtl_source(args.reference+':'+str(SOURCE), cwd=ROOT, text=True)
    current = (ROOT/SOURCE).read_text()
    registers = sorted(set(re.findall(r'(?<![.\w])(\w+)\s*<=', reference)))
    gold = out/'reference.sv'; gate = out/'current.sv'
    gold.write_text(instrument(reference, 'checker_reference', registers, False))
    gate.write_text(instrument(current, 'checker_current', registers, True))
    packages = ' '.join(shlex.quote(str(ROOT/'rtl/npu/conv'/name)) for name in
                        ('conv_im2col_pkg.sv', 'vector_engine_pkg.sv'))
    summary = {'passed': True, 'reference': args.reference, 'source_sha256': digest(current),
               'reference_sha256': digest(reference), 'input_constraints': None,
               'all_original_outputs_and_state_each_cycle': True, 'runs': []}
    for tile in args.tiles:
        script = out/f'tile_{tile}.ys'
        script.write_text(f'''read_slang --top checker_reference -GTILE={tile} {packages} {shlex.quote(str(gold))}
prep -top checker_reference -flatten
async2sync
rename checker_reference gold
design -stash gold
read_slang --top checker_current -GTILE={tile} {packages} {shlex.quote(str(gate))}
delete -output checker_current/w:o_*
prep -top checker_current -flatten
async2sync
rename checker_current gate
design -copy-from gold -as gold gold
chformal -remove
equiv_make gold gate proof
hierarchy -top proof
equiv_simple -seq 2
equiv_induct -seq 4
equiv_status -assert
''')
        result = run_stage(script, script.with_suffix('.log'), dict(os.environ))
        summary['runs'].append({'tile': tile, 'passed': True, 'state_signals': len(registers), **result})
        print(json.dumps(summary['runs'][-1]), flush=True)
    assert current == (ROOT/SOURCE).read_text()
    (out/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
