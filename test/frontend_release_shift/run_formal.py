#!/usr/bin/env python3
"""证明行释放移位跨越既有缓存接收寄存级时的数值和状态关系。"""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import resource
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('release_prepare_formal',
    ROOT / 'test/frontend_release_prepare/run_formal.py')
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)
SOURCE, CACHE = prepare.SOURCE, prepare.CACHE
REFERENCE = '1df45da1'
DECODE_BEGIN = '  assign retire_decode_input[0] = work_request.retire;\n'
DECODE_END = '  // 地址范围结果随接收描述保存，出队时只选择已保存的一位状态。\n'


def source_pair(reference):
    result = {}
    for path in (SOURCE, CACHE):
        result[path] = dict(reference=prepare.read_rtl_source(reference + ':' + path, cwd=ROOT, text=True),
                            current=(ROOT / path).read_text())
    old, new = (result[SOURCE][label] for label in ('reference', 'current'))
    old_body = old[old.index(prepare.BEGIN):old.index(prepare.END)]
    new_body = new[new.index(prepare.BEGIN):new.index(prepare.END)]
    if old_body[:old_body.index(prepare.RUNTIME)] != new_body[:new_body.index(prepare.RUNTIME)]:
        raise RuntimeError('已证明的配置准备寄存逻辑发生变化')
    normalized = new.replace(new_body, old_body, 1).replace(
        '.DMA_MAX_BYTES(DMA_MAX_BYTES),\n    .p_defer_retire_shift(CACHE_POLICY == 3)) u_cache',
        '.DMA_MAX_BYTES(DMA_MAX_BYTES)) u_cache', 1)
    if normalized != old:
        raise RuntimeError('前端配置准备和寄存边界以外存在变化')
    old_cache, new_cache = (result[CACHE][label] for label in ('reference', 'current'))
    decode = new_cache[new_cache.index(DECODE_BEGIN):new_cache.index(DECODE_END)]
    normalized = new_cache.replace(decode, '', 1).replace(
        '  parameter int TAGW=32-LB-SI,\n  parameter bit p_defer_retire_shift=1\'b0',
        '  parameter int TAGW=32-LB-SI').replace(
        '.DMA_MAX_BYTES(DMA_MAX_BYTES),\n      .p_defer_retire_shift(p_defer_retire_shift)) u_window',
        '.DMA_MAX_BYTES(DMA_MAX_BYTES)) u_window', 1).replace(
        '  logic [1:0][31:0] retire_decode_input, retire_decode_output;\n', '', 1).replace(
        'retire_decode_output[0]', 'work_request.retire').replace(
        'retire_decode_output[1]', 'offer_retire_q')
    if normalized != old_cache:
        raise RuntimeError('缓存存储、控制或解码范围以外存在变化')
    return result, dict(reference=old_body, current=new_body)


def default_equivalence(folder, contents, parameters, defines):
    folder.mkdir(parents=True, exist_ok=True)
    commands = []
    for label, text in contents[CACHE].items():
        rtl = folder / (label + '.sv')
        rtl.write_text(text)
        options = ['-j', '1', '--top', 'conv_windowed_cache', *defines,
                   *(f'-G{name}={value}' for name, value in parameters.items()), str(rtl),
                   *(str(ROOT / path) for path in ('rtl/npu/dma/cache/conv_sdp_ram.sv',
                     'rtl/npu/conv/conv_axi_span_reader.sv', 'rtl/common/regfile.v'))]
        commands += ['read_slang ' + shlex.join(options),
            'prep -top conv_windowed_cache -flatten', 'memory_map', 'async2sync', 'opt_clean',
            f'rename conv_windowed_cache {label}', f'design -stash {label}']
    commands += ['design -copy-from reference -as reference reference',
        'design -copy-from current -as current current', 'equiv_make reference current equivalent',
        'hierarchy -top equivalent', 'opt_merge', 'equiv_simple -short -seq 1', 'opt_clean',
        'equiv_induct -seq 2', 'equiv_status -assert']
    script, log = folder / 'proof.ys', folder / 'proof.log'
    script.write_text('\n'.join(commands) + '\n')

    def limit_memory():
        resource.setrlimit(resource.RLIMIT_AS, (600 << 20, 600 << 20))

    with log.open('w') as stream:
        subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
            '--worker', str(script)], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
            preexec_fn=limit_memory, check=True, timeout=180)
    text = log.read_text()
    matches = re.findall(r'Of those cells (\d+) are proven and (\d+) are unproven', text)
    if not matches or int(matches[-1][1]) or 'Equivalence successfully proven' not in text:
        raise RuntimeError('默认参数的完整缓存等价未完成')
    return dict(passed=True, equivalent_bits=int(matches[-1][0]),
                script_sha256=prepare.digest(script.read_bytes()), log_sha256=prepare.digest(text))


