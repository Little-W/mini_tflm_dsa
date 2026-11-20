#!/usr/bin/env python3
"""验证 Softmax 分段归一化、事务结果和原生组合路径。"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/conv/vector_softmax.sv')
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
sys.path.insert(0, str(ROOT / 'test'))
from netlist_metrics import connected_paths, register_origins, resources
from open_fpga_synth import run_stage
from rtl_reference import read_rtl_source


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalization_unit(text, current):
    if current:
        begin = text.index('  logic normalization_invalid;')
        first = text.index('  // 有效累计值位于')
    else:
        begin = text.index('  logic norm16_zero;')
        first = text.index('  assign norm16_zero')
    end = text.index('  logic signed [32:0] reciprocal_input_quotient;', begin)
    declarations = text[begin:end]
    end = text.index('  // 接收乘积时', first)
    logic = text[first:end].replace('(c_st == NORMALIZE)', '(i_enable)')
    label = 'current' if current else 'reference'
    invalid = 'normalization_invalid' if current else '(sum == 0 || sum[31] || leading_zeros > 12)'
    return f'''module {label}_normalization (
    input logic clk, i_enable,
    input logic [31:0] sum,
    output logic invalid,
    output logic [31:0] denominator,
    output logic [5:0] result_shift
);
    logic [5:0] leading_zeros;
    logic [31:0] normalized_minus_one;
''' + declarations + logic + f'''
    assign invalid = {invalid};
    assign denominator = {{2'b01, normalized_minus_one[30:2],
        (normalized_minus_one[1] && normalized_minus_one[0])}};
    assign result_shift = 6'(7'd66 - {{1'b0, leading_zeros}});
endmodule
'''


PROOF = '''module normalization_proof (
    input logic clk, rst_n, i_enable,
    input logic [31:0] sum
);
    logic reference_invalid, current_invalid;
    logic [31:0] reference_denominator, current_denominator, expected_denominator;
    logic [5:0] reference_shift, current_shift, expected_shift;
    logic expected_valid;
    reference_normalization u_reference (
        .clk(clk), .i_enable(i_enable), .sum(sum), .invalid(reference_invalid),
        .denominator(reference_denominator), .result_shift(reference_shift)
    );
    current_normalization u_current (
        .clk(clk), .i_enable(i_enable), .sum(sum), .invalid(current_invalid),
        .denominator(current_denominator), .result_shift(current_shift)
    );
    always_ff @(posedge clk) begin
        if (!rst_n) expected_valid <= 1'b0;
        else if (i_enable) expected_valid <= !reference_invalid;
        if (i_enable) begin
            expected_denominator <= reference_denominator;
            expected_shift <= reference_shift;
        end
    end
    always_comb begin
        assert(current_invalid == reference_invalid);
        if (expected_valid) begin
            assert(current_denominator == expected_denominator);
            assert(current_shift == expected_shift);
        end
    end
endmodule
'''


def formal(out, reference, current):
    folder = out / 'formal'
    folder.mkdir(exist_ok=True)
    source = folder / 'normalization.sv'
    source.write_text(normalization_unit(reference, False) +
                      normalization_unit(current, True) + PROOF)
    script = folder / 'proof.ys'
    script.write_text(f'read_slang --top normalization_proof {shlex.quote(str(source))}\n'
                      'prep -top normalization_proof -flatten\nchformal -lower\nopt -full\n'
                      'sat -verify -seq 3 -prove-asserts -prove-skip 1 -set-def-inputs '
                      '-set-at 1 rst_n 0 -set-at 2 rst_n 1 -set-at 3 rst_n 1\n')
    result = run_stage(script, folder / 'proof.log', dict(os.environ))
    normalization = {'passed': True, 'input_bits': 32, 'input_constraints': None,
                     'sample_register_edges': 1, 'enable_and_hold_checked': True,
                     'extracted_source_sha256': digest(source), **result}
    rounding_source = folder / 'rounding.sv'
    units = []
    for label, text in (('reference', reference), ('current', current)):
        begin = text.index('  assign reciprocal_rounded =') if label == 'reference' else \
            text.index('  // 正向饱和条件由舍入前的商确定')
        end = text.index('  assign update_scaled', begin)
        declarations = 'logic signed [33:0] reciprocal_rounded;' if label == 'reference' else '''
    logic [31:0] reciprocal_rounded_word;
    logic [3:0] reciprocal_byte_carry;
    logic reciprocal_above_range;'''
        units.append(f'''module {label}_rounding (
    input logic signed [32:0] reciprocal_quotient_q,
    input logic reciprocal_increment_q,
    output logic signed [31:0] reciprocal_rounded_q31
);
{declarations}
{text[begin:end]}
endmodule
''')
    rounding_source.write_text(''.join(units) + '''module rounding_proof (
    input logic signed [32:0] quotient,
    input logic increment,
    output logic equal
);
    logic signed [31:0] reference_result, current_result;
    reference_rounding u_reference (.reciprocal_quotient_q(quotient),
        .reciprocal_increment_q(increment), .reciprocal_rounded_q31(reference_result));
    current_rounding u_current (.reciprocal_quotient_q(quotient),
        .reciprocal_increment_q(increment), .reciprocal_rounded_q31(current_result));
    assign equal = reference_result == current_result;
endmodule
''')
    rounding_script = folder / 'rounding.ys'
    rounding_script.write_text(f'read_slang --top rounding_proof {shlex.quote(str(rounding_source))}\n'
                              'prep -top rounding_proof -flatten\nopt -full\n'
                              'sat -verify -prove equal 1 -set-def-inputs\n')
    rounding_result = run_stage(rounding_script, folder / 'rounding.log', dict(os.environ))
    estimate_source = folder / 'estimate.sv'
    begin = current.index('  assign update_scaled')
    end = current.index('  assign reciprocal_scaled', begin)
    estimate_body = current[begin:end].replace('(c_st == RECIP_INIT_WAIT)', 'i_initial')
    estimate_source.write_text('''module estimate_proof (
    input logic i_initial,
    input logic signed [31:0] estimate, reciprocal_q31,
    output logic equal
);
    logic signed [33:0] update_scaled;
    logic signed [31:0] update_saturated;
    logic [31:0] estimate_lhs, estimate_rhs, estimate_next;
    logic [16:0] estimate_low;
    logic [15:0] estimate_high_direct, estimate_high_increment;
    logic [31:0] expected;
''' + estimate_body + '''
    assign expected = i_initial ? 32'd1515870810 + reciprocal_q31 : estimate + update_saturated;
    assign equal = estimate_next == expected;
endmodule
''')
    estimate_script = folder / 'estimate.ys'
    estimate_script.write_text(f'read_slang --top estimate_proof {shlex.quote(str(estimate_source))}\n'
                              'prep -top estimate_proof -flatten\nopt -full\n'
                              'sat -verify -prove equal 1 -set-def-inputs\n')
    estimate_result = run_stage(estimate_script, folder / 'estimate.log', dict(os.environ))
    return {'normalization': normalization,
            'rounding': {'passed': True, 'input_bits': 34, 'input_constraints': None,
                         'extracted_source_sha256': digest(rounding_source), **rounding_result},
            'estimate': {'passed': True, 'input_bits': 65, 'input_constraints': None,
                         'extracted_source_sha256': digest(estimate_source), **estimate_result}}


def mapped(out, reference):
    original = out / 'reference.sv'
    original.write_text(reference)
    cases = {name: {'top': 'vector_softmax',
                   'options': ['-D', 'SYNTHESIS=1', '-GMAX_DEPTH=16', '-GMULTIPLIER_LATENCY=2'],
                   'sources': [str(source)], 'configuration': '完整 Softmax，原生算术映射'}
             for name, source in (('reference', original), ('current', ROOT / SOURCE))}
    configuration = out / 'cases.json'
    configuration.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + '\n')
    with (out / 'prepare.log').open('w') as log:
        subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                        '--case-config', str(configuration), '--cases', 'reference', 'current',
                        '--out', str(out / 'native'), '--through', 'pre_lut'],
                       cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    cost = out / 'unit_lut_cost.lut'
    cost.write_text(''.join(f'{width} 1 1\n' for width in range(1, 7)))
    result = {}
    for name in ('reference', 'current'):
        folder = out / 'native' / name
        pre = folder / 'pre_lut.il'
        target = folder / 'mapped.json'
        script = folder / 'native_map.ys'
        script.write_text(f'''read_rtlil {shlex.quote(str(pre))}
read_verilog -lib -specify -overwrite +/xilinx/cells_sim.v
read_verilog -lib -overwrite +/xilinx/cells_xtra.v
opt_expr -mux_undef -noclkinv
read_verilog -icells -lib -specify +/xilinx/abc9_model.v
scratchpad -set abc9.xaiger 1
scratchpad -set abc9.verify 1
abc9 -W 500 -lut {shlex.quote(str(cost))} -D 6667
clean
techmap -map +/xilinx/lut_map.v -map +/xilinx/cells_map.v -D LUT_WIDTH=6
xilinx_dffopt
opt_lut_ins -tech xilinx
synth_xilinx -top vector_softmax -family xc7 -noiopad -noclkbuf -run finalize:
check -assert
write_json {shlex.quote(str(target))}
stat
''')
        stage = run_stage(script, folder / 'native_map.log', dict(os.environ))
        module = json.loads(target.read_text())['modules']['vector_softmax']
        for cell, origin in register_origins(pre).items():
            if cell in module['cells']:
                module['cells'][cell].setdefault('attributes', {})['fpga_register_origin'] = origin
        normalization_paths = connected_paths(module, limit=4, group_limit=5,
            sink_filter=lambda name, cell, port: any(value in cell.get('attributes', {}).get(
                'fpga_register_origin', '') for value in ('half_denominator', 'result_shift', 'norm8_q')))
        result[name] = {'resources': resources(module['cells']),
                        'paths': connected_paths(module, limit=4, group_limit=8),
                        'normalization_paths': normalization_paths,
                        'mapped_json_sha256': digest(target), 'stage': stage}
        for path in (target, pre, folder / 'elaborated.il'):
            with path.open('rb') as stream, gzip.open(str(path) + '.gz', 'wb') as output:
                shutil.copyfileobj(stream, output)
            path.unlink()
    return result


def numerical(out, tflm_root, verilator):
    folder = out / 'numeric'
    folder.mkdir(exist_ok=True)
    top = (ROOT / 'test/vector_softmax/vector_softmax_test.sv').read_text()
    top = top.replace('parameter int MAX_DEPTH=16,',
                      'parameter int MAX_DEPTH=16,\n  parameter int MULTIPLIER_LATENCY=0,')
    top = top.replace('output logic signed [7:0] out_data\n',
                      'output logic signed [7:0] out_data,\n  output logic [1:0] normalization_phase\n')
    top = top.replace('  assign mul_product=mul_a*mul_b;', '''  if (MULTIPLIER_LATENCY == 0) begin : g_direct
    assign mul_product=mul_a*mul_b;
  end else begin : g_pipe
    logic signed [63:0] product_first, product_second;
    always_ff @(posedge clk) begin
      product_first <= mul_a*mul_b;
      product_second <= product_first;
    end
    assign mul_product=product_second;
  end
  assign normalization_phase = (dut.c_st == dut.NORMALIZE) ? 2'd1 :
      (dut.c_st == dut.NORMALIZE_COMMIT) ? 2'd2 : 2'd0;''')
    top = top.replace('vector_softmax #(.MAX_DEPTH(MAX_DEPTH))',
                      'vector_softmax #(.MAX_DEPTH(MAX_DEPTH),.MULTIPLIER_LATENCY(MULTIPLIER_LATENCY))')
    state_text = re.search(r'typedef enum logic \[4:0\] \{(.*?)\} state_t;',
                           (ROOT / SOURCE).read_text(), re.S).group(1)
    state_names = [name.strip() for name in state_text.split(',')]
    for name in ('NORMALIZE_COMMIT', 'NORMALIZE'):
        top = top.replace('dut.' + name, f"5'd{state_names.index(name)}")
    wrapper = folder / 'vector_softmax_test.sv'
    wrapper.write_text(top)
    main_source = (ROOT / 'test/vector_softmax/main.cpp').read_text()
    main_source = main_source.replace('std::copy(values.begin(),values.end(),input.begin());',
        'std::copy_n(values.begin(),std::min(values.size(),input.size()),input.begin());')
    marker = '\n  void run(const std::vector<int8_t>& values,'
    cancel = '''
  void cancel_normalization(const Table& lut, unsigned phase) {
    table=&lut;input.fill(1);exponent.fill(0);output.fill(0);
    pending=-1;requests=0;writes=0;fail_request=-1;pending_error=false;
    dut.depth=3;dut.start=1;tick();dut.start=0;
    unsigned waited=0;
    while(dut.normalization_phase!=phase) {
      tick();
      if(++waited>1000) throw std::runtime_error("normalization phase timeout");
    }
    if(writes || dut.ready) throw std::runtime_error("normalization phase outputs");
    pending=-1;dut.rst_n=0;tick();dut.rst_n=1;tick();
    if(!dut.ready || dut.done || dut.out_we || dut.lut_req_valid)
      throw std::runtime_error("normalization reset recovery");
    ++case_count;
  }
'''
    main_source = main_source.replace(marker, cancel + marker)
    marker = '    run_quantized(sim,{1,2,3},p,"recovery");'
    main_source = main_source.replace(marker, marker + '''
    for(unsigned phase=1;phase<=2;phase++) {
      sim.cancel_normalization(table,phase);
      run_quantized(sim,{1,2,3},p,"normalization_reset_recovery");
    }''')
    main = folder / 'main.cpp'
    main.write_text(main_source)
    import pyosys
    library = Path(pyosys.__file__).parent / 'share/xilinx/cells_sim.v'
    primitive = re.search(r'^module DSP48E1\b.*?^endmodule', library.read_text(), re.M | re.S).group()
    model = folder / 'dsp48e1.sv'
    model.write_text(primitive + '\n')
    result = []
    for depth, latency, fpga in ((16, 0, False), (16, 0, True), (32, 2, True), (256, 2, True)):
        label = f'depth{depth}_latency{latency}_' + ('fpga' if fpga else 'generic')
        case = folder / label
        case.mkdir(exist_ok=True)
        flags = ['-std=c++17', '-O2', '-fsanitize=undefined', '-fno-sanitize-recover=all',
                 '-DTF_LITE_DISABLE_X86_NEON', f'-DTEST_MAX_DEPTH={depth}',
                 '-I' + str(tflm_root),
                 '-I' + str(tflm_root / 'tensorflow/lite/micro/tools/make/downloads/gemmlowp')]
        options = ['-DXILINX_FPGA', str(model)] if fpga else []
        command = [verilator, '--cc', '--exe', '--build', '-j', '1', '-Wno-fatal', '--assert',
                   '--top-module', 'vector_softmax_test', '--Mdir', str(case / 'obj'),
                   f'-GMAX_DEPTH={depth}', f'-GMULTIPLIER_LATENCY={latency}',
                   '-CFLAGS', ' '.join(flags), '-LDFLAGS', '-fsanitize=undefined',
                   str(ROOT / SOURCE), str(wrapper), *options, str(main)]
        command += [str(tflm_root / 'tensorflow/lite/kernels/internal' / filename)
                    for filename in ('common.cc', 'runtime_shape.cc', 'quantization_util.cc')]
        (case / 'command.json').write_text(json.dumps(command, indent=2) + '\n')
        with (case / 'build.log').open('w') as log:
            subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        binary = case / 'obj/Vvector_softmax_test'
        run = subprocess.run([str(binary)], cwd=ROOT, capture_output=True, text=True, check=True)
        log = case / 'run.log'
        log.write_text(run.stdout + run.stderr)
        record = json.loads(run.stdout.strip().splitlines()[-1])
        record.update(multiplier_latency=latency, fpga=fpga, normalization_resets=2,
                      binary_sha256=digest(binary), log_sha256=digest(log))
        result.append(record)
        shutil.copy2(binary, case / 'Vvector_softmax_test')
        shutil.rmtree(case / 'obj')
        print(json.dumps(record), flush=True)
    return {'runs': result, 'wrapper_sha256': digest(wrapper),
            'test_cpp_sha256': digest(main), 'primitive_library_sha256': digest(library)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='9a6437f4')
    parser.add_argument('--tflm-root', type=Path, default=ROOT / 'drivers/tflm/tflm/tflite-micro')
    parser.add_argument('--verilator', default='verilator-modern')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source_hash = digest(ROOT / SOURCE)
    reference = read_rtl_source(args.reference + ':' + str(SOURCE), cwd=ROOT, text=True)
    current = (ROOT / SOURCE).read_text()
    report = {'source_sha256': source_hash, 'reference_revision': args.reference,
              'formal': formal(out, reference, current)}
    report['mapping'] = mapped(out, reference)
    (out / 'mapping_summary.json').write_text(json.dumps(report['mapping'], ensure_ascii=False, indent=2) + '\n')
    report['numeric'] = numerical(out, args.tflm_root.resolve(), args.verilator)
    if source_hash != digest(ROOT / SOURCE):
        raise RuntimeError('验证期间 RTL 内容发生变化')
    report.update(passed=True, valid_task_extra_cycles=1, dsp_remapping=False,
                  physical_lut_packing=False)
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({name: {'lut': row['resources']['logic_lut_cells'],
                            'ff': row['resources']['flip_flops'],
                            'maximum_depth': row['paths']['longest_register_path_cells'],
                            'normalization_depth': row['normalization_paths']['longest_register_path_cells']}
                      for name, row in report['mapping'].items()}, indent=2), flush=True)


if __name__ == '__main__':
    main()
