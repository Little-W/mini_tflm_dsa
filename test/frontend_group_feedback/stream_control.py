#!/usr/bin/env python3
"""验证前端流状态、字内范围与范围保存资格。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'test'))
from rtl_reference import read_rtl_source
sys.path.insert(0, str(ROOT / 'test/frontend_pipeline'))
from source_sections import read_module

SOURCE = 'rtl/npu/conv/conv_im2col_frontend.sv'

def section(source: str, first: str, last: str) -> str:
    begin = source.index(first)
    return source[begin:source.index(last, begin)]


def states(source: str) -> str:
    declaration = re.search(r'  typedef enum logic \[(\d+):0\] \{', source)
    width = declaration.group(1)
    block = re.search(r'  typedef enum logic \[\d+:0\] \{.*?  \} st_t;', source, re.S)[0]
    return block.replace(declaration.group(0),
        f'typedef logic [{width}:0] st_t;\nlocalparam logic [{width}:0] ').replace('  } st_t;', ';')


def word_unit(source: str) -> str:
    if 'assign next_available[byte_index] = tile_commit ?' in source:
        body = re.search(r'      assign next_available\[byte_index\] = tile_commit \?.*?;',
                         source, re.S).group(0)
        body = body.replace('next_available[byte_index]', 'actual_value[byte_index]')
        body = body.replace('state[$clog2(ADDRESS_CHANNEL)]', 'address_channel')
        return '''module comparison #(parameter int p_word_shift=3,p_cache_read_bytes=1<<p_word_shift)(
input logic[4:0][p_word_shift-1:0] source_low,
input logic commit_fast,address_channel,address_stream_write,chunk_reaches_end,
 row_last_q,row_base_valid,geometry_tile,past_active_q,active_after_chunk,
 group_end_o_equal,coordinate_address_valid,address_linear_tap,
output logic equivalent,
output logic[p_cache_read_bytes-1:0] reference_value,actual_value
);
logic[4:0] address_update_select;
logic[p_cache_read_bytes-1:0][4:0] source_available;
logic tile_commit,legal_context;
assign tile_commit=commit_fast;
assign legal_context=!(commit_fast&&(address_channel||address_stream_write))&&
 !(address_channel&&address_stream_write)&&!(address_linear_tap&&coordinate_address_valid);
assign address_update_select[0]=commit_fast;
assign address_update_select[1]=address_stream_write&&chunk_reaches_end&&!row_last_q&&row_base_valid&&!geometry_tile;
assign address_update_select[2]=address_stream_write&&!chunk_reaches_end&&!past_active_q&&active_after_chunk&&group_end_o_equal&&coordinate_address_valid;
assign address_update_select[3]=address_stream_write&&!chunk_reaches_end&&!past_active_q&&active_after_chunk&&(!group_end_o_equal||address_linear_tap);
assign address_update_select[4]=address_channel;
for(genvar byte_index=0;byte_index<p_cache_read_bytes;byte_index++)begin:g_byte
for(genvar source=0;source<5;source++)begin:g_source
assign source_available[byte_index][source]={1'b0,source_low[source]}<(p_word_shift+1)'(p_cache_read_bytes-byte_index);
end
assign reference_value[byte_index]=|(source_available[byte_index]&address_update_select);
''' + body + '''
end
assign equivalent=!legal_context||!(|address_update_select)||reference_value==actual_value;
endmodule
'''
    body = section(source, '      // 地址候选先形成行首和列内范围',
                   '    end\n    always_ff')
    body = body.replace('next_available[byte_index]', 'actual_value[byte_index]')
    return '''module comparison #(parameter int p_word_shift=3,p_cache_read_bytes=1<<p_word_shift)(
input logic[4:0][p_word_shift-1:0] source_low,
input logic commit_fast,address_channel,address_stream_write,chunk_reaches_end,
 row_last_q,row_base_valid,geometry_tile,past_active_q,active_after_chunk,
 group_end_o_equal,coordinate_address_valid,address_linear_tap,
output logic equivalent,
output logic[p_cache_read_bytes-1:0] reference_value,actual_value
);
logic[4:0] address_update_select;
logic[p_cache_read_bytes-1:0][4:0] source_available;
logic[p_cache_read_bytes-1:0] row_available,column_available,stream_available;
assign address_update_select[0]=commit_fast;
assign address_update_select[1]=address_stream_write&&chunk_reaches_end&&!row_last_q&&row_base_valid&&!geometry_tile;
assign address_update_select[2]=address_stream_write&&!chunk_reaches_end&&!past_active_q&&active_after_chunk&&group_end_o_equal&&coordinate_address_valid;
assign address_update_select[3]=address_stream_write&&!chunk_reaches_end&&!past_active_q&&active_after_chunk&&(!group_end_o_equal||address_linear_tap);
assign address_update_select[4]=address_channel;
for(genvar byte_index=0;byte_index<p_cache_read_bytes;byte_index++)begin:g_byte
for(genvar source=0;source<5;source++)begin:g_source
assign source_available[byte_index][source]={1'b0,source_low[source]}<(p_word_shift+1)'(p_cache_read_bytes-byte_index);
end
assign reference_value[byte_index]=|(source_available[byte_index]&address_update_select);
''' + body + '''
end
assign equivalent=reference_value==actual_value;
endmodule
'''


def range_unit(source: str, reference: str) -> str:
    context = re.search(r'    assign lane_context_allowed\[lane\] =.*?;', source, re.S).group(0)
    data = re.search(r'    assign chunk_data_allowed\[lane\] =.*?;', source, re.S).group(0)
    lane = re.search(r'      chunk_lane_allowed\[lane\] =.*?;', source, re.S).group(0).strip()
    active = (section(source, '  logic range_active_after_chunk;', '  assign stream_context=')
              if '  logic range_active_after_chunk;' in source else '')
    old = section(reference, "  always_comb begin\n    range_stream_allowed = 1'b0;",
                  '  // 译码选择保持状态优先次序')
    new = section(source, '  logic range_write_context;',
                  '  end else begin : g_stream_range_write' if 'g_stream_range_write' in source else
                  '  // 译码选择保持状态优先次序')
    unit = '''module comparison #(
parameter int SIZE=16,LANES=8,NARROW_LANES=4,
parameter int TILE_COUNT_W=$clog2(SIZE+1),CHUNK_COUNT_W=$clog2(LANES+1)
)(
input logic[21:0] state,
input logic[LANES-1:0] group_lane_allowed,word_lane_allowed,
input logic[LANES:0] active_lane_allowed_q,column_lane_allowed_q,
input logic narrow_output,word_output_q,past_active_q,chunk_reaches_end,row_last_q,
 cache_rsp_valid,cache_rsp_error,wr_ready,external_active_after,
output logic equivalent,reference_allowed,actual_allowed
);
''' + states(source) + '''
logic[LANES-1:0] lane_context_allowed,chunk_data_allowed,chunk_lane_allowed;
logic active_after_chunk;
for(genvar lane=0;lane<LANES;lane++)begin:g_lane
''' + context + data + 'assign ' + lane + '''
end
assign active_after_chunk = TILE_COUNT_W>=CHUNK_COUNT_W ?
 active_lane_allowed_q[0] && (&(~chunk_lane_allowed | active_lane_allowed_q[LANES:1])) :
 external_active_after;
''' + active + old.replace('range_stream_allowed', 'reference_allowed') + \
        new.replace('range_stream_allowed', 'actual_allowed') + '''
assign equivalent=reference_allowed==actual_allowed;
endmodule
'''
    width = re.search(r'  typedef enum logic \[(\d+):0\] \{', source).group(1)
    return unit.replace('[21:0]', f'[{width}:0]')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-ref', default='ef0dc75')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    path = args.source_root.resolve() / SOURCE
    stream_path, stream = read_module(args.source_root, 'stream')
    package = args.source_root.resolve()/'rtl/npu/conv/conv_im2col_frontend_pkg.sv'
    source_paths = [path]
    source = path.read_text()
    if stream_path != path:
        source = package.read_text()+'\n'+stream+'\n'+source
        source_paths += [stream_path, package]
    reference = read_rtl_source(f'{args.reference_ref}:{SOURCE}', cwd=ROOT, text=True)
    state_out=out/'stream_state'
    subprocess.run([sys.executable,str(ROOT/'test/frontend_state_selection/run_stream_control.py'),
                    '--source-root',str(args.source_root.resolve()),'--out',str(state_out)],check=True,cwd=ROOT)
    state_report=json.loads((state_out/'summary.json').read_text())
    units = {'word': word_unit(source.replace('active_select_commit','tile_commit')),
             'range': range_unit(source, reference)}
    for name, unit in units.items():
        (out / f'{name}.sv').write_text(unit)
    cases = [('word', f'b{shift}', {'p_word_shift': shift}) for shift in (1, 2, 3, 4)]
    cases += [('range', f's{size}_l{lanes}_n{narrow}',
               {'SIZE': size, 'LANES': lanes, 'NARROW_LANES': narrow})
              for size, lanes, narrow in ((32,17,4),(32,17,8),(32,20,4),(32,20,8),
                                          (32,24,4),(32,24,8),(64,32,4),(64,32,8))]
    results = []
    for kind, suffix, parameters in cases:
        name = kind + '_' + suffix
        script, log = out / (name + '.ys'), out / (name + '.log')
        options = ' '.join(f'-G{key}={value}' for key, value in parameters.items())
        script.write_text(f'read_slang --top comparison {options} {shlex.quote(str(out / (kind + ".sv")))}\n'
                          'prep -top comparison -flatten\n'
                          'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                            '--worker', str(script)], cwd=ROOT, stdout=stream,
                           stderr=subprocess.STDOUT, check=True)
        results.append({'name': name, 'passed': True})
        print('FRONTEND_STREAM_CONTROL_PASS', name, flush=True)
    (out / 'summary.json').write_text(json.dumps({'passed': True, 'cases': results,'complete_stream_control':state_report,
        'range_scope': 'Qualified range-write branch; speculative stream updates are checked by test/frontend_pipeline/check_control.py.',
        'reference_ref': args.reference_ref,
        'source_sha256': {str(item.relative_to(args.source_root.resolve())):
                         hashlib.sha256(item.read_bytes()).hexdigest() for item in source_paths}},
        ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
