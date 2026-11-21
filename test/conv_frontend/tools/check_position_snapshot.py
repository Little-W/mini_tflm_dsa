#!/usr/bin/env python3
"""证明描述符提交时保存的历史命中和坐标与四项历史表一致。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.source_root/'rtl/npu/conv/conv_im2col_frontend.sv'
    text = path.read_text()
    source_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    first = text.index('  if (REGISTER_DESCRIPTOR && REGISTER_CACHE_REQUEST) begin : g_saved_position_lookup')
    last = text.index('  assign p_cache_write_enable =', first)
    stage = text[first:last]
    positions = re.findall(r'\bp0\s*<=\s*([^;]+);', text)
    assert positions == ['0', 'committing_tile.position']
    valid_writes = re.findall(r'\bp_cache_valid(?:\[p_cache_select\])?\s*<=\s*([^;]+);', text)
    assert valid_writes == ['0', '0', '1', '1']
    stored_key = re.search(r'  assign p_cache_write_data =.*?;', text, re.S).group()
    assert stored_key.count('{p0,') == 2
    source = args.out/'snapshot.sv'
    source.write_text('''module proof #(parameter int CW=4)(
 input logic clk,rst_n,input logic[1:0]event_choice,
 input logic[31:0]position,coordinates,input logic invalid,
 output logic equivalent);
 localparam bit REGISTER_DESCRIPTOR=1,REGISTER_CACHE_REQUEST=1;
 typedef struct packed {logic invalid;logic[31:0]position;}tile_t;
 tile_t committing_tile;
 assign committing_tile={invalid,position};
 logic[31:0]p0,p_decode;
 logic[1:0]p_cache_select;
 logic[3:0]p_cache_valid;
 logic[63:0]p_cache_data[4];
 wire cfg_valid=event_choice==1;
 wire cfg_ready=1'b1;
 wire tile_commit=event_choice==2;
 wire p_cache_write_enable=rst_n&&event_choice==3;
 wire[63:0]p_cache_write_data={p0,coordinates};
 logic p_cache_hit;
 logic[15:0]p_cache_y,p_cache_x;
 assign p_decode=p0;
 assign p_cache_select=2'(p0>>CW);
 always_ff @(posedge clk or negedge rst_n)begin
  if(!rst_n)begin p0<=0;p_cache_valid<=0;end
  else begin
   if(cfg_valid)p_cache_valid<=0;
   if(tile_commit&&!invalid)p0<=position;
   if(p_cache_write_enable)p_cache_valid[p_cache_select]<=1;
  end
 end
 always_ff @(posedge clk)begin
  if(p_cache_write_enable)p_cache_data[p_cache_select]<=p_cache_write_data;
 end
''' + stage + '''
 wire[63:0]reference_data=p_cache_data[p_cache_select];
 wire reference_hit=p_cache_valid[p_cache_select]&&reference_data[63:32]==p0;
 assign equivalent=(p_cache_hit==reference_hit)&&
   (!reference_hit||{p_cache_y,p_cache_x}==reference_data[31:0]);
endmodule
''')
    rows = []
    for shift in (0, 1, 2, 3, 4, 5, 6, 16, 31):
        name = f'shift{shift}'
        script, log = args.out/(name+'.ys'), args.out/(name+'.log')
        script.write_text('read_slang --top proof -GCW=' + str(shift) + ' ' + shlex.quote(str(source)) +
                          '\nprep -top proof -flatten\nmemory_map\nasync2sync\nopt\ncheck -assert\n'
                          'sat -seq 2 -set-at 1 rst_n 0 -prove-skip 1 -prove equivalent 1 -verify\n'
                          'sat -seq 1 -tempinduct-inductonly -maxsteps 1 -prove equivalent 1 -verify\n')
        with log.open('w') as stream:
            run = subprocess.run([sys.executable, str(ROOT/'scripts/fpga/open_fpga_synth.py'),
                                  '--worker', str(script)], stdout=stream, stderr=subprocess.STDOUT,
                                 timeout=120)
        if run.returncode or 'Induction step proven: SUCCESS!' not in log.read_text():
            raise RuntimeError(str(log))
        rows.append({'index_shift': shift, 'passed': True,
                     'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()})
    if source_sha != hashlib.sha256(path.read_bytes()).hexdigest():
        raise RuntimeError('Source changed during verification')
    report = {'passed': True, 'source_sha256': source_sha, 'runs': rows,
              'reset_steps': 2, 'unbounded_induction_steps': 1,
              'formal_domain': 'all binary input and state values',
              'event_scope': 'Configuration, descriptor commit, and history write are mutually exclusive.',
              'event_relationship_proof': 'check_frontend_event_domains.py',
              'position_and_coordinate_constraints': [],
              'checked_properties': ['history hit every cycle', 'coordinate payload whenever the history entry hits']}
    (args.out/'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print('POSITION_SNAPSHOT_PASS', len(rows))


if __name__ == '__main__':
    main()
