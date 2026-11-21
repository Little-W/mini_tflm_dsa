#!/usr/bin/env python3
"""证明舍入流水的完整输入域，并检查 X、Z 传播及寄存延迟。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/conv/vector_round_shift.sv')
sys.path.insert(0, str(ROOT / 'test'))
from rtl_reference import read_rtl_source


def run(command, log):
    with log.open('w') as output:
        result = subprocess.run(list(map(str, command)), cwd=ROOT, stdout=output,
                                stderr=subprocess.STDOUT, timeout=240)
    if result.returncode:
        raise RuntimeError(f'检查未完成：{log}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference', default='415a70a')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--iverilog', default='iverilog')
    parser.add_argument('--vvp', default='vvp')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (args.source_root.resolve() / SOURCE).read_text()
    original = read_rtl_source(args.reference + ':' + str(SOURCE), cwd=ROOT, text=True)
    reference = out / 'reference.sv'
    reference.write_text(original.replace('module vector_round_shift', 'module round_reference'))
    candidate = out / 'current.sv'
    candidate.write_text(current.replace('module vector_round_shift', 'module round_current'))
    import pyosys
    library = Path(pyosys.__file__).parent / 'share/xilinx/cells_sim.v'
    model = out / 'lut6_model.sv'
    block = re.search(r'^module LUT6\b.*?^endmodule', library.read_text(), re.M | re.S)[0]
    model.write_text(re.sub(r'\bspecify\b.*?\bendspecify\b', '', block, flags=re.S) + '\n')
    report = {'source_sha256': hashlib.sha256(current.encode()).hexdigest(),
              'reference': args.reference,
              'reference_sha256': hashlib.sha256(original.encode()).hexdigest(),
              'input_scope': '每周期任意 64 位有符号输入及任意 6 位移位量。',
              'input_constraints': None, 'formal_runs': [],
              'test_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'testbench_sha256': hashlib.sha256(Path(__file__).with_name('tb.sv').read_bytes()).hexdigest()}
    header = '''(input logic clk, input logic signed [63:0] value,
      input logic [5:0] amount, output logic signed [63:0] result, floor_value);\n'''
    profiles = [(mode, define, middle, input_stage)
                for mode, define in [('fpga', 'XILINX_FPGA'), ('generic', 'ASIC_SYNTHESIS')]
                for middle in (0, 1) for input_stage in (0, 1)]
    for mode, define, middle, input_stage in profiles:
        folder = out / f'{mode}_middle{middle}_input{input_stage}'
        folder.mkdir(exist_ok=True)
        old = folder / 'reference_top.sv'
        old.write_text('module reference_top ' + header + f'''
          logic signed [63:0] delayed_value;
          logic [5:0] delayed_amount;
          if ({input_stage}) begin
            always_ff @(posedge clk) begin
              delayed_value <= value;
              delayed_amount <= amount;
            end
          end else begin
            assign delayed_value = value;
            assign delayed_amount = amount;
          end
          round_reference #(.REGISTER_MIDDLE({middle})) u_reference(
            .clk, .value(delayed_value), .amount(delayed_amount), .result, .floor_value);
        endmodule
        ''')
        new = folder / 'current_top.sv'
        new.write_text('module current_top ' + header + f'''
          round_current #(.REGISTER_MIDDLE({middle}), .REGISTER_INPUT({input_stage})) u_current(
            .clk, .value, .amount, .result, .floor_value);
        endmodule
        ''')
        commands = []
        for label, source, wrapper in [('reference', reference, old), ('current', candidate, new)]:
            commands += [f'read_slang -D {define}=1 --top {label}_top ' +
                         ' '.join(shlex.quote(str(p)) for p in (source, wrapper, model)),
                         f'prep -top {label}_top -flatten', 'memory_map', 'opt -full',
                         f'rename {label}_top {label}', f'design -stash {label}']
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from current -as current current',
                     'equiv_make reference current comparison', 'hierarchy -top comparison',
                     'equiv_simple -seq 3', 'opt_clean', 'equiv_induct -seq 4',
                     'equiv_status -assert']
        script = folder / 'run.ys'
        script.write_text('\n'.join(commands) + '\n')
        log = folder / 'formal.log'
        run([sys.executable, ROOT / 'scripts/fpga/open_fpga_synth.py', '--worker', script], log)
        assert 'Equivalence successfully proven' in log.read_text()
        row = {'implementation': mode, 'REGISTER_MIDDLE': middle, 'REGISTER_INPUT': input_stage, 'passed': True,
               'outputs': ['result[63:0]', 'floor_value[63:0]'],
               'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()}
        report['formal_runs'].append(row)
        print(json.dumps(row), flush=True)

    tb = Path(__file__).with_name('tb.sv')
    report['four_state_runs'] = []
    for mode, define in [('fpga', 'XILINX_FPGA'), ('generic', 'ASIC_SYNTHESIS')]:
        binary = out / f'{mode}_simulation.vvp'
        run([args.iverilog, '-g2012', '-D' + define, '-s', 'tb', '-o', binary,
             reference, candidate, model, tb], out / f'{mode}_build.log')
        log = out / f'{mode}_four_state.log'
        run([args.vvp, binary], log)
        text = log.read_text()
        assert 'ROUND_PIPELINE_FOUR_STATE_PASS checks=52352 configurations=4 outputs=2' in text
        report['four_state_runs'].append({'implementation': mode, 'passed': True,
                                         'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()})
        print(text, end='', flush=True)
    report['four_state_checks'] = 52352
    report['four_state_configurations'] = 4
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
