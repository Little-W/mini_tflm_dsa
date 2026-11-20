#!/usr/bin/env python3
"""证明行释放运算、配置准备状态与缓存有效请求之间的关系。"""
import argparse
import hashlib
import json
from pathlib import Path
import resource
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'rtl/npu/conv/conv_im2col_frontend.sv'
CACHE = 'rtl/npu/dma/cache/conv_read_cache.sv'
REFERENCE = '2297cb12deac56b476f9a2a656da4038a9d8a75c'
sys.path.insert(0, str(ROOT / 'test'))
from rtl_reference import read_rtl_source

OLD_BEGIN = '  // 请求与预取各保留一个退休行号计算端口，两个预取阶段按原有采样周期共用端口。\n'
BEGIN = '  // 配置准备阶段保存行偏移和限幅阈值，运行时的加法与范围判断并行。\n'
RUNTIME = '  // 请求和预取各共用一个计算端口，全部结果仍在原请求接收周期使用。\n'
END = '  // 位置解码使用已接受的描述符，快速请求的资格条件保证输入位置与保存位置相同。\n'
DATAPATH_INPUTS = (
    'cfg_ok cfg_basic_valid incoming_fast incoming_padding tile_rows_in_range tile_q_before_end '
    'ix iy pad_q word_valid addr word_addr geometry_tile col_idx q_current chunk_count row_last_q '
    'chunk_reaches_end row_coordinate_valid current_coordinate_valid coordinate_address_valid '
    'row_base_valid p_fast_valid incoming_q_fast p_cache_valid col_remaining active_remaining '
    'group_remaining').split()
DEPENDENCIES = [
    'rtl/npu/conv/conv_im2col_pkg.sv', CACHE,
    'rtl/npu/dma/cache/conv_sdp_ram.sv', 'rtl/npu/dma/cache/conv_next_use_predictor.sv',
    'rtl/npu/conv/conv_axi_span_reader.sv', 'rtl/common/onehot_check.sv',
    'rtl/common/add_equal.sv', 'rtl/common/add3_equal.sv', 'rtl/common/regfile.v']


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()


def sources(reference):
    result = {'reference': read_rtl_source(reference + ':' + SOURCE, cwd=ROOT, text=True),
              'current': (ROOT / SOURCE).read_text()}
    bodies = {label: content[content.index(OLD_BEGIN if label == 'reference' else BEGIN):
                            content.index(END)] for label, content in result.items()}
    if result['current'].replace(bodies['current'], bodies['reference'], 1) != result['reference']:
        raise RuntimeError('行释放计算以外存在源码变化，需要扩展证明范围')
    return result, bodies


def input_declarations(input_name):
    return '''  logic [15:0] request_y_q, pad_top, retire_last_row_q;
  logic [34:0] iy, pfa_y, pf0_y;
  logic request_pending, retire_enabled_q, short_pixel_q;
  logic [3:0] retire_shift_q, prefetch_phase;
  typedef struct packed {logic [15:0] pad_top;} config_t;
  config_t c;
  logic [1:0][15:0] retirement_input;
  logic [1:0][31:0] retirement_result;
  logic [31:0] request_retire;
  assign {request_y_q, pad_top, retire_last_row_q, iy, pfa_y, pf0_y,
      request_pending, retire_enabled_q, short_pixel_q, retire_shift_q,
      prefetch_phase} = ''' + input_name + ''';
  assign c.pad_top = pad_top;
'''


def calculation(name, body):
    return f'''module {name}(input logic [163:0] i_value, output logic [63:0] o_value);
''' + input_declarations('i_value') + body + '''
  assign o_value = retirement_result;
endmodule
'''


COEFFICIENTS = '''  logic [16:0] retire_bias_q;
  logic [15:0] retire_compare_q;
  logic retire_all_bounded_q, retire_no_bound_q, prefetch_retire_pfa_q;
  logic signed [31:0] limit_value;
  assign retire_bias_q = {1'b0, c.pad_top} +
      (short_pixel_q ? (17'd1 << retire_shift_q) : 17'd0);
  assign limit_value = $signed({16'd0, retire_last_row_q} << retire_shift_q) -
      $signed({16'd0, c.pad_top});
  assign retire_compare_q = limit_value[15:0];
  assign retire_all_bounded_q = limit_value[31];
  assign retire_no_bound_q = !limit_value[31] && (|limit_value[30:16]);
  assign prefetch_retire_pfa_q = prefetch_phase == 4'd3;
'''


