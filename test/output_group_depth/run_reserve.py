#!/usr/bin/env python3
"""Prove the actual configuration captures and runtime output reservation selection."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'test'))
from rtl_reference import read_rtl_source


def extract(source, name):
    first = source.index('        logic [REG_WIDTH-1:0] ia_reuse_num_eff;')
    first = source.index('        always_ff', first)
    end = source.index('        wire is_mode =', first)
    capture = source[first:end]
    targets = {'ia_reuse_num_eff', 'output_reserve_with_extra'}
    capture = re.sub(r'^\s*(\w+)\s*<=\s*[^;]+;\n',
                     lambda match: match[0] if match[1] in targets else '', capture, flags=re.M)
    first = source.index('        wire direct_final_stream;') + len('        wire direct_final_stream;')
    end = source.index('        wire [31:0] exec_stream_k =', first)
    context = source.find('        logic [31:0] frame_exec_rows,', first, end)
    if context >= 0:
        end = context
    arithmetic = source[first:end]
    return f'''module {name} #(parameter int REG_WIDTH=32, DIRECT_OUTPUT_EXTRA_BANKS=2) (
    input logic clk, core_rst_n, cfg_stage2_fire, direct_final_stream,
    input logic [REG_WIDTH-1:0] cfg_ia_reuse_eff_s2,
    output logic [31:0] o_reserve
);
    logic [REG_WIDTH-1:0] ia_reuse_num_eff;
    logic [31:0] output_reserve_with_extra, output_reserve_calc;
''' + capture + arithmetic + '\n    assign o_reserve = output_reserve_banks;\nendmodule\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='2297cb12')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = ROOT / 'rtl/npu/top/npu_top.sv'
    reference = read_rtl_source(args.reference + ':rtl/npu/top/npu_top.sv', cwd=ROOT, text=True)
    for label, text in (('reference', reference), ('candidate', source.read_text())):
        (out / (label + '.sv')).write_text(extract(text, label))
    harness = out / 'formal.sv'
    harness.write_text('''module reserve_formal #(
    parameter int REG_WIDTH=32, DIRECT_OUTPUT_EXTRA_BANKS=2
) (
    input logic clk, core_rst_n, cfg_stage2_fire, direct_final_stream,
    input logic [REG_WIDTH-1:0] cfg_ia_reuse_eff_s2,
    output logic o_equal
);
    logic [31:0] reference_reserve, candidate_reserve;
    reference #(.REG_WIDTH(REG_WIDTH), .DIRECT_OUTPUT_EXTRA_BANKS(DIRECT_OUTPUT_EXTRA_BANKS))
        u_reference (.*, .o_reserve(reference_reserve));
    candidate #(.REG_WIDTH(REG_WIDTH), .DIRECT_OUTPUT_EXTRA_BANKS(DIRECT_OUTPUT_EXTRA_BANKS))
        u_candidate (.*, .o_reserve(candidate_reserve));
    assign o_equal = reference_reserve == candidate_reserve;
endmodule
''')
    helper = ROOT / 'rtl/common/parallel_prefix_add.sv'
    files = [out / 'reference.sv', out / 'candidate.sv', harness, helper]
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    report = dict(reference=args.reference, source_sha256={str(p.relative_to(ROOT)):digest(p)
                  for p in (source, helper)}, inputs='Unconstrained configuration, commit, mode and subsequent reset inputs',
                  initialization='Reset on the first sampled cycle', runs=[])
    for width, extra in ((16, 2), (32, 1), (32, 2), (32, 3), (32, 7), (32, 13), (64, 2)):
        folder = out / f'w{width}_extra{extra}'
        folder.mkdir(exist_ok=True)
        script, log = folder / 'run.ys', folder / 'formal.log'
        script.write_text('read_slang --top reserve_formal ' +
                          f'-GREG_WIDTH={width} -GDIRECT_OUTPUT_EXTRA_BANKS={extra} ' +
                          shlex.join(map(str, files)) + '\nprep -top reserve_formal -flatten\n' +
                          'async2sync\nopt_clean\ncheck -assert\n' +
                          'sat -seq 2 -tempinduct -maxsteps 5 -set-at 1 core_rst_n 0 '
                          '-verify -prove o_equal 1 -show-inputs -show-outputs\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                            '--worker', str(script)], stdout=stream, stderr=subprocess.STDOUT,
                           check=True, timeout=120)
        if 'Induction step proven: SUCCESS!' not in log.read_text():
            raise RuntimeError(f'Proof did not complete: {log}')
        report['runs'].append(dict(width=width, extra=extra, passed=True, log_sha256=digest(log)))
        print(f'width={width} extra={extra}: PASS', flush=True)
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
