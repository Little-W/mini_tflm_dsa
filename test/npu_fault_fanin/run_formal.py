#!/usr/bin/env python3
"""验证实际故障表达式在全部宏组合和全部 11 位输入下的行为。"""
import argparse
import hashlib
import itertools
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

from extract_fault import ROOT, TOP, INPUTS, INPUT_BITS, region, abort_expression, module_source

VENDOR_MODEL = Path(__file__).resolve().parent / 'vendor/LUT6_2.v'
VENDOR_URL = 'https://raw.githubusercontent.com/Xilinx/XilinxUnisimLibrary/master/verilog/src/unisims/LUT6_2.v'
VENDOR_SHA256 = '07befa8fba9a87fe7f06d317e652dd34fbfa723fa7d68907001dcc71435f8f39'
MACROS = ('XILINX_FPGA', 'SYNTHESIS', 'ASIC_SYNTHESIS')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='47e51eff')
    parser.add_argument('--iverilog', default='iverilog')
    parser.add_argument('--vvp', default='vvp')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if digest(VENDOR_MODEL) != VENDOR_SHA256:
        raise RuntimeError('The saved Xilinx LUT6_2 model differs from its recorded SHA256')
    sources = {
        'reference': subprocess.check_output(['git', 'show', f'{args.reference}:{TOP}'], cwd=ROOT, text=True),
        'current': (ROOT / TOP).read_text(),
    }
    source_hash = digest(ROOT / TOP)
    snapshot = out / 'fault_logic.sv'
    snapshot.write_text(''.join(module_source(source, 'fault_' + label) for label, source in sources.items()))
    proof = out / 'proof.sv'
    proof.write_text(f'''module fault_proof(input logic [{INPUT_BITS-1}:0] i_flags,
    output logic equivalent, selected_lut,
    output logic [1:0] reference_outputs, current_outputs);
    fault_reference u_reference(.i_flags(i_flags), .task_fault(reference_outputs[0]),
        .arbiter_abort(reference_outputs[1]), .selected_lut());
    fault_current u_current(.i_flags(i_flags), .task_fault(current_outputs[0]),
        .arbiter_abort(current_outputs[1]), .selected_lut(selected_lut));
    assign equivalent = reference_outputs == current_outputs;
endmodule
''')
    tb = out / 'tb_fault.sv'
    tb.write_text(f'''module tb_fault;
    logic [{INPUT_BITS-1}:0] flags;
    wire equivalent, selected_lut;
    wire [1:0] reference_outputs, current_outputs;
    integer truth_file;
    fault_proof u_proof(.i_flags(flags), .equivalent(equivalent),
        .selected_lut(selected_lut), .reference_outputs(reference_outputs),
        .current_outputs(current_outputs));
    initial begin
        truth_file = $fopen("reference_truth.hex", "w");
        if (!truth_file) $fatal(1, "cannot write reference truth table");
        for (integer value = 0; value < {1 << INPUT_BITS}; value = value + 1) begin
            flags = {INPUT_BITS}'(value);
            #1;
            if (reference_outputs !== current_outputs)
                $fatal(1, "fault mismatch input=%h reference=%b current=%b",
                    flags, reference_outputs, current_outputs);
            if (selected_lut !== `EXPECTED_LUT)
                $fatal(1, "unexpected preprocessor branch");
            $fdisplay(truth_file, "%h", reference_outputs);
        end
        $fclose(truth_file);
        $display("PASS combinations={1 << INPUT_BITS} output_bits=2");
        $finish;
    end
endmodule
''')
    init_match = re.search(r"LUT6_2\s*#\(\.INIT\(64'h([0-9a-fA-F_]+)\)\)", region(sources['current']))
    if not init_match:
        raise RuntimeError('The dual-output fault LUT initialization is missing')
    init = int(init_match[1].replace('_', ''), 16)
    for flags in range(32):
        common_fault, run_conv, run_vector, conv_error, dma_error = (
            bool(flags & (1 << bit)) for bit in range(5))
        expected = common_fault or dma_error or ((run_conv or run_vector) and conv_error)
        assert ((init >> flags) & 1) == int(expected)
        assert ((init >> (32 + flags)) & 1) == 1
    report = {
        'reference_commit': subprocess.check_output(['git', 'rev-parse', args.reference], cwd=ROOT, text=True).strip(),
        'source_sha256': {str(TOP): source_hash},
        'reference_source_sha256': hashlib.sha256(sources['reference'].encode()).hexdigest(),
        'extracted_regions': {label: {
            'fault_region_sha256': hashlib.sha256(region(source).encode()).hexdigest(),
            'arbiter_abort_expression': abort_expression(source),
        } for label, source in sources.items()},
        'input_bits': INPUT_BITS, 'inputs': [{'name': name, 'width': width} for name, width in INPUTS],
        'inputs_constrained': False, 'output_bits': 2,
        'init': f"64'h{init:016x}", 'init_truth_table_passed': True,
        'primitive_model': {'source_url': VENDOR_URL, 'sha256': digest(VENDOR_MODEL),
                            'upstream_sha256': 'd4927b9fa9299db1332257c215c48fad31954dbab189d2bd2aa098571d65f945',
                            'implementation': 'Xilinx Unisim LUT6_2 2017.1, Apache-2.0'},
        'snapshot_sha256': digest(snapshot), 'proof_sha256': digest(proof),
        'profiles': [],
    }
    for values in itertools.product((0, 1), repeat=len(MACROS)):
        defines = [macro for macro, enabled in zip(MACROS, values) if enabled]
        name = '_'.join(defines).lower() if defines else 'generic'
        expected_lut = int(bool(values[0] or values[1]) and not values[2])
        folder = out / name
        folder.mkdir(exist_ok=True)
        script, log = folder / 'formal.ys', folder / 'formal.log'
        options = ' '.join('-D ' + name + '=1' for name in defines)
        paths = ' '.join(shlex.quote(str(path)) for path in (snapshot, proof, VENDOR_MODEL))
        script.write_text(f'read_slang --no-synthesis-define {options} --top fault_proof {paths}\n'
                          f'read_verilog -formal -sv -overwrite {shlex.quote(str(VENDOR_MODEL))}\n'
                          'prep -top fault_proof -flatten\ncheck -assert\n'
                          f'sat -verify -prove equivalent 1 -prove selected_lut {expected_lut} '
                          '-show-inputs -show-outputs\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                            '--worker', str(script)], cwd=ROOT, stdout=stream,
                           stderr=subprocess.STDOUT, check=True, timeout=120)
        if 'SAT proof finished - no model found: SUCCESS!' not in log.read_text():
            raise RuntimeError('The complete combinational proof did not succeed: ' + str(log))
        executable = folder / 'fault.vvp'
        command = [args.iverilog, '-g2012', '-s', 'tb_fault', '-o', str(executable),
                   f"-DEXPECTED_LUT=1'b{expected_lut}"]
        command += ['-D' + macro + '=1' for macro in defines]
        command += [str(path) for path in (snapshot, proof, tb, VENDOR_MODEL)]
        compile_log, numeric_log = folder / 'compile.log', folder / 'numeric.log'
        with compile_log.open('w') as stream:
            subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                           check=True, timeout=120)
        with numeric_log.open('w') as stream:
            subprocess.run([args.vvp, str(executable)], cwd=folder, stdout=stream,
                           stderr=subprocess.STDOUT, check=True, timeout=120)
        if f'PASS combinations={1 << INPUT_BITS} output_bits=2' not in numeric_log.read_text():
            raise RuntimeError('The exhaustive numerical comparison did not complete')
        case = {'defines': defines, 'fpga_lut_selected': bool(expected_lut),
                'formal_passed': True, 'numeric_passed': True,
                'numeric_combinations': 1 << INPUT_BITS,
                'script_sha256': digest(script), 'formal_log_sha256': digest(log),
                'executable_sha256': digest(executable), 'numeric_log_sha256': digest(numeric_log),
                'reference_truth_sha256': digest(folder / 'reference_truth.hex')}
        report['profiles'].append(case)
        print(json.dumps({'profile': name, **{k: case[k] for k in (
            'fpga_lut_selected', 'formal_passed', 'numeric_passed', 'numeric_combinations')}}), flush=True)
    if digest(ROOT / TOP) != source_hash:
        raise RuntimeError('The NPU source changed during verification')
    report['passed'] = True
    if len({case['reference_truth_sha256'] for case in report['profiles']}) != 1:
        raise RuntimeError('Reference outputs differ across macro combinations')
    report['numeric_combinations'] = sum(case['numeric_combinations'] for case in report['profiles'])
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