def instrument(content, module, assertions):
    begin = content.index('module ' + module)
    header = content.index(');', begin)
    content = content[:header] + ',\n  output logic proof_ok\n' + content[header:]
    end = content.index('endmodule', begin)
    return content[:end] + assertions + '\n' + content[end:]


PRODUCER_PROPERTIES = '''  logic [16:0] proof_bias;
  logic [30:0] proof_scaled;
  logic signed [31:0] proof_limit;
  logic proof_low_ready, proof_coefficients, proof_preparation, proof_selection;
  logic proof_reset_seen = 1'b0;
  always_ff @(posedge clk) if (!rst_n) proof_reset_seen <= 1'b1;
  assign proof_bias = {1'b0, c.pad_top} +
      (short_pixel_q ? (17'd1 << retire_shift_q) : 17'd0);
  assign proof_scaled = {15'd0, retire_last_row_q} << retire_shift_q;
  assign proof_limit = $signed({1'b0, proof_scaled}) - $signed({16'd0, c.pad_top});
  assign proof_low_ready = cfg_prepare_phase != 2'd2 ||
    (retire_bias_q == proof_bias && retire_compare_q == proof_scaled[15:0] &&
     retire_all_bounded_q == !(|proof_scaled[30:16]) &&
     retire_no_bound_q == (|proof_scaled[30:17]));
  assign proof_coefficients = !retire_enabled_q || cfg_prepare_phase != 2'd0 ||
    (retire_bias_q == proof_bias && retire_compare_q == proof_limit[15:0] &&
     retire_all_bounded_q == proof_limit[31] &&
     retire_no_bound_q == (!proof_limit[31] && (|proof_limit[30:16])));
  assign proof_preparation = cfg_prepare_phase != 2'd3 &&
    (cfg_prepare_phase == 2'd0 || (state == IDLE && !request_pending &&
      prefetch_phase == 0 && !configured && !cache_port_valid));
  assign proof_selection = prefetch_retire_pfa_q == (prefetch_phase == 4'd3);
'''


def cache_properties(content):
    begin = content.index('    lookup_read_request = request_count==0 ?')
    end = content.index('    lookup_read_set =', begin)
    selector = content[begin:end]
    for old, new in (('lookup_read_request', 'proof_lookup_tainted'),
                     ('incoming_request', 'proof_incoming_tainted'),
                     ('request_queue', 'proof_queue_tainted')):
        selector = selector.replace(old, new)
    return '''  logic proof_incoming_tainted, proof_lookup_tainted, proof_work_tainted;
  logic proof_queue_tainted [DEMAND_DEPTH];
  logic proof_reset_seen = 1'b0;
  assign proof_incoming_tainted = !req_valid;
  always_ff @(posedge clk) begin
    if (!rst_n) proof_reset_seen <= 1'b1;
    proof_work_tainted <= proof_lookup_tainted;
    if (!rst_n || (cfg_valid && cfg_ready)) begin
      for (int entry = 0; entry < DEMAND_DEPTH; entry++)
        proof_queue_tainted[entry] <= 1'b1;
    end else if (request_push) begin
      proof_queue_tainted[request_tail] <= proof_incoming_tainted;
    end
  end
  always_comb begin
''' + selector + '''  end
  logic [DEMAND_DEPTH-1:0] proof_slot_clean;
  logic proof_pointers;
  for (genvar slot = 0; slot < DEMAND_DEPTH; slot++) begin : g_proof_slot
    logic [DQ_AW-1:0] distance_from_head;
    assign distance_from_head = DEMAND_DEPTH == 1 ? DQ_AW'(0) :
        DQ_AW'(slot) - request_head;
    assign proof_slot_clean[slot] = DQ_CW'(distance_from_head) >= request_count ||
        !proof_queue_tainted[slot];
  end
  assign proof_pointers = DEMAND_DEPTH == 1 ? (request_head == 0 && request_tail == 0) :
      request_tail == DQ_AW'(request_head + DQ_AW'(request_count));
  assign proof_ok = !proof_reset_seen ||
      (proof_pointers && (&proof_slot_clean) && (!work_valid || !proof_work_tainted));
'''


