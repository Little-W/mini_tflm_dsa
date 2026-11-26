#!/usr/bin/env python3
"""检查循环优先选择的任意输入等价及未知值传播。"""
from pathlib import Path
import argparse
import hashlib
import json
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


BENCH = r'''module tb;
  localparam integer DEPTH=VALUE_DEPTH, AW=DEPTH<=1 ? 1 : $clog2(DEPTH);
  logic [DEPTH-1:0] i_match;
  logic [AW-1:0] i_head;
  wire equivalent;
  integer checks=0;
  logic [31:0] random_state=32'h5c3a1027;
  prefetch_priority_proof #(.DEPTH(DEPTH)) dut(.*);
  function automatic logic four(input integer value);
    case(value&3)0:return 0;1:return 1;2:return 1'bx;3:return 1'bz;endcase
  endfunction
  function automatic logic [31:0] advance(input logic [31:0] value);
    logic [31:0] result;
    result=value^(value<<13);result=result^(result>>17);return result^(result<<5);
  endfunction
  task automatic check;
    #1;
    if(equivalent!==1'b1)$fatal(1,"priority differs DEPTH=%0d head=%b match=%b",DEPTH,i_head,i_match);
    checks++;
  endtask
  initial begin
    if(DEPTH<=4)begin
      for(integer value=0;value<(1<<(2*(DEPTH+AW)));value++)begin
        for(integer bit_index=0;bit_index<DEPTH;bit_index++)
          i_match[bit_index]=four(value>>(2*bit_index));
        for(integer bit_index=0;bit_index<AW;bit_index++)
          i_head[bit_index]=four(value>>(2*(DEPTH+bit_index)));
        check();
      end
    end else begin
      for(integer head=0;head<DEPTH;head++)begin
        i_head=AW'(head);
        for(integer value=0;value<(1<<(2*DEPTH));value++)begin
          for(integer bit_index=0;bit_index<DEPTH;bit_index++)
            i_match[bit_index]=four(value>>(2*bit_index));
          check();
        end
      end
      for(integer head=0;head<(1<<(2*AW));head++)begin
        for(integer bit_index=0;bit_index<AW;bit_index++)
          i_head[bit_index]=four(head>>(2*bit_index));
        if((^i_head)===1'bx)begin
          for(integer value=0;value<(1<<DEPTH);value++)begin
            i_match=DEPTH'(value);
            check();
          end
        end
      end
      for(integer trial=0;trial<32768;trial++)begin
        for(integer bit_index=0;bit_index<DEPTH;bit_index++)begin
          random_state=advance(random_state);i_match[bit_index]=four(random_state[1:0]);
        end
        for(integer bit_index=0;bit_index<AW;bit_index++)begin
          random_state=advance(random_state);i_head[bit_index]=four(random_state[1:0]);
        end
        check();
      end
    end
    $display("PRIORITY_PASS checks=%0d",checks);$finish;
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
    source = subprocess.check_output(['git', 'show', args.reference +
        ':rtl/npu/dma/cache/conv_windowed_cache.sv'], cwd=ROOT, text=True)
    start = source.index('  for (genvar slot = 0; slot < PF_DEPTH; slot++) begin : g_prefetch_priority')
    end = source.index('  for (genvar bit_index = 0; bit_index < PF_AW;', start)
    reference = source[start:end]
    for before, after in (('pf_current_by_slot', 'i_match'), ('pf_head', 'i_head'),
                          ('pf_pick_by_slot', 'reference_select'), ('PF_DEPTH', 'DEPTH'), ('PF_AW', 'AW')):
        reference = reference.replace(before, after)
    model = out / 'prefetch_priority_proof.sv'
    model.write_text('''// 直接使用参照缓存的循环优先选择表达式。
module prefetch_priority_proof #(
  parameter integer DEPTH=8,
  parameter integer AW=DEPTH<=1 ? 1 : $clog2(DEPTH)
) (
  input logic [DEPTH-1:0] i_match, // 各位置的匹配结果
  input logic [AW-1:0] i_head, // 循环起始位置
  output logic equivalent // 两种实现的四态结果一致
);
  wire [DEPTH-1:0] reference_select, current_select;
''' + reference + '''
  conv_cache_prefetch_priority #(.p_depth(DEPTH),.p_address_width(AW)) u_current(
      .i_match(i_match),.i_head(i_head),.o_select(current_select));
  assign equivalent=reference_select===current_select;
endmodule
''')
    sources = [model, ROOT / 'rtl/npu/dma/cache/conv_cache_prefetch_priority.sv']
    hashes = {str(path): digest(path) for path in sources}
    reports = []
    for depth in (1, 2, 4, 8):
        address_width = max(1, (depth - 1).bit_length())
        expected = 4 ** (depth + address_width) if depth <= 4 else (
            depth * 4 ** depth + (4 ** address_width - 2 ** address_width) * 2 ** depth + 32768)
        for mode in ('generic', 'fpga'):
            name = f'{mode}_d{depth}'
            flags = ['-DSYNTHESIS=1', '-DXILINX_FPGA=1'] if mode == 'fpga' else []
            formal_flags = flags if flags else ['-USYNTHESIS', '-UXILINX_FPGA']
            script, log = out / (name + '.ys'), out / (name + '_formal.log')
            script.write_text('read_slang --top prefetch_priority_proof ' +
                              shlex.join([f'-GDEPTH={depth}', *formal_flags, *map(str, sources)]) +
                              '\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n'
                              'prep -top prefetch_priority_proof -flatten\ncheck -assert\n'
                              'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
            with log.open('w') as stream:
                subprocess.run([sys.executable, ROOT / 'scripts/fpga/open_fpga_synth.py', '--worker', script],
                               stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=120)
            assert 'SUCCESS!' in log.read_text()
            bench = out / (name + '_tb.sv')
            bench.write_text(BENCH.replace('VALUE_DEPTH', str(depth)))
            binary, simulation = out / (name + '.vvp'), out / (name + '_simulation.log')
            with (out / (name + '_compile.log')).open('w') as stream:
                subprocess.run(['iverilog', '-g2012', '-s', 'tb', *flags, '-o', str(binary),
                                *map(str, sources), str(bench)], stdout=stream,
                               stderr=subprocess.STDOUT, check=True)
            with simulation.open('w') as stream:
                subprocess.run(['vvp', binary], stdout=stream, stderr=subprocess.STDOUT,
                               check=True, timeout=240)
            assert f'PRIORITY_PASS checks={expected}' in simulation.read_text()
            record = dict(depth=depth, mode=mode, macro_options=formal_flags,
                          arbitrary_input_proof=True, four_state_checks=expected, passed=True,
                          formal_log_sha256=digest(log), simulation_log_sha256=digest(simulation))
            reports.append(record)
            print(json.dumps(record), flush=True)
    assert all(digest(Path(path)) == value for path, value in hashes.items())
    report = dict(passed=True, reference_commit=args.reference, input_constraints=[], checks=reports,
                  source_sha256=hashes, runner_sha256=digest(Path(__file__)))
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
