#!/usr/bin/env python3
"""比较窗口余量分段选择与完整十七位范围关系。"""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import shlex
import subprocess
import sys

import four_state_coverage as coverage

ROOT = Path(__file__).resolve().parents[2]
CASES = ((1, 1), (2, 2), (3, 4), (4, 8), (5, 16), (5, 17),
         (5, 31), (6, 32), (15, 16384), (15, 32767))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    out = parser.parse_args().out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = ROOT / 'rtl/npu/conv/conv_tile_remaining_range.sv'
    resolver = runpy.run_path(str(ROOT / 'scripts/rtl/source_files.py'))
    sources = resolver['with_dependencies']([source], ROOT)
    hashes = {str(p.relative_to(ROOT)): digest(p)
              for p in resolver['input_files'](sources, ROOT)}
    results = []
    for width, size in CASES:
        name = f'width{width}_size{size}'
        model = out / (name + '.sv')
        model.write_text(f'''module comparison(
input logic [16:0] i_remaining,
input logic [{width-1}:0] i_columns,
output logic equivalent,actual,expected);
conv_tile_remaining_range #(.p_width({width}),.p_size({size})) dut(
  .i_remaining,.i_columns,.o_fits(actual));
assign expected=i_columns=='0 ?
  (!i_remaining[16] && 17'({size})<=i_remaining) :
  (!i_remaining[16] && 17'(i_columns)<=i_remaining);
assign equivalent=actual===expected;
endmodule
''')
        script, log = out / (name + '.ys'), out / (name + '.formal.log')
        script.write_text(shlex.join(['read_slang', '--top', 'comparison',
            '-DSYNTHESIS=1', *map(str, sources), str(model)]) +
            '\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n'
            'prep -top comparison -flatten\nsat -verify -prove equivalent 1\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                '--worker', str(script)], stdout=stream, stderr=subprocess.STDOUT,
                check=True, timeout=180)
        if 'SUCCESS!' not in log.read_text():
            raise RuntimeError('窗口余量形式比较未完成')
        widths = {'i_remaining': 17, 'i_columns': width}
        bits = sum(widths.values())
        tb = f'''module tb;
logic [16:0] i_remaining;
logic [{width-1}:0] i_columns;
logic equivalent,actual,expected;
localparam integer p_input_width={bits};
logic [p_input_width-1:0] stimulus;
assign {{i_remaining,i_columns}}=stimulus;
comparison dut(.*);
integer positive=0,negative=0;
initial begin
  for(integer sample=0;sample<4096;sample++)begin
    stimulus=$urandom;
    case(sample%16)
      0:stimulus='0;
      1:stimulus='1;
      2:stimulus='x;
      3:stimulus='z;
      4,5:stimulus[sample%p_input_width]=1'bx;
      6,7:stimulus[sample%p_input_width]=1'bz;
      8:stimulus={{17'({size}),{width}'(0)}};
      9:stimulus={{17'({size}-1),{width}'(0)}};
      10:stimulus={{17'(sample%32),{width}'(sample%32)}};
      11:stimulus={{17'(sample%32),{width}'(sample%32+1)}};
      default:begin end
    endcase
    #1;
    if(equivalent!==1'b1)$fatal(1,"remaining range mismatch sample=%0d",sample);
    if(actual===1'b1)positive++;
    if(actual===1'b0)negative++;
  end
  if(positive<100 || negative<100)$fatal(1,"range result coverage");
  $display("REMAINING_RANGE_FOUR_STATE_PASS samples=4096 positive=%0d negative=%0d",positive,negative);
  $finish;
end
endmodule
'''
        names = 'i_remaining,i_columns'
        tb = tb.replace('initial begin', coverage.declarations('p_input_width') +
            'initial begin' + coverage.initialize('p_input_width', names), 1)
        tb = tb.replace('    #1;', coverage.sample('p_input_width') + '    #1;', 1)
        tb = tb.replace('  $display("REMAINING_RANGE_FOUR_STATE_PASS',
            coverage.finish('p_input_width') + '  $display("REMAINING_RANGE_FOUR_STATE_PASS', 1)
        bench, binary = out / (name + '.tb.sv'), out / (name + '.vvp')
        bench.write_text(tb)
        four = []
        for synthesis in (False, True):
            simulation = out / (name + f'.synthesis{int(synthesis)}.log')
            command = ['iverilog', '-g2012', '-s', 'tb', '-o', str(binary)]
            if synthesis:
                command.append('-DSYNTHESIS=1')
            with simulation.open('w') as stream:
                subprocess.run(command + [*map(str, sources), str(model), str(bench)],
                    stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=120)
                subprocess.run(['vvp', str(binary)], stdout=stream,
                    stderr=subprocess.STDOUT, check=True, timeout=120)
            if 'REMAINING_RANGE_FOUR_STATE_PASS' not in simulation.read_text():
                raise RuntimeError('窗口余量四态比较未完成')
            four.append(dict(synthesis=synthesis, comparisons=4096, passed=True,
                coverage=coverage.result(simulation, widths), log_sha256=digest(simulation)))
        binary.unlink()
        results.append(dict(width=width, size=size, formal_passed=True,
            formal_log_sha256=digest(log), four_state=four))
        print('REMAINING_RANGE_PASS ' + name, flush=True)
    if any(digest(ROOT / name) != value for name, value in hashes.items()):
        raise RuntimeError('检查期间窗口余量源码发生变化')
    (out / 'summary.json').write_text(json.dumps(dict(passed=True,
        formal_properties=len(results), four_state_comparisons=len(results)*8192,
        cases=results, source_sha256=hashes), ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