def worker(folder, text):
    folder.mkdir(parents=True, exist_ok=True)
    script, log = folder / 'proof.ys', folder / 'proof.log'
    script.write_text(text)

    def limit_memory():
        resource.setrlimit(resource.RLIMIT_AS, (600 << 20, 600 << 20))

    with log.open('w') as stream:
        subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                        '--worker', str(script)], cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, check=True, preexec_fn=limit_memory)
    result = log.read_text()
    success = ('SAT proof finished - no model found: SUCCESS!' in result or
               'Induction step proven: SUCCESS!' in result)
    if not success:
        raise RuntimeError('形式证明未完成: ' + str(log))
    return dict(passed=True, script_sha256=digest(text), log_sha256=digest(result),
                unbounded_induction='Induction step proven: SUCCESS!' in result)


def state_script(top, rtl, dependencies, parameters, defines, cut_inputs, cut_multipliers=False):
    options = ['-j', '1', '--keep-hierarchy', '--top', top, *defines,
               *(f'-G{name}={value}' for name, value in parameters.items()),
               *(str(ROOT / path) for path in dependencies), str(rtl)]
    lines = ['read_slang ' + shlex.join(options), f'hierarchy -top {top}', 'proc',
             f'expose -evert {top}']
    if cut_inputs:
        lines.append('expose -input ' + ' '.join(f'{top}/w:{name}' for name in cut_inputs))
    if cut_multipliers:
        lines.append(f'cutpoint {top}/t:$mul')
    lines += [f'delete -output {top}/w:*', f'expose {top}/w:proof_ok',
              f'hierarchy -top {top}', f'prep -top {top} -flatten', 'memory_map',
              'async2sync', 'opt -full', 'stat',
              'sat -verify -seq 1 -tempinduct -maxsteps 8 -prove proof_ok 1 -timeout 30']
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-ref', default=REFERENCE)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    content, bodies = sources(args.reference_ref)
    cache = (ROOT / CACHE).read_text()
    report = dict(reference_commit=subprocess.check_output(
        ['git', 'rev-parse', args.reference_ref], cwd=ROOT, text=True).strip(),
        source_sha256={name: digest(text) for name, text in content.items()},
        unchanged_outside_release=True, inputs_constrained=False,
        dependency_sha256={path: digest((ROOT / path).read_bytes()) for path in DEPENDENCIES},
        proofs=[])

    def save():
        report['maximum_resident_kib'] = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')

    runtime = bodies['current'][bodies['current'].index(RUNTIME):]
    arithmetic = calculation('release_reference', bodies['reference']) + \
        calculation('release_current', COEFFICIENTS + runtime) + '''
module release_proof(input logic [163:0] i_value, output logic o_equal);
  logic [63:0] reference_value, current_value;
  release_reference u_reference(.i_value(i_value), .o_value(reference_value));
  release_current u_current(.i_value(i_value), .o_value(current_value));
  assign o_equal = reference_value == current_value;
endmodule
'''
    adder = runtime[runtime.index('    logic [9:0] row_sum_low;'):
                    runtime.index('    assign shifted_row =')]
    adder = adder.replace('retirement_input[row_port]', 'i_y').replace('retire_bias_q', 'i_bias')
    adder = '''module addition_proof(input logic [15:0] i_y, input logic [16:0] i_bias,
    output logic o_equal);
  logic [17:0] biased_row;
''' + adder + '''
  assign o_equal = biased_row == ({2'b0, i_y} + {1'b0, i_bias});
endmodule
'''
    for name, rtl_text, bits_in, bits_out in (('release', arithmetic, 164, 64),
                                              ('addition', adder, 33, 18)):
        folder = out / name
        folder.mkdir(exist_ok=True)
        rtl = folder / 'proof.sv'
        rtl.write_text(rtl_text)
        result = worker(folder, f'read_slang -j 1 --top {name}_proof {rtl}\n'
            f'prep -top {name}_proof -flatten\n'
            'sat -verify -prove o_equal 1 -show-inputs -show-outputs -timeout 60\n')
        report['proofs'].append(dict(name=name, input_bits=bits_in, output_bits=bits_out,
            rtl_sha256=digest(rtl_text), **result))
        save()
        print(name + ': PASS', flush=True)

    profiles = [dict(LANES=1, BUS_WIDTH=32, CACHE_SETS=2, LINE_BYTES=8, CACHE_POLICY=0),
                dict(LANES=4, BUS_WIDTH=64, CACHE_SETS=8, LINE_BYTES=16, CACHE_POLICY=3),
                dict(LANES=4, BUS_WIDTH=64, CACHE_SETS=128, LINE_BYTES=16, CACHE_POLICY=3)]
    modes = {'generic': ['-D', 'ASIC_SYNTHESIS=1'],
             'fpga': ['-D', 'SYNTHESIS=1', '-D', 'XILINX_FPGA=1', '-D', 'YOSYS=1', '-D', 'VERIFIC=1']}
    for mode, defines in modes.items():
        for index, parameters in enumerate(profiles):
            for property_name in ('coefficients', 'admission'):
                name = f'{mode}_{property_name}_{index}'
                folder = out / name
                folder.mkdir(exist_ok=True)
                condition = ('proof_low_ready && proof_coefficients && proof_selection'
                             if property_name == 'coefficients' else 'proof_preparation')
                properties = PRODUCER_PROPERTIES + \
                    f'  assign proof_ok = !proof_reset_seen || ({condition});\n'
                rtl = folder / 'conv_im2col_frontend.sv'
                rtl.write_text(instrument(content['current'], 'conv_im2col_frontend', properties))
                cut_inputs = DATAPATH_INPUTS + (['cfg_ready', 'cache_port_valid']
                                               if property_name == 'coefficients' else [])
                result = worker(folder, state_script('conv_im2col_frontend', rtl,
                    DEPENDENCIES, parameters, defines, cut_inputs, property_name == 'admission'))
                report['proofs'].append(dict(name=name, parameters=parameters, mode=mode,
                    children_are_free_inputs=True, free_internal_inputs=cut_inputs,
                    multipliers_are_free_inputs=property_name == 'admission',
                    rtl_sha256=digest(rtl.read_bytes()), **result))
                save()
                print(name + ': PASS', flush=True)

        for depth, ways, width in ((1, 1, 32), (2, 2, 64), (4, 2, 64), (8, 1, 32)):
            name = f'{mode}_cache_depth{depth}'
            folder = out / name
            folder.mkdir(exist_ok=True)
            rtl = folder / 'conv_read_cache.sv'
            rtl.write_text(instrument(cache, 'conv_windowed_cache', cache_properties(cache)))
            dependencies = ['rtl/npu/dma/cache/conv_sdp_ram.sv',
                            'rtl/npu/conv/conv_axi_span_reader.sv', 'rtl/common/regfile.v']
            cut_inputs = ['cfg_ready', 'req_ready', 'work_ready', 'fg_state']
            parameters = dict(SETS=2, WAYS=ways, BUS_WIDTH=width, DEMAND_DEPTH=depth)
            result = worker(folder, state_script('conv_windowed_cache', rtl, dependencies,
                                                parameters, defines, cut_inputs))
            report['proofs'].append(dict(name=name, parameters=parameters, mode=mode,
                children_are_free_inputs=True, free_internal_inputs=cut_inputs,
                rtl_sha256=digest(rtl.read_bytes()), **result))
            save()
            print(name + ': PASS', flush=True)
    if digest((ROOT / SOURCE).read_bytes()) != report['source_sha256']['current']:
        raise RuntimeError('Source changed during proof')
    report['passed'] = True
    report['proof_count'] = len(report['proofs'])
    save()
    print('RELEASE_PREPARE_FORMAL_PASS count=' + str(report['proof_count']), flush=True)


if __name__ == '__main__':
    main()
