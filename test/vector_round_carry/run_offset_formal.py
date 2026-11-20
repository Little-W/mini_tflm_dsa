#!/usr/bin/env python3
"""对生产源码的六十四位偏移与限幅表达式执行全输入等价检查。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'rtl/npu/conv/vector_engine.sv'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source', type=Path, default=ROOT/SOURCE)
    parser.add_argument('--reference-ref', default='1c081bc')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    original = read_rtl_source(args.reference_ref+':'+SOURCE, cwd=ROOT, text=True)
    current = args.source.read_text()
    reference_body = 'logic signed [63:0] q_with_offset;\n'
    reference_body += re.search(r'assign q_with_offset\s*=.*?;', original, re.S).group(0)+'\n'
    reference_body += re.search(r'wire signed \[31:0\] q_clamped_data=.*?;', original, re.S).group(0)+'\n'
    current_body = re.search(r'  logic \[32:0\] q_offset_low;.*?logic signed \[31:0\] q_clamped_data;', current, re.S).group(0)+'\n'
    current_body += re.search(r'  assign q_offset_low\s*=.*?(?=  assign ready)', current, re.S).group(0)
    current_body += re.search(r'  assign q_clamped_data\s*=.*?;', current, re.S).group(0)+'\n'
    header = '''module offset_proof (
  input logic signed [63:0] q_rounded,
  input vector_engine_pkg::vector_engine_cfg_t c,
  output logic signed [31:0] o_result
);
'''
    commands = []
    packages = [ROOT/'rtl/npu/conv/conv_im2col_pkg.sv', ROOT/'rtl/npu/conv/vector_engine_pkg.sv']
    for name, body in (('reference', reference_body), ('current', current_body)):
        path = out/(name+'.sv')
        path.write_text(header+body+'assign o_result = q_clamped_data;\nendmodule\n')
        sources = ' '.join(shlex.quote(str(p)) for p in [*packages, path])
        commands.extend([f'read_slang -D ASIC_SYNTHESIS --top offset_proof {sources}', 'prep -top offset_proof -flatten',
                         'opt_clean', f'rename offset_proof {name}', f'design -stash {name}'])
    commands.extend(['design -copy-from reference -as reference reference',
                     'design -copy-from current -as current current',
                     'equiv_make reference current equivalent', 'hierarchy -top equivalent',
                     'equiv_simple', 'equiv_status -assert'])
    script = out/'run.ys'
    script.write_text('\n'.join(commands)+'\n')
    log = out/'formal.log'
    with log.open('w') as stream:
        result = subprocess.run([sys.executable, str(ROOT/'scripts/fpga/open_fpga_synth.py'),
                                 '--worker', str(script)], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
    report = {'passed': result.returncode == 0 and 'Equivalence successfully proven' in log.read_text(),
              'inputs_constrained': False, 'output_width': 32, 'reference_ref': args.reference_ref,
              'implementation': 'generic combinational expressions',
              'source_sha256': hashlib.sha256(current.encode()).hexdigest(),
              'reference_source_sha256': hashlib.sha256(original.encode()).hexdigest(),
              'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()}
    (out/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report), flush=True)
    if not report['passed']:
        raise RuntimeError(log.read_text()[-8000:])


if __name__ == '__main__':
    main()