def decoder(cache):
    body = cache[cache.index(DECODE_BEGIN):cache.index(DECODE_END)]
    body = body.replace('      logic [31:0] shifted_value;\n', '''      logic [31:0] shifted_value;
      if ($bits(row_value) != 18 || $bits(shift) != 4 || $bits(disabled) != 1 ||
          $bits(unused_padding) != 9 || $bits(retire_decode_input[retire_port]) != 32) begin : g_width_check
        release_metadata_width_must_be_32 u_invalid_width();
      end
''', 1)
    return '''module release_decoder(input logic [63:0] i_value, output logic [63:0] o_value);
  localparam bit p_defer_retire_shift = 1'b1;
  localparam logic [31:0] INF = 32'hffff_ffff;
  typedef struct packed {logic [31:0] retire;} request_t;
  request_t work_request;
  logic [31:0] offer_retire_q;
  logic [1:0][31:0] retire_decode_input, retire_decode_output;
  assign work_request.retire = i_value[31:0];
  assign offer_retire_q = i_value[63:32];
''' + body + '''
  assign o_value = retire_decode_output;
endmodule
'''


def cache_properties(cache):
    begin = cache.index('    lookup_read_request = request_count==0 ?')
    end = cache.index('    lookup_read_set =', begin)
    selector = cache[begin:end]

    def selected(suffix):
        value = selector
        for before, after in (('lookup_read_request', 'proof_lookup_' + suffix),
                              ('incoming_request', 'proof_incoming_' + suffix),
                              ('request_queue', 'proof_queue_' + suffix)):
            value = value.replace(before, after)
        return value

    return '''
  logic proof_reset_seen = 1'b0;
  logic [31:0] proof_incoming_value, proof_lookup_value, proof_work_value;
  logic [31:0] proof_queue_value [DEMAND_DEPTH];
  logic proof_queue_known [DEMAND_DEPTH];
  logic proof_incoming_known, proof_lookup_known, proof_work_known;
  logic [31:0] proof_prefetch_value, proof_offer_value, proof_demand_value;
  logic proof_offer_known;
  logic [DEMAND_DEPTH-1:0] proof_queue_equal, proof_slot_clean;
  logic proof_pointers, proof_work_equal, proof_offer_equal, proof_consumption;
  assign proof_incoming_value = req_window_retire[22] ? INF :
      ({14'd0, req_window_retire[17:0]} >> req_window_retire[21:18]);
  assign proof_prefetch_value = prefetch_window_retire[22] ? INF :
      ({14'd0, prefetch_window_retire[17:0]} >> prefetch_window_retire[21:18]);
  assign proof_incoming_known = 1'b1;
  always_comb begin
''' + selected('value') + selected('known') + '''  end
  always_ff @(posedge clk) begin
    if (!rst_n) proof_reset_seen <= 1'b1;
    proof_work_value <= proof_lookup_value;
    proof_work_known <= proof_lookup_known;
    if (!rst_n || (cfg_valid && cfg_ready)) begin
      for (int slot = 0; slot < DEMAND_DEPTH; slot++) proof_queue_known[slot] <= 1'b0;
    end else if (request_push) begin
      proof_queue_value[request_tail] <= proof_incoming_value;
      proof_queue_known[request_tail] <= 1'b1;
    end
    if (!rst_n) proof_offer_known <= 1'b0;
    else if (offer_capture) proof_offer_known <= 1'b1;
    if (offer_capture) proof_offer_value <= proof_prefetch_value;
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) proof_demand_value <= INF;
    else if (!(cfg_valid && cfg_ready) && req_fire) proof_demand_value <= proof_work_value;
  end
  for (genvar slot = 0; slot < DEMAND_DEPTH; slot++) begin : g_proof_slot
    logic [DQ_AW-1:0] distance_from_head;
    logic [31:0] stored_value;
    assign stored_value = request_queue[slot].retire[22] ? INF :
        ({14'd0, request_queue[slot].retire[17:0]} >> request_queue[slot].retire[21:18]);
    assign distance_from_head = DEMAND_DEPTH == 1 ? DQ_AW'(0) : DQ_AW'(slot) - request_head;
    assign proof_slot_clean[slot] = DQ_CW'(distance_from_head) >= request_count ||
        proof_queue_known[slot];
    assign proof_queue_equal[slot] = !proof_queue_known[slot] || stored_value == proof_queue_value[slot];
  end
  assign proof_pointers = DEMAND_DEPTH == 1 ? (request_head == 0 && request_tail == 0) :
      request_tail == DQ_AW'(request_head + DQ_AW'(request_count));
  assign proof_work_equal = (!work_valid || proof_work_known) &&
      (!proof_work_known || retire_decode_output[0] == proof_work_value);
  assign proof_offer_equal = (!offer_valid || proof_offer_known) &&
      (!proof_offer_known || (retire_decode_output[1] == proof_offer_value && offer_next_retire_q == INF));
  assign proof_consumption = (!req_fire || (proof_work_known && retire_decode_output[0] == proof_work_value)) &&
      (!metadata_hit || metadata_hit_rank == (windowed_q ? proof_work_value : hint_next)) &&
      (!pf_push || pf_offer_retire == (offer_select_next_q ? INF : proof_offer_value)) &&
      demand_retire == proof_demand_value;
  assign proof_ok = !proof_reset_seen || (proof_pointers && (&proof_slot_clean) &&
      (&proof_queue_equal) && proof_work_equal && proof_offer_equal && proof_consumption);
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-ref', default=REFERENCE)
    parser.add_argument('--cache-only', action='store_true')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    contents, bodies = source_pair(args.reference_ref)
    cache = contents[CACHE]['current']
    report = dict(reference_commit=subprocess.check_output(['git', 'rev-parse', args.reference_ref],
        cwd=ROOT, text=True).strip(), source_sha256={path: {label: prepare.digest(text)
        for label, text in pair.items()} for path, pair in contents.items()},
        inputs_constrained=False, unchanged_configuration_preparation=True,
        unchanged_cache_storage_and_control=True, proofs=[])

    def save():
        report['maximum_resident_kib'] = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')

    if not args.cache_only:
        folder = out / 'arithmetic'
        folder.mkdir(exist_ok=True)
        rtl = folder / 'proof.sv'
        runtime = {label: body[body.index(prepare.RUNTIME):] for label, body in bodies.items()}
        text = prepare.calculation('release_reference', prepare.COEFFICIENTS + runtime['reference']) + \
            prepare.calculation('release_current', prepare.COEFFICIENTS + runtime['current']) + decoder(cache) + '''
