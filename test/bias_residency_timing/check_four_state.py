#!/usr/bin/env python3
"""比较实际偏置驻留表达式的四态结果，覆盖共享及独立装载索引。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/loaders/bias_loader_buffer.sv')
HELPER = Path('rtl/common/parallel_prefix_add.sv')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def model(source, name, count, share):
    first = source.index('  assign load_request_idx =')
    last = source.index('  assign resident_current =', first)
    extras = source[source.index('endmodule') + len('endmodule'):]
    body = source[first:last]
    for helper in re.findall(r'^module\s+(\w+)\b', extras, flags=re.M):
        body = re.sub(r'\b' + helper + r'\b', name + '_' + helper, body)
        extras = re.sub(r'\b' + helper + r'\b', name + '_' + helper, extras)
    return f'''module {name}(input wire [{7*count+3}:0] stimulus,
    output wire [7:0] result);
  localparam CNT_W={count}, RANGE_WIDTH=CNT_W+1, p_share_load_index={share};
  localparam RANGE_STAGES=$clog2(RANGE_WIDTH);
  wire [CNT_W-1:0] load_block_idx, current_block_idx, group_blocks_needed;
  wire [CNT_W-1:0] load_request_idx;
  wire bank_loaded[2];
  wire [CNT_W-1:0] bank_block_idx[2];
  wire [CNT_W:0] bank_end_q[2];
  wire [1:0][1:0] window_end_valid;
  wire [1:0] load_window_hit, current_window_hit;
  assign {{load_block_idx,current_block_idx,group_blocks_needed,
           bank_block_idx[0],bank_block_idx[1],bank_end_q[0],bank_end_q[1],
           bank_loaded[0],bank_loaded[1]}}=stimulus;
{body}
  assign result={{window_end_valid,load_window_hit,current_window_hit}};
endmodule
{extras}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-root', type=Path)
    parser.add_argument('--reference-rev', default='aa0a169c')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if args.reference_root:
        reference_path = args.reference_root.resolve() / SOURCE
        reference_revision = str(args.reference_root.resolve())
    else:
        reference_revision = subprocess.check_output(
            ['git', 'rev-parse', args.reference_rev], cwd=ROOT, text=True).strip()
        reference_path = out / 'reference_source.sv'
        reference_path.write_bytes(subprocess.check_output(
            ['git', 'show', f'{reference_revision}:{SOURCE}'], cwd=ROOT))
    originals = {'reference': reference_path,
                 'current': args.source_root.resolve() / SOURCE,
                 'helper': args.source_root.resolve() / HELPER}
    hashes = {name: digest(path) for name, path in originals.items()}
    runs = []
    for count, share in [(1, 0), (5, 0), (29, 0), (29, 1), (32, 0), (32, 1)]:
        folder = out / f'count{count}_share{share}'
        folder.mkdir(exist_ok=True)
        sources = []
        for label in ('reference', 'current'):
            target = folder / (label + '.sv')
            target.write_text(model(originals[label].read_text(), label, count, share))
            sources.append(target)
        tb = folder / 'tb.sv'
        tb.write_text(f'''module tb;
  localparam W={7*count+4};
  reg [W-1:0] stimulus, known;
  wire [7:0] old_result, new_result;
  integer seed=32'h93a8147, checks=0;
  reference u_old(.stimulus(stimulus),.result(old_result));
  current u_new(.stimulus(stimulus),.result(new_result));
  task check;
    begin
      #1;checks=checks+1;
      if(old_result!==new_result)
        $fatal(1,"Residency four-state mismatch input=%h old=%b new=%b",stimulus,old_result,new_result);
    end
  endtask
  initial begin
    for(integer sample=0;sample<64;sample++)begin
      for(integer bit_i=0;bit_i<W;bit_i++)known[bit_i]=$random(seed);
      if(sample==0)known='0;
      if(sample==1)known='1;
      stimulus=known;check();
      for(integer bit_i=0;bit_i<W;bit_i++)begin
        stimulus=known;stimulus[bit_i]=1'bx;check();
        stimulus=known;stimulus[bit_i]=1'bz;check();
      end
    end
    for(integer sample=0;sample<4096;sample++)begin
      for(integer bit_i=0;bit_i<W;bit_i++)begin
        case($random(seed)&15)
          0:stimulus[bit_i]=1'bx;
          1:stimulus[bit_i]=1'bz;
          default:stimulus[bit_i]=$random(seed);
        endcase
      end
      check();
    end
    $display("BIAS_RESIDENCY_FOUR_STATE_PASS checks=%0d",checks);$finish;
  end
endmodule
''')
        executable = folder / 'simulation.vvp'
        command = ['iverilog', '-g2012', '-s', 'tb', '-o', str(executable),
                   *map(str, sources), str(originals['helper']), str(tb)]
        with (folder / 'build.log').open('w') as stream:
            subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=True)
        result = subprocess.run(['vvp', str(executable)], text=True, capture_output=True, timeout=120)
        log = folder / 'run.log'
        log.write_text(result.stdout + result.stderr)
        match = re.search(r'BIAS_RESIDENCY_FOUR_STATE_PASS checks=(\d+)', result.stdout)
        assert result.returncode == 0 and match, result.stdout + result.stderr
        row = {'COUNT_WIDTH': count, 'p_share_load_index': share, 'passed': True,
               'checks': int(match[1]), 'run_log_sha256': digest(log),
               'build_command': command, 'testbench_sha256': digest(tb)}
        runs.append(row)
        print(json.dumps({key: row[key] for key in ('COUNT_WIDTH', 'p_share_load_index', 'passed', 'checks')}), flush=True)
    assert hashes == {label: digest(path) for label, path in originals.items()}
    report = {'passed': True, 'strict_four_state_equivalence': True,
              'source_sha256': hashes, 'profiles': runs,
              'reference_revision': reference_revision,
              'source_root': str(args.source_root.resolve())}
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
