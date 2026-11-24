#!/usr/bin/env python3
"""证明保存的行数条件与计数器在相同周期一致。"""
from pathlib import Path
import argparse
import hashlib
import json
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'rtl/npu/ps_compact/ps_frame_store.sv'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def model(source):
    start = source.index('    logic commit_following_equal;')
    end = source.index('    always @(posedge clk or negedge rst_n)', start)
    commit_state = source[start:end]
    start = source.index('    // 行数条件与各计数器同时更新')
    end = source.index('    always @(posedge clk or negedge rst_n)', start)
    read_state = source[start:end]
    return '''module counter_state #(
 parameter LENGTH_BITS=9
)(input logic clk,rst_n,clear_metadata,cancel_prepared,prepare_start,encode_commit_valid,
 input logic replay_active,replay_consume,prefetch_fire,prefetch_prepare,
 input logic [31:0] requested_rows,
 output logic equivalent);
 logic [LENGTH_BITS-1:0] commit_count,frame_rows_q,replay_index,read_index;
 logic commit_complete_q,commit_next_complete_q,replay_complete_q,read_remaining_q;
 typedef struct packed {logic [31:0] rows;} request_t;
 request_t request_q;
 assign request_q.rows=requested_rows;
 always_ff @(posedge clk or negedge rst_n) begin
  if(!rst_n)begin
   commit_count<='0;frame_rows_q<='0;replay_index<='0;read_index<='0;
  end else if(clear_metadata || cancel_prepared)begin
   commit_count<='0;replay_index<='0;read_index<='0;
  end else begin
   if(encode_commit_valid)commit_count<=commit_count+LENGTH_BITS'(1);
   if(replay_active && replay_consume)replay_index<=replay_index+LENGTH_BITS'(1);
   if(prefetch_fire)read_index<=read_index+LENGTH_BITS'(1);
   if(prepare_start)begin
    commit_count<='0;frame_rows_q<=LENGTH_BITS'(requested_rows);
    replay_index<='0;read_index<=LENGTH_BITS'(prefetch_prepare);
   end
  end
 end
''' + commit_state + read_state + '''
 assign equivalent = {read_remaining_q,replay_complete_q,commit_complete_q,commit_next_complete_q} ==
  {(read_index<frame_rows_q),(replay_index==frame_rows_q),(commit_count==frame_rows_q),
   (commit_count+LENGTH_BITS'(1)==frame_rows_q)};
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--widths', nargs='+', type=int, default=[1, 2, 3, 6, 9, 10])
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = SOURCE.read_text()
    actual = out / 'counter_state.sv'
    actual.write_text(model(source))
    records = []
    for width in args.widths:
        script = out / f'width{width}.ys'
        log = out / f'width{width}.log'
        script.write_text(shlex.join(['read_slang', '--top', 'counter_state',
            f'-GLENGTH_BITS={width}', str(actual), str(ROOT / 'rtl/common/add_equal.sv')]) + '\n'
            'prep -top counter_state -flatten\nasync2sync\nopt_clean\n'
            'sat -verify -tempinduct -seq 2 -set-at 1 rst_n 0 -prove equivalent 1\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                            '--worker', str(script)], stdout=stream, stderr=subprocess.STDOUT,
                           check=True, timeout=180)
        assert 'Induction step proven: SUCCESS!' in log.read_text()
        records.append(dict(width=width, passed=True, log_sha256=digest(log)))
    assert SOURCE.read_text() == source
    report = dict(passed=True, source_sha256=digest(SOURCE), test_sha256=digest(Path(__file__)),
                  model_sha256=digest(actual), cases=records,
                  assumptions='第一个采样边沿复位；后续控制输入与行数不受限制')
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(dict(passed=True, widths=[r['width'] for r in records])))


if __name__ == '__main__':
    main()
