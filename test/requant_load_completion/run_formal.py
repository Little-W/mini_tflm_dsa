#!/usr/bin/env python3
"""证明命令准备资格与实际突发字数对应的完整末拍比较结果。"""
from pathlib import Path
import argparse
import json
import re
import shlex
import subprocess
import sys
from support import ROOT, RTL, HELPER, PROFILES, digest, arithmetic_unit, reference_root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-root', type=Path)
    parser.add_argument('--worker', type=Path)
    args = parser.parse_args()
    if args.worker:
        from pyosys import libyosys
        libyosys.run_pass('script ' + shlex.quote(str(args.worker)))
        return
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = args.source_root.resolve()
    reference = args.reference_root.resolve() if args.reference_root else reference_root(out / 'reference', current)
    roots = {'reference': reference, 'current': current}
    sources, hashes = [], {}
    for label, root in roots.items():
        source, helper = root / RTL, root / HELPER
        helper_name = 'parallel_prefix_add_' + label
        unit = re.sub(r'\bparallel_prefix_add\b', helper_name, arithmetic_unit(source, label))
        unit += re.sub(r'\bparallel_prefix_add\b', helper_name, helper.read_text())
        path = out / (label + '.sv')
        path.write_text(unit)
        sources.append(path)
        hashes[label] = {str(RTL): digest(source), str(HELPER): digest(helper)}
    proof = out / 'proof.sv'
    proof.write_text('''module proof #(parameter VLEN=16, REG_WIDTH=32)(input logic [31:0] need, offset);
    wire expected, observed;
    wire [31:0] expected_chunk, observed_chunk;
    arithmetic_reference #(REG_WIDTH, VLEN) r(.quant_need_load_r(need), .load_offset(offset), .result(expected), .chunk(expected_chunk));
    arithmetic_current #(REG_WIDTH, VLEN) c(.quant_need_load_r(need), .load_offset(offset), .result(observed), .chunk(observed_chunk));
    always_comb assert({expected, expected_chunk} == {observed, observed_chunk});
endmodule
''')
    report = {'passed': False, 'input_bits': 64, 'inputs_constrained': False,
              'source_sha256': hashes, 'profiles': []}
    for vlen, width in PROFILES:
        name = f'v{vlen}_w{width}'
        script, log = out / (name + '.ys'), out / (name + '.log')
        script.write_text(f'read_slang --top proof -GVLEN={vlen} -GREG_WIDTH={width} ' +
                          shlex.join(map(str, [*sources, proof])) +
                          '\nprep -top proof -flatten\nchformal -lower\nopt -full\n'
                          'sat -set-def-inputs -verify -prove-asserts -show-inputs\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, __file__, '--out', str(out), '--worker', str(script)],
                           stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=120)
        if 'SUCCESS!' not in log.read_text():
            raise RuntimeError('完整输入证明没有完成：' + str(log))
        row = {'vlen': vlen, 'reg_width': width, 'passed': True, 'log_sha256': digest(log)}
        report['profiles'].append(row)
        print(json.dumps(row), flush=True)
    for label, root in roots.items():
        if hashes[label] != {str(RTL): digest(root / RTL), str(HELPER): digest(root / HELPER)}:
            raise RuntimeError('验证期间源码发生变化')
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
