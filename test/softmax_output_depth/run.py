#!/usr/bin/env python3
"""验证 Softmax 结果舍入的完整状态、四态传播及实际整数结果。"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/conv/vector_softmax.sv')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def logged(command, path):
    with path.open('w') as stream:
        subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
    return path.read_text()


def rounding_unit(text, label):
    declarations = text[text.index('  logic signed [17:0] output_shift8;'):
                        text.index('  logic [31:0] reciprocal_rounded_word;')]
    body = text[text.index('  assign output_shift8 ='):
                text.index('  // 正向饱和条件由舍入前的商确定')]
    begin = text.index('    if (output_shift_base_q[17]) begin')
    end = text.index('\n  end', begin)
    rounded = 'output_rounded_byte' if 'output_rounded_byte' in text else 'output_small[7:0]'
    return f'''module {label}_rounding (
    input logic signed [17:0] output_shift_base_q,
    input logic [5:0] result_shift,
    output logic signed [7:0] out_data,
    output logic [7:0] small_value
);
{declarations}
{body}
  assign small_value = {rounded};
  always_comb begin
{text[begin:end]}
  end
endmodule
'''


def four_state(folder, reference, current):
    folder.mkdir(parents=True, exist_ok=True)
    rtl = folder / 'rounding.sv'
    rtl.write_text(rounding_unit(reference, 'reference') + rounding_unit(current, 'current'))
    tb = folder / 'tb.sv'
    tb.write_text('''module tb;
  logic signed [17:0] value;
  logic [5:0] shift;
  logic signed [7:0] reference_result, current_result;
  logic [7:0] reference_small, current_small;
  integer samples = 0;
  reference_rounding a(value, shift, reference_result, reference_small);
  current_rounding b(value, shift, current_result, current_small);
  task automatic check;
    #1;
    if (reference_result !== current_result || reference_small !== current_small)
      $fatal(1, "rounding value=%h shift=%h reference=%h/%h current=%h/%h",
          value, shift, reference_result, reference_small, current_result, current_small);
    samples++;
  endtask
  initial begin
    for (integer amount=0; amount<64; amount++) begin
      shift=6'(amount);
      for (integer sample=0; sample<1024; sample++) begin
        value=18'($urandom);
        case(sample%8)
          0: value='0;
          1: value='1;
          2: value=18'(sample);
          3: value=18'(18'h20000+sample);
          default: begin end
        endcase
        check();
      end
      for (integer bit_index=0; bit_index<18; bit_index++) begin
        for (integer pattern=0; pattern<8; pattern++) begin
          value=pattern[0] ? '1 : '0;
          if (pattern[1]) value=18'($urandom);
          value[bit_index]=pattern[2] ? 1'bz : 1'bx;
          check();
        end
      end
      for (integer bit_index=0; bit_index<6; bit_index++) begin
        for (integer pattern=0; pattern<16; pattern++) begin
          value=18'($urandom);
          shift=6'(amount);
          shift[bit_index]=pattern[0] ? 1'bz : 1'bx;
          check();
        end
      end
    end
    $display("SOFTMAX_OUTPUT_FOUR_STATE_PASS samples=%0d", samples);
    $finish;
  end
endmodule
''')
    logged(['iverilog', '-g2012', '-s', 'tb', '-o', str(folder / 'sim'), str(rtl), str(tb)],
           folder / 'compile.log')
    text = logged(['vvp', str(folder / 'sim')], folder / 'run.log')
    samples = re.search(r'SOFTMAX_OUTPUT_FOUR_STATE_PASS samples=(\d+)', text)
    if not samples:
        raise RuntimeError('四态检查未输出完整结果')
    return dict(passed=True, samples=int(samples.group(1)), states=['0', '1', 'x', 'z'],
                extracted_source_sha256=digest(rtl), testbench_sha256=digest(tb))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-root', type=Path)
    parser.add_argument('--baseline-ref', default='aa0a169c')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--numeric', action='store_true')
    parser.add_argument('--verilator', default='verilator')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current_path = args.source_root.resolve() / SOURCE
    original = ((args.reference_root / SOURCE).read_bytes() if args.reference_root else
                subprocess.check_output(['git', 'show', f'{args.baseline_ref}:{SOURCE}'], cwd=ROOT))
    reference = out / 'reference.sv'
    current = out / 'current.sv'
    reference.write_bytes(original)
    current.write_bytes(current_path.read_bytes())
    result = dict(passed=False, reference_revision=str(args.reference_root or args.baseline_ref),
                  source_sha256={str(SOURCE): digest(current)},
                  reference_source_sha256={str(SOURCE): digest(reference)},
                  all_public_outputs_and_common_states_compared=True, input_constraints=[], runs=[])
    for mode in ('generic', 'fpga'):
        for depth, latency in ((1, 0), (3, 1), (16, 0), (16, 2), (32, 2), (256, 2)):
            folder = out / 'formal' / f'{mode}_d{depth}_l{latency}'
            folder.mkdir(parents=True, exist_ok=True)
            commands = []
            for label, source in (('reference', reference), ('current', current)):
                define = 'XILINX_FPGA' if mode == 'fpga' else 'ASIC_SYNTHESIS'
                commands += [f'read_slang -D SYNTHESIS=1 -D {define}=1 --top vector_softmax '
                             f'-GMAX_DEPTH={depth} -GMULTIPLIER_LATENCY={latency} {shlex.quote(str(source))}',
                             'prep -top vector_softmax -flatten', 'async2sync', 'opt_clean',
                             f'rename vector_softmax {label}', f'design -stash {label}']
            commands += ['design -copy-from reference -as reference reference',
                         'design -copy-from current -as current current',
                         'equiv_make reference current comparison', 'hierarchy -top comparison',
                         'equiv_simple -seq 2', 'opt_clean', 'equiv_induct -seq 3',
                         'equiv_status -assert']
            script = folder / 'proof.ys'
            script.write_text('\n'.join(commands) + '\n')
            log = logged([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                          '--worker', str(script)], folder / 'proof.log')
            if 'Equivalence successfully proven' not in log:
                raise RuntimeError(f'完整等价检查未完成：{folder}')
            count = re.search(r'Of those cells (\d+) are proven and 0 are unproven', log)
            record = dict(mode=mode, depth=depth, multiplier_latency=latency, passed=True,
                          equivalent_bits=int(count.group(1)) if count else None)
            result['runs'].append(record)
            print(json.dumps(record), flush=True)
    result['four_state'] = four_state(out / 'four_state', reference.read_text(), current.read_text())
    if args.numeric:
        path = ROOT / 'test/vector_softmax_normalize/run.py'
        spec = importlib.util.spec_from_file_location('softmax_numeric', path)
        numeric = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(numeric)
        numeric.SOURCE = current
        result['numeric'] = numeric.numerical(out, ROOT / 'drivers/tflm/tflm/tflite-micro', args.verilator)
    if digest(current_path) != digest(current):
        raise RuntimeError('验证期间输入源码发生变化')
    result['passed'] = True
    result['runner_sha256'] = digest(Path(__file__).resolve())
    (out / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(dict(passed=True, profiles=len(result['runs']), four_state=result['four_state'])))


if __name__ == '__main__':
    main()
