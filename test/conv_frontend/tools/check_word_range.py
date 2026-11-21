#!/usr/bin/env python3
"""证明字内剩余范围与地址在同一边沿保存。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]


def between(text, start, end):
    first = text.index(start)
    return text[first:text.index(end, first)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    source = args.source_root / 'rtl/npu/conv/conv_im2col_frontend.sv'
    text = source.read_text()
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    event = runpy.run_path(str(ROOT / 'test/conv_frontend/tools/check_frontend_event_domains.py'))
    results = []

    def prove(name, content, options, commands):
        sv, ys, log = [args.out / (name + suffix) for suffix in ('.sv', '.ys', '.log')]
        sv.write_text(content)
        ys.write_text('read_slang --top proof -DSYNTHESIS=1 -DXILINX_FPGA=1 ' +
                      options + ' ' + shlex.quote(str(sv)) +
                      '\nprep -top proof -flatten\nasync2sync\nopt\ncheck -assert\n' + commands)
        with log.open('w') as stream:
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                     '--worker', str(ys)], stdout=stream, stderr=subprocess.STDOUT,
                                    timeout=180)
        if result.returncode or 'SUCCESS!' not in log.read_text():
            raise RuntimeError(str(log))
        results.append({'name': name, 'passed': True,
                        'source_sha256': hashlib.sha256(sv.read_bytes()).hexdigest(),
                        'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()})

    for registered in (0, 1):
        content = event['module'](text, 'events') + \
            'module proof(' + event['PORTS'] + '''output logic equivalent);
 logic [20:0] result;
 logic invariant;
 wire [4:0] address_select=result[16:12];
''' + f'events #(.REGISTER_DESCRIPTOR({registered})) u_events(.*);\n' + '''
 assign equivalent=invariant && ((address_select&(address_select-5'd1))==0);
endmodule
'''
        prove(f'address_events_r{registered}', content, '',
              'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
    update = between(text, '  assign address_update_value =',
                     '  // 保存字命中标志与地址共用更新事件')
    content = '''module proof #(parameter int WORD_BYTES=8)(
 input logic clk,rst_n,input logic[2:0]source_index,
 input logic[4:0][31:0]source_address,output logic equivalent);
 localparam int p_cache_read_bytes=WORD_BYTES,p_word_shift=$clog2(WORD_BYTES);
 localparam bit p_saved_word_range=1'b1;
 logic[WORD_BYTES-1:0]word_available_q,reference_available;
 logic[31:0]addr,address_update_value;
 logic[4:0]address_update_select;
 typedef struct packed{logic[31:0]address;}descriptor_t;
 descriptor_t committing_tile;
 wire[31:0]next_row_addr=source_address[1],next_tap_addr=source_address[2];
 wire[31:0]next_byte_addr=source_address[3],channel_addr=source_address[4];
 assign committing_tile.address=source_address[0];
 assign address_update_select=source_index<5 ? 5'b1<<source_index : 5'b0;
''' + update + '''
 for(genvar byte_index=0;byte_index<WORD_BYTES;byte_index++)begin:g_reference
  assign reference_available[byte_index]=
   {1'b0,addr[p_word_shift-1:0]}<(p_word_shift+1)'(WORD_BYTES-byte_index);
 end
 assign equivalent=word_available_q==reference_available;
endmodule
'''
    for word_bytes in (2, 3, 4, 5, 6, 7, 8):
        prove(f'word_bytes{word_bytes}', content, f'-GWORD_BYTES={word_bytes}',
              'sat -seq 2 -set-at 1 rst_n 0 -prove-skip 1 -prove equivalent 1 -verify\n' +
              'sat -seq 1 -tempinduct-inductonly -maxsteps 1 -prove equivalent 1 -verify\n')
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
    report = {'passed': True, 'source_sha256': digest, 'runs': results,
              'address_event_proof': 'Both descriptor modes, unrestricted input flags and state index.',
              'address_stage_model': 'One selected address source or no write; source data is unrestricted.',
              'event_state_encoding': 'One-hot or zero; every reachable state assignment is one-hot.',
              'reset_steps': 2, 'unbounded_induction_steps': 1,
              'synthesis_configuration': ['SYNTHESIS=1', 'XILINX_FPGA=1']}
    (args.out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'passed': True, 'event_proofs': 2, 'inductive_word_widths': 7}))


if __name__ == '__main__':
    main()
