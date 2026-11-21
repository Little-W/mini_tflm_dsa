#!/usr/bin/env python3
"""证明前端配置、描述符提交与运行状态的更新事件互斥。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]


def extract(text, start, stop):
    first = text.index(start)
    return text[first:text.index(stop, first)]


def assignment(text, name):
    return re.search(r'  assign ' + re.escape(name) + r'\s*=.*?;', text, re.S).group()


PORTS = '''input logic [4:0] state_index,
 input logic rst_n,cfg_valid,cache_cfg_ready,cache_hint_pending,tile_prepared_valid,
 input logic request_pending,pred_busy,pred_cfg_busy,pred_cfg_pending,cache_cfg_pending,
 input logic[1:0]cfg_prepare_phase,address_step_phase,
 input logic[3:0]prefetch_phase,
 input logic configured,error,tile_valid,wr_ready,cache_rsp_valid,cache_rsp_error,
 input logic row_last_q,chunk_reaches_end,past_active_q,active_after_chunk,row_base_valid,geometry_tile,
 input logic coordinate_address_valid,current_coordinate_valid,tap_wrap,pad_q,ix_step_below_limit,group_end_o_equal,
 input logic commit_invalid,commit_fast,commit_word_hit,next_row_word_hit,next_tap_saved_hit,next_byte_saved_hit,channel_saved_hit,
 input logic group_shape_o_valid,p_fast_valid,
 input logic[31:0]q0,p0,decode_index,
 input logic[15:0]group_c,input_c,group_offset,dilation_w,
'''


def module(text, name):
    enum = extract(text, '  typedef enum logic [21:0]', '  (* fsm_encoding')
    cfg = extract(text, '  assign cfg_idle_groups[0]', '  assign busy =')
    wr = assignment(text, 'wr_valid') + '\n' + assignment(text, 'wr_last')
    commit = assignment(text, 'tile_capture') + '\n' + assignment(text, 'tile_commit')
    ranges = extract(text, '  always_comb begin\n    range_stream_allowed =',
                     '  assign range_update_value =')
    address = extract(text, '  assign address_stream_write =', '  assign address_update_value =')
    hit = extract(text, '  assign word_response_write =', '  always_ff')
    active = extract(text, '  assign active_update_select[0]', '  assign active_update_candidate[0]')
    cache_write = assignment(text, 'p_cache_write_enable')
    return f'''module {name} #(parameter bit REGISTER_DESCRIPTOR=1)(
{PORTS}
 output logic[20:0]result,output logic invariant);
{enum}
 logic descriptor_response_forward;
 st_t state;
 assign state=st_t'(22'b1<<state_index);
 typedef struct packed {{logic[15:0]group_c,input_c,group_offset,dilation_w;}} cfg_t;
 typedef struct packed {{logic invalid,fast,word_hit;}} tile_t;
 cfg_t c;tile_t committing_tile;
 assign c={{group_c,input_c,group_offset,dilation_w}};
 assign committing_tile={{commit_invalid,commit_fast,commit_word_hit}};
 localparam int p_saved_group_lanes=8;
 logic[2:0][5:0]cfg_idle_groups;
 logic[2:0]cfg_idle_group_clear;
 logic cfg_ready,finishing_tile,tile_ready_context,tile_ready,tile_capture,tile_commit,wr_valid,wr_last;
 logic range_stream_allowed,range_decode_write;
 logic[8:0]range_decode_value;
 wire[5:0][8:0]group_range_next='0;
 logic[3:0]range_update_select;
 logic address_stream_write,address_column_advance,address_linear_tap;
 logic[4:0]address_update_select,word_hit_update_select,word_hit_candidate;
 logic word_response_write,word_hit_write_enable,word_hit_write_value;
 logic[2:0]active_update_select;
 logic p_cache_write_enable;
{cfg}
{wr}
{commit}
{ranges}
{address}
{hit}
{active}
{cache_write}
 assign result={{range_update_select,address_update_select,word_hit_update_select,
    word_hit_write_enable,word_hit_write_value,active_update_select,
    address_stream_write,p_cache_write_enable}};
 assign invariant=!(cfg_valid&&cfg_ready&&wr_valid)&&
    !(cfg_valid&&cfg_ready&&tile_commit)&&
    !(cfg_valid&&cfg_ready&&range_decode_write)&&
    !(tile_commit&&range_decode_write)&&!(wr_valid&&range_decode_write)&&
    !(tile_commit&&state[$clog2(ADDRESS_CHANNEL)])&&
    (!REGISTER_DESCRIPTOR||!(tile_commit&&wr_valid));
endmodule
'''


def run(name, source, commands, out):
    sv, ys, log = (out / (name + extension) for extension in ('.sv', '.ys', '.log'))
    sv.write_text(source)
    ys.write_text('read_slang --top proof ' + shlex.quote(str(sv)) +
                  '\nprep -top proof -flatten\ncheck -assert\n' + commands)
    with log.open('w') as stream:
        result = subprocess.run([sys.executable, str(ROOT/'scripts/fpga/open_fpga_synth.py'),
                                 '--worker', str(ys)], stdout=stream, stderr=subprocess.STDOUT,
                                timeout=180)
    if result.returncode or 'SUCCESS!' not in log.read_text():
        raise RuntimeError(str(log))
    return {'name': name, 'passed': True,
            'source_sha256': hashlib.sha256(sv.read_bytes()).hexdigest(),
            'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    paths = [root/'rtl/npu/conv/conv_im2col_frontend.sv'
             for root in (args.source_root, args.reference_root)]
    current, reference = [path.read_text() for path in paths]
    hashes = [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]
    rows = []

    # 对所有状态赋值的右侧逐项检查；未赋值分支保存当前状态。
    enum = extract(current, '  typedef enum logic [21:0]', '  (* fsm_encoding')
    encodings = dict((name, int(value, 16)) for name, value in
                     re.findall(r'(\w+)\s*=\s*22\x27h([0-9a-fA-F]+)', enum))
    if len(encodings) != 22 or any(value == 0 or value & (value-1) for value in encodings.values()):
        raise RuntimeError('State encoding')
    if re.search(r'\bstate\s*\[.*?\]\s*(?:<=|=)', current):
        raise RuntimeError('Partial state assignment')
    assignments = re.findall(r'\bstate\s*<=\s*([^;]+);', current)
    paired_assignments = re.findall(
        r'\{word_output_q,\s*state\}\s*<=\s*\{state_uses_word\((.*?)\),\s*(.*?)\};',
        current)
    for class_value, state_value in paired_assignments:
        if re.sub(r'\s+', '', class_value) != re.sub(r'\s+', '', state_value):
            raise RuntimeError('State output class assignment')
    if paired_assignments:
        if assignments:
            raise RuntimeError('Mixed state assignment forms')
        assignments = [state_value for _, state_value in paired_assignments]
        if len(paired_assignments) != len(re.findall(r'\{word_output_q,\s*state\}\s*<=', current)):
            raise RuntimeError('State output class coverage')
    if not assignments or assignments[0] != 'IDLE':
        raise RuntimeError('State reset')
    for rhs in assignments:
        unknown = set(re.findall(r'\b[A-Za-z_]\w*\b', rhs)) - set(encodings) - {'cache_req_ready', 'next_row_request'}
        if unknown:
            raise RuntimeError(('State assignment', rhs, unknown))
    candidates = sorted(set(assignments))
    declarations = '\n'.join(f'wire[21:0]candidate_{i}={rhs};' for i,rhs in enumerate(candidates))
    conditions = ' && '.join(f'(candidate_{i}!=0 && (candidate_{i}&(candidate_{i}-22\x27d1))==0)'
                             for i in range(len(candidates)))
    rows.append(run('state_assignment_values',
                    'module proof(input logic cache_req_ready,next_row_request,output logic equivalent);\n'+
                    enum+declarations+'\nassign equivalent='+conditions+';\nendmodule\n',
                    'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n', args.out))

    pair = module(current, 'current') + module(reference, 'reference')
    for registered in (0, 1):
        wrapper = f'''module proof({PORTS}output logic equivalent);
 logic[20:0]current_result,reference_result;
 logic current_invariant,reference_invariant;
 current #(.REGISTER_DESCRIPTOR({registered}))u_current(.*,.result(current_result),.invariant(current_invariant));
 reference #(.REGISTER_DESCRIPTOR({registered}))u_reference(.*,.result(reference_result),.invariant(reference_invariant));
 assign equivalent=current_result==reference_result&&current_invariant&&reference_invariant;
endmodule
'''
        rows.append(run('event_selection_register'+str(registered), pair+wrapper,
                        'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n', args.out))
    if hashes != [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]:
        raise RuntimeError('Source changed during verification')
    report = {'passed': True, 'runs': rows, 'source_sha256': hashes[0],
              'reference_sha256': hashes[1], 'state_assignment_count': len(assignments),
              'distinct_state_assignment_values': candidates,
              'state_invariant': 'Reset IDLE; every state assignment is one-hot; unassigned cycles hold state.',
              'event_input_constraints': [],
              'event_state_encoding': 'One-hot or zero from unrestricted five-bit index',
              'descriptor_modes': [0, 1], 'compared_event_bits': 21}
    (args.out/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
    print('FRONTEND_EVENT_DOMAINS_PASS', len(rows), args.out/'summary.json')


if __name__ == '__main__':
    main()
