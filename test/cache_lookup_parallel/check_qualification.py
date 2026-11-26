#!/usr/bin/env python3
"""提取实际请求资格逻辑，检查任意输入等价和四态传播。"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
REQUEST = 'rtl/npu/dma/cache/conv_cache_request_path.sv'
PROFILES = ((1, 1, 2, 0), (2, 1, 3, 0), (3, 2, 5, 1), (2, 4, 9, 1))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def wrapper(source, name):
    selection_start = source.index('  always_comb begin\n    lookup_candidate_select =')
    selection_end = source.index('  // 保存后的填充组号', selection_start)
    selection = source[selection_start:selection_end]
    match_start = source.index('  always_comb begin\n    case (^{fg_state, req_fire, lookup_input_valid, request_count})\n      1\'b0, 1\'b1: begin\n        lookup_fill_match')
    match_end = source.index('  if (DEMAND_DEPTH == 1', match_start)
    fill_match = source[match_start:match_end]
    qualified_start = source.index('  end else begin : g_queued_lookup_qualification\n')
    qualified_end = source.index('\n  // 快照内容在时钟边沿保存', qualified_start)
    qualified = source[qualified_start:qualified_end]
    qualified = qualified.split('\n', 1)[1].rsplit('\n  end', 1)[0]
    return f'''// 实际请求资格片段的组合检查接口，所有输入独立变化。
module {name} #(
  parameter integer Q=2, SI=4, AW=9, SHIFT=1,
  parameter integer WIDTH=15+Q+2*AW+2*SI
) (
  input logic [WIDTH-1:0] i_values, // 状态、地址、写入资格及候选比较结果
  output logic [1:0] o_result // 读写冲突和快照资格
);
  localparam integer DQ_CW=Q, RAM_BANK_SHIFT=SHIFT;
  localparam logic [1:0] FG_MISS=2'd1;
  logic [1:0] fg_state, lookup_candidate_select;
  logic [Q-1:0] request_count;
  logic req_fire, lookup_input_valid, ram_wen, metadata_enable, metadata_fill_good;
  logic [3:0] lookup_candidate_conflict, lookup_candidate_fill_match;
  logic [AW-1:0] speculative_address, fill_word_address;
  logic [SI-1:0] fill_set, lookup_read_set;
  logic lookup_fill_match, spec_read_conflict, lookup_snapshot_good;
  assign {{fg_state, request_count, req_fire, lookup_input_valid, ram_wen,
      metadata_enable, metadata_fill_good, lookup_candidate_conflict,
      lookup_candidate_fill_match, speculative_address, fill_word_address,
      fill_set, lookup_read_set}} = i_values;
{selection}
{fill_match}
  if (1) begin : g_qualification
{qualified}
  end
  assign o_result = {{lookup_snapshot_good, spec_read_conflict}};
endmodule
'''


BENCH = r'''module tb;
  localparam integer Q=VALUE_Q, SI=VALUE_SI, AW=VALUE_AW, SHIFT=VALUE_SHIFT;
  localparam integer WIDTH=15+Q+2*AW+2*SI;
  logic [WIDTH-1:0] i_values;
  wire equivalent;
  logic [31:0] random_state=32'h28e14c9b;
  integer checks=0;
  qualification_proof #(.Q(Q),.SI(SI),.AW(AW),.SHIFT(SHIFT)) dut(.*);
  function automatic logic [31:0] advance(input logic [31:0] value);
    logic [31:0] result;
    result=value^(value<<13);result=result^(result>>17);return result^(result<<5);
  endfunction
  function automatic logic four(input logic [1:0] value);
    case(value)0:return 0;1:return 1;2:return 1'bx;3:return 1'bz;endcase
  endfunction
  initial begin
    for(integer trial=0;trial<65536;trial++)begin
      for(integer bit_index=0;bit_index<WIDTH;bit_index++)begin
        random_state=advance(random_state);
        if(trial%4==0 || (trial%4==1 && bit_index<WIDTH-(4+Q)))
          i_values[bit_index]=four(random_state[1:0]);
        else i_values[bit_index]=random_state[0];
      end
      if(trial%4==2)begin
        random_state=advance(random_state);
        i_values[(random_state>>1)%WIDTH]=random_state[0] ? 1'bx : 1'bz;
      end
      #1;
      if(equivalent!==1'b1)$fatal(1,"qualification differs Q=%0d SI=%0d AW=%0d trial=%0d",Q,SI,AW,trial);
      checks++;
    end
    $display("QUALIFICATION_PASS checks=%0d",checks);
    $finish;
  end
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='d7cb67be')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = subprocess.check_output(['git', 'show', args.reference + ':' + REQUEST], cwd=ROOT, text=True)
    current = (ROOT / REQUEST).read_text()
    model = out / 'qualification_proof.sv'
    model.write_text(wrapper(reference, 'qualification_reference') +
                     wrapper(current, 'qualification_current') + '''
module qualification_proof #(
  parameter integer Q=2, SI=4, AW=9, SHIFT=1,
  parameter integer WIDTH=15+Q+2*AW+2*SI
) (
  input logic [WIDTH-1:0] i_values, // 独立组合输入
  output logic equivalent // 两种实现的四态输出一致
);
  wire [1:0] reference_result, current_result;
  qualification_reference #(.Q(Q),.SI(SI),.AW(AW),.SHIFT(SHIFT)) u_reference(
      .i_values(i_values),.o_result(reference_result));
  qualification_current #(.Q(Q),.SI(SI),.AW(AW),.SHIFT(SHIFT)) u_current(
      .i_values(i_values),.o_result(current_result));
  assign equivalent=reference_result===current_result;
endmodule
''')
    sources = [model, ROOT / 'rtl/npu/dma/cache/conv_cache_queued_read_select.sv']
    source_hashes = {str(path): digest(path) for path in sources + [ROOT / REQUEST]}
    reports = []
    for profile, (count_width, set_width, address_width, bank_shift) in enumerate(PROFILES):
        parameters = dict(Q=count_width, SI=set_width, AW=address_width, SHIFT=bank_shift)
        for mode in ('generic', 'fpga'):
            name = f'{mode}_{profile}'
            flags = ['-DSYNTHESIS=1', '-DXILINX_FPGA=1'] if mode == 'fpga' else []
            formal_flags = flags if flags else ['-USYNTHESIS', '-UXILINX_FPGA']
            options = [f'-G{key}={value}' for key, value in parameters.items()]
            script, log = out / (name + '.ys'), out / (name + '_formal.log')
            script.write_text('read_slang --top qualification_proof ' +
                              shlex.join(formal_flags + options + list(map(str, sources))) +
                              '\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n'
                              'prep -top qualification_proof -flatten\ncheck -assert\n'
                              'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
            with log.open('w') as stream:
                subprocess.run([sys.executable, ROOT / 'scripts/fpga/open_fpga_synth.py', '--worker', script],
                               stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=120)
            assert 'SUCCESS!' in log.read_text()
            bench_text = BENCH
            for key, value in parameters.items():
                bench_text = bench_text.replace('VALUE_' + key, str(value))
            bench = out / (name + '_tb.sv')
            bench.write_text(bench_text)
            binary, simulation = out / (name + '.vvp'), out / (name + '_simulation.log')
            with (out / (name + '_compile.log')).open('w') as stream:
                subprocess.run(['iverilog', '-g2012', '-s', 'tb', *flags, '-o', str(binary),
                                *map(str, sources), str(bench)], stdout=stream,
                               stderr=subprocess.STDOUT, check=True)
            with simulation.open('w') as stream:
                subprocess.run(['vvp', binary], stdout=stream, stderr=subprocess.STDOUT,
                               check=True, timeout=120)
            assert 'QUALIFICATION_PASS checks=65536' in simulation.read_text()
            record = dict(mode=mode, macro_options=formal_flags, parameters=parameters,
                          arbitrary_input_proof=True, four_state_checks=65536, passed=True,
                          formal_log_sha256=digest(log), simulation_log_sha256=digest(simulation))
            reports.append(record)
            print(json.dumps(record), flush=True)
    assert all(digest(Path(path)) == value for path, value in source_hashes.items())
    report = dict(passed=True, reference_commit=args.reference, input_constraints=[], checks=reports,
                  source_sha256=source_hashes, runner_sha256=digest(Path(__file__)))
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
