#!/usr/bin/env python3
"""证明缓存接收前的十八位普通加法与原分组加法等价。"""
import argparse
import importlib.util
import json
from pathlib import Path
import resource
import subprocess

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('release_prepare_formal',
    ROOT / 'test/frontend_release_prepare/run_formal.py')
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)
SOURCE, CACHE = prepare.SOURCE, prepare.CACHE
REFERENCE = 'e31241c7'
ADDER_END = '    assign limit_reached ='


def adder(text):
    start = text.index('    logic [9:0] row_sum_low;') if '    logic [9:0] row_sum_low;' in text \
        else text.index('    logic unused_row_carry;')
    return text[start:text.index(ADDER_END, start)]


def source_pair(reference):
    contents = {path: dict(reference=prepare.read_rtl_source(reference + ':' + path,
        cwd=ROOT, text=True), current=(ROOT / path).read_text()) for path in (SOURCE, CACHE)}
    old, new = (contents[SOURCE][name] for name in ('reference', 'current'))
    if new.replace(adder(new), adder(old), 1) != old:
        raise RuntimeError('行偏移加法以外存在前端变化')
    if contents[CACHE]['reference'] != contents[CACHE]['current']:
        raise RuntimeError('缓存寄存、解码或控制代码发生变化')
    bodies = {name: text[text.index(prepare.BEGIN):text.index(prepare.END)]
              for name, text in contents[SOURCE].items()}
    return contents, bodies


def standalone(name, text):
    return f'''module {name}(input logic [32:0] i_value, output logic [17:0] o_value);
  localparam int row_port = 0;
  logic [0:0][15:0] retirement_input;
  logic [16:0] retire_bias_q;
  logic [17:0] biased_row;
  assign {{retirement_input, retire_bias_q}} = i_value;
''' + adder(text) + '''  assign o_value = biased_row;
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-ref', default=REFERENCE)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    contents, bodies = source_pair(args.reference_ref)
    report = dict(reference_commit=subprocess.check_output(['git', 'rev-parse', args.reference_ref],
        cwd=ROOT, text=True).strip(), inputs_constrained=False,
        unchanged_configuration_storage_control_and_decoder=True,
        source_sha256={path: {name: prepare.digest(text) for name, text in pair.items()}
                       for path, pair in contents.items()}, proofs=[])
    comparisons = {
        'independent_operands': (33, 18, ''.join(standalone(name, text)
            for name, text in contents[SOURCE].items())),
        'complete_metadata': (164, 64, ''.join(prepare.calculation(name,
            prepare.COEFFICIENTS + body[body.index(prepare.RUNTIME):])
            for name, body in bodies.items()))}
    for name, (input_bits, output_bits, text) in comparisons.items():
        folder = out / name
        folder.mkdir(exist_ok=True)
        text += f'''module proof(input logic [{input_bits-1}:0] i_value, output logic o_equal);
  logic [{output_bits-1}:0] reference_value, current_value;
  reference u_reference(.i_value(i_value), .o_value(reference_value));
  current u_current(.i_value(i_value), .o_value(current_value));
  assign o_equal = reference_value == current_value;
endmodule
'''
        rtl = folder / 'proof.sv'
        rtl.write_text(text)
        result = prepare.worker(folder, f'read_slang -j 1 --top proof {rtl}\n'
            'prep -top proof -flatten\n'
            'sat -verify -prove o_equal 1 -show-inputs -show-outputs -timeout 60\n')
        report['proofs'].append(dict(name=name, input_bits=input_bits, output_bits=output_bits,
            rtl_sha256=prepare.digest(text), **result))
        print(name + ': PASS', flush=True)
    report['maximum_resident_kib'] = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