module release_proof(input logic [163:0] i_value, output logic o_equal);
  logic [63:0] reference_value, metadata, current_value;
  release_reference u_reference(.i_value(i_value), .o_value(reference_value));
  release_current u_current(.i_value(i_value), .o_value(metadata));
  release_decoder u_decode(.i_value(metadata), .o_value(current_value));
  assign o_equal = reference_value == current_value && metadata[31:23] == 0 && metadata[63:55] == 0;
endmodule
'''
        rtl.write_text(text)
        result = prepare.worker(folder, f'read_slang -j 1 --top release_proof {rtl}\n'
            'prep -top release_proof -flatten\n'
            'sat -verify -prove o_equal 1 -show-inputs -show-outputs -timeout 60\n')
        report['proofs'].append(dict(name='encoded_arithmetic', input_bits=164, output_bits=64,
            rtl_sha256=prepare.digest(text), **result))
        save()
        print('encoded_arithmetic: PASS', flush=True)

    for mode, defines in {'generic': ['-D', 'ASIC_SYNTHESIS=1'],
            'fpga': ['-D', 'SYNTHESIS=1', '-D', 'XILINX_FPGA=1', '-D', 'YOSYS=1', '-D', 'VERIFIC=1']}.items():
        for depth, ways, width in ((1, 1, 32), (2, 2, 64), (4, 2, 32), (8, 1, 64)):
            name = f'{mode}_cache_depth{depth}'
            folder = out / name
            folder.mkdir(exist_ok=True)
            rtl = folder / 'conv_read_cache.sv'
            rtl.write_text(prepare.instrument(cache, 'conv_windowed_cache', cache_properties(cache)))
            dependencies = ['rtl/npu/dma/cache/conv_sdp_ram.sv',
                            'rtl/npu/conv/conv_axi_span_reader.sv', 'rtl/common/regfile.v']
            cut_inputs = ['cfg_ready', 'req_ready', 'work_ready', 'fg_state', 'lookup_range', 'lookup_hit',
                          'offer_capture', 'offer_checked', 'incoming_lookup_ready', 'offer_duplicate_q',
                          'offer_in_range']
            parameters = dict(SETS=2, WAYS=ways, BUS_WIDTH=width, DEMAND_DEPTH=depth,
                              p_defer_retire_shift=1)
            result = prepare.worker(folder, prepare.state_script('conv_windowed_cache', rtl,
                dependencies, parameters, defines, cut_inputs))
            report['proofs'].append(dict(name=name, parameters=parameters, mode=mode,
                children_are_free_inputs=True, free_internal_inputs=cut_inputs,
                rtl_sha256=prepare.digest(rtl.read_bytes()), **result))
            save()
            print(name + ': PASS', flush=True)
        if not args.cache_only:
            for depth, ways, width in ((1, 1, 32), (4, 2, 64)):
                name = f'{mode}_default_depth{depth}'
                parameters = dict(SETS=2, WAYS=ways, LINE_BYTES=16, BUS_WIDTH=width, DEMAND_DEPTH=depth)
                result = default_equivalence(out / name, contents, parameters, defines)
                report['proofs'].append(dict(name=name, parameters=parameters, mode=mode,
                    every_state_and_public_output=True, **result))
                save()
                print(name + ': PASS', flush=True)
    if any(prepare.digest((ROOT / path).read_bytes()) != pair['current']
           for path, pair in report['source_sha256'].items()):
        raise RuntimeError('Source changed during proof')
    report['passed'] = True
    report['proof_count'] = len(report['proofs'])
    save()
    print('RELEASE_SHIFT_FORMAL_PASS count=' + str(report['proof_count']), flush=True)


if __name__ == '__main__':
    main()
