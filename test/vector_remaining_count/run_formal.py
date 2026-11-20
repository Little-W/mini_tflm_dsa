#!/usr/bin/env python3
"""比较实际向量源码的前进条件、下一偏移和有效通道数。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]


def expressions(source):
    pattern = r'VECTOR_NEXT: if \((.*?)\) begin\s+vector_offset<=(.*?);\s+active<=(.*?);'
    return re.search(pattern, source, re.S).groups()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-rev', default='2f06471c')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    relative = Path('rtl/npu/conv/vector_engine.sv')
    source = ROOT / relative
    current = source.read_text()
    reference = subprocess.check_output(
        ['git', 'show', args.reference_rev + ':' + str(relative)], cwd=ROOT, text=True)
    declarations = re.search(
        r'  logic \[ACTIVE_COUNT_W:0\] vector_low_sum;.*?logic vector_has_more;',
        current, re.S)[0]
    body = re.search(r'  assign vector_low_sum.*?(?=  // 偏移)', current, re.S)[0]
    packages = [ROOT / 'rtl/npu/conv/conv_im2col_pkg.sv',
                ROOT / 'rtl/npu/conv/vector_engine_pkg.sv']
    report = {
        'reference_rev': args.reference_rev,
        'source_sha256': hashlib.sha256(current.encode()).hexdigest(),
        'reference_sha256': hashlib.sha256(reference.encode()).hexdigest(),
        'input_constraints': None,
        'proof_scope': 'VECTOR_NEXT advance condition, next offset and next active count',
        'runs': [],
    }
    for tile in (1, 3, 16, 17, 32, 64, 255):
        folder = out / f'tile{tile}'
        folder.mkdir(exist_ok=True)
        header = f'''module remaining_compare #(
          parameter int TILE={tile}, ACTIVE_COUNT_W=$clog2(TILE+1)
        ) (
          input vector_engine_pkg::vector_engine_cfg_t c,
          input logic [31:0] vector_offset,
          input logic [ACTIVE_COUNT_W-1:0] active,
          output logic o_more,
          output logic [31:0] o_offset,
          output logic [ACTIVE_COUNT_W-1:0] o_active
        );
        '''
        commands = []
        for label, text in [('reference', reference), ('candidate', current)]:
            advance, offset, active = expressions(text)
            path = folder / (label + '.sv')
            path.write_text(header + (declarations + body if label == 'candidate' else '') +
                            f'assign o_more={advance};\nassign o_offset={offset};\n'
                            f'assign o_active={active};\nendmodule\n')
            commands += [
                'read_slang --top remaining_compare ' +
                ' '.join(shlex.quote(str(item)) for item in packages + [path]),
                'prep -top remaining_compare -flatten',
                'opt -full',
                'rename remaining_compare ' + label,
                'design -stash ' + label,
            ]
        commands += [
            'design -copy-from reference -as reference reference',
            'design -copy-from candidate -as candidate candidate',
            'miter -equiv -flatten reference candidate comparison',
            'hierarchy -top comparison',
            'opt -full',
            'sat -verify -prove trigger 0 -show-inputs -show-outputs',
        ]
        script = folder / 'run.ys'
        script.write_text('\n'.join(commands) + '\n')
        log_path = folder / 'formal.log'
        with log_path.open('w') as log:
            result = subprocess.run(
                [sys.executable, ROOT / 'scripts/fpga/open_fpga_synth.py', '--worker', script],
                cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        log_text = log_path.read_text()
        record = {'tile': tile, 'passed': result.returncode == 0 and 'SUCCESS!' in log_text,
                  'log_sha256': hashlib.sha256(log_path.read_bytes()).hexdigest()}
        report['runs'].append(record)
        print(json.dumps(record), flush=True)
        if not record['passed']:
            raise RuntimeError(log_text[-8000:])
    assert current == source.read_text()
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
