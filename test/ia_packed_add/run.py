#!/usr/bin/env python3
"""检查四通道分段加法的完整输入空间和四态传播。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'test/ia_write_output_depth'))
from primitives import prepare_models


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--iverilog', default='iverilog')
    parser.add_argument('--vvp', default='vvp')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    model, model_info = prepare_models(out, names=('DSP48E1',))
    sources = [ROOT / 'rtl/npu/compute/select_add.sv',
               Path(__file__).with_name('packed_add_formal.sv')]
    hashes = {str(p.relative_to(ROOT)): digest(p) for p in sources}
    summary = dict(passed=False, source_sha256=hashes, primitive_models=model_info,
                   inputs_constrained=False, formal=[])
    profiles = [('packed', width, dsp) for width in (8, 12) for dsp in (0, 1)]
    profiles += [('restore', width, dsp) for width in (1, 8, 9, 11) for dsp in (0, 1)]
    for kind, width, dsp in profiles:
        name = f'{kind}_width{width}_dsp{dsp}'
        top = 'packed_add_formal' if kind == 'packed' else 'restore_add_formal'
        width_name = 'p_lane_width' if kind == 'packed' else 'p_offset_width'
        properties = '-prove o_equivalent 1'
        if kind == 'packed':
            properties += ' -prove o_padding_zero 1'
        commands = [f'read_slang --top {top} -DYOSYS=1 -DVERIFIC=1 '
                    f'-G{width_name}={width} -Gp_use_dsp={dsp} ' +
                    ' '.join(shlex.quote(str(p)) for p in [*sources, model]),
                    f'prep -top {top} -flatten',
                    f'sat -verify {properties} -show-inputs -show-outputs']
        script = out / (name + '.ys')
        script.write_text('\n'.join(commands) + '\n')
        log = out / (name + '.log')
        with log.open('w') as stream:
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                     '--worker', str(script)], cwd=ROOT,
                                    stdout=stream, stderr=subprocess.STDOUT, timeout=120)
        row = dict(kind=kind, width=width, use_dsp=bool(dsp),
                   input_bits=12*width+2 if kind == 'packed' else 32+width,
                   passed=result.returncode == 0 and 'no model found: SUCCESS!' in log.read_text(),
                   script_sha256=digest(script), log_sha256=digest(log))
        summary['formal'].append(row)
        print(json.dumps(row), flush=True)
        if not row['passed']:
            raise RuntimeError('Packed addition proof did not complete: ' + str(log))
    binary = out / 'four_state.vvp'
    testbench = Path(__file__).with_name('tb_four_state.sv')
    command = [args.iverilog, '-g2012', '-s', 'tb_four_state', '-o', str(binary),
               *map(str, sources), str(model), str(testbench)]
    with (out / 'compile.log').open('w') as stream:
        subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
    result = subprocess.run([args.vvp, str(binary)], cwd=ROOT, capture_output=True, text=True, check=True)
    log = out / 'four_state.log'
    log.write_text(result.stdout + result.stderr)
    counts = re.search(r'PACKED_ADD_FOUR_STATE_PASS cases=(\d+) comparisons=(\d+)', result.stdout)
    if not counts:
        raise RuntimeError('Four-state comparison did not complete: ' + str(log))
    summary['four_state'] = dict(passed=True, cases=int(counts[1]), comparisons=int(counts[2]),
                                log_sha256=digest(log), testbench_sha256=digest(testbench))
    if hashes != {str(p.relative_to(ROOT)): digest(p) for p in sources}:
        raise RuntimeError('RTL changed during verification')
    summary['passed'] = True
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary['four_state']), flush=True)


if __name__ == '__main__':
    main()
