#!/usr/bin/env python3
"""证明平衡非零判断及完整帧调度器的所有状态与输出逐周期等价。"""
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
SOURCE = Path('rtl/npu/control/ps_window_scheduler.sv')
HELPER = Path('rtl/common/onehot_check.sv')
PROOF = '''module scheduler_any_proof #(
    parameter int p_width=16, parameter bit p_use_lut=1'b0
) (
    input logic [p_width-1:0] i_value,
    output logic equivalent
);
    logic any_value;
    ps_scheduler_any #(.p_width(p_width),.p_use_lut(p_use_lut)) u_dut (
        .i_value(i_value),.o_any(any_value)
    );
    assign equivalent = any_value == (|i_value);
endmodule
'''


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-rev', default='e6fd2b1f')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = [ROOT/SOURCE, ROOT/HELPER]
    hashes = {str(p.relative_to(ROOT)): digest(p) for p in sources}
    current = out/'current.sv'
    reference = out/'reference.sv'
    current.write_bytes((ROOT/SOURCE).read_bytes())
    reference.write_bytes(read_rtl_source(f'{args.reference_rev}:{SOURCE}', cwd=ROOT))
    proof = out/'any_proof.sv'
    proof.write_text(PROOF)
    import pyosys
    library = Path(pyosys.__file__).parent/'share/xilinx/cells_sim.v'
    model = out/'lut_models.sv'
    models = []
    for primitive in ('LUT6', 'LUT6_2'):
        body = re.search(r'^module '+primitive+r'\b.*?^endmodule', library.read_text(), re.M|re.S)[0]
        models.append(re.sub(r'\bspecify\b.*?\bendspecify\b', '', body, flags=re.S))
    model.write_text('\n\n'.join(models)+'\n')
    report = {'passed': False, 'reference_rev': args.reference_rev, 'source_sha256': hashes,
              'reference_sha256': digest(reference), 'source_input_constraints': False,
              'any_profiles': [], 'scheduler_profiles': [], 'primitive_model_sha256': digest(model)}

    def run(name, commands, expected):
        script = out/(name+'.ys')
        log = out/(name+'.log')
        script.write_text('\n'.join(commands)+'\n')
        with log.open('w') as stream:
            result = subprocess.run([sys.executable, str(ROOT/'scripts/fpga/open_fpga_synth.py'),
                                     '--worker', str(script)], cwd=ROOT, stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=300)
        text = log.read_text()
        if result.returncode or expected not in text:
            raise RuntimeError(f'Formal comparison did not complete: {log}')
        return text, digest(log)

    for width in (1, 2, 3, 6, 7, 16, 31, 36, 37, 64):
        for lut in (0, 1):
            commands = [f'read_slang -D ASIC_SYNTHESIS=1 --top scheduler_any_proof '
                        f'-Gp_width={width} -Gp_use_lut={lut} '+
                        ' '.join(shlex.quote(str(p)) for p in (current, model, proof)),
                        'prep -top scheduler_any_proof -flatten',
                        'sat -verify -prove equivalent 1 -show-inputs -show-outputs']
            _, log_hash = run(f'any_w{width}_lut{lut}', commands,
                              'SAT proof finished - no model found: SUCCESS!')
            report['any_profiles'].append({'width': width, 'lut': lut, 'passed': True,
                                          'log_sha256': log_hash})
    print('All balanced reduction profiles passed', flush=True)
    for size, frames, reuse in ((1, 1, 1), (4, 3, 4), (16, 16, 32), (16, 16, 0), (16, 17, 64)):
        for fpga in (False, True):
            commands = []
            for label, source in [('reference', reference), ('current', current)]:
                paths = [source, ROOT/HELPER, model]
                define = 'XILINX_FPGA=1' if fpga else 'ASIC_SYNTHESIS=1'
                commands += [f'read_slang -D {define} --top ps_window_scheduler '
                             f'-GSIZE={size} -GFRAME_COUNT={frames} -GMAX_REUSE_TILES={reuse} '+
                             ' '.join(shlex.quote(str(p)) for p in paths),
                             'prep -top ps_window_scheduler -flatten', 'memory_map', 'async2sync', 'opt_clean',
                             f'rename ps_window_scheduler {label}', f'design -stash {label}']
            commands += ['design -copy-from reference -as reference reference',
                         'design -copy-from current -as current current',
                         'equiv_make reference current equivalent', 'hierarchy -top equivalent',
                         'equiv_simple -seq 1', 'opt_clean', 'equiv_induct -seq 2', 'equiv_status -assert']
            text, log_hash = run(f'scheduler_s{size}_f{frames}_r{reuse}_fpga{int(fpga)}', commands,
                                 'Equivalence successfully proven')
            count_match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', text)
            row = {'size': size, 'frames': frames, 'max_reuse_tiles': reuse, 'fpga': fpga,
                   'passed': True, 'equivalent_bits': int(count_match[1]), 'log_sha256': log_hash}
            report['scheduler_profiles'].append(row)
            print(json.dumps(row), flush=True)
    if hashes != {str(p.relative_to(ROOT)): digest(p) for p in sources}:
        raise RuntimeError('Sources changed during verification')
    report['passed'] = True
    (out/'summary.json').write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    main()
