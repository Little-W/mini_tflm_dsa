#!/usr/bin/env python3
"""验证快照最终有效位并行准备后的完整二态及四态更新条件。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/dma/cache/conv_read_cache.sv')


def source_path(root: Path) -> Path:
    child = root / SOURCE.with_name('conv_windowed_cache.sv')
    return child if child.is_file() else root / SOURCE


PORTS = '''input logic rst_n,cfg_valid,cfg_ready,req_fire,req_valid,
input logic [1:0] fg_state,
input logic [DQ_CW-1:0] request_count,
input logic ram_wen,metadata_fill_good,raw_address_conflict,raw_fill_match,
input logic [3:0] lookup_candidate_conflict,lookup_candidate_fill_match,
input logic [1:0] lookup_candidate_select'''


def clock_block(text: str) -> str:
    assignment = text.index("      lookup_snapshot_valid <= 1'b0;")
    first = text.rfind('  always_ff', 0, assignment)
    begin = text.index('begin', first)
    depth = 0
    for token in re.finditer(r'\bbegin\b|\bend\b', text[begin:]):
        depth += 1 if token[0] == 'begin' else -1
        if depth == 0:
            return text[first:begin + token.end()]
    raise RuntimeError('找不到快照保存过程')


def model(root: Path, name: str) -> str:
    text = source_path(root).read_text()
    block = clock_block(text)
    block = block.replace('always_ff @(posedge clk or negedge rst_n)', 'always_comb').replace('<=', '=')
    first = text.index('  always_comb begin\n    case (^{fg_state, req_fire, req_valid, request_count})')
    last = text.index('  for (genvar data_way', first)
    selection = text[first:last]
    selection = selection.replace('(speculative_address >> RAM_BANK_SHIFT) == (fill_word_address >> RAM_BANK_SHIFT)',
                                  'raw_address_conflict')
    selection = selection.replace('fill_set == lookup_read_set', 'raw_fill_match')
    candidate = ''
    if '  logic [3:0] lookup_candidate_snapshot_ready;' in text:
        first = text.index('  logic [3:0] lookup_candidate_snapshot_ready;')
        last = text.index('  // 快照内容在时钟边沿保存', first)
        candidate = text[first:last]
    return f'''module {name} #(parameter int DQ_CW=2)({PORTS},output logic lookup_snapshot_valid);
wire metadata_enable=!(cfg_valid && cfg_ready);
logic lookup_fill_match,spec_read_conflict;
{selection}
{candidate}
{block}
endmodule
'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    roots = {'reference': args.reference_root.resolve(), 'current': args.source_root.resolve()}
    models = out / 'snapshot.sv'
    names = re.sub(r'input logic(?: \[[^\]]+\])? ', '', PORTS).replace('\n', '').replace(' ', '').split(',')
    connections = ','.join(f'.{name}({name})' for name in names)
    models.write_text(''.join(model(root, name) for name, root in roots.items()) + f'''
module comparison #(parameter int DQ_CW=2)({PORTS},output logic equivalent);
logic expected,actual;
reference #(.DQ_CW(DQ_CW)) u_reference({connections},.lookup_snapshot_valid(expected));
current #(.DQ_CW(DQ_CW)) u_current({connections},.lookup_snapshot_valid(actual));
assign equivalent=expected===actual;
endmodule
''')
    reports = []
    for width in (1, 2, 3, 4):
        script, log = out / f'count_width_{width}.ys', out / f'count_width_{width}.log'
        script.write_text(f'read_slang --top comparison -GDQ_CW={width} ' + shlex.quote(str(models)) +
                          '\nprep -top comparison -flatten\ncheck -assert\n'
                          'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        with log.open('w') as stream:
            completed = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                        '--worker', str(script)], stdout=stream,
                                       stderr=subprocess.STDOUT, timeout=60)
        if completed.returncode or 'SUCCESS!' not in log.read_text():
            raise RuntimeError('快照条件证明未完成: ' + str(log))
        reports.append({'count_width': width, 'passed': True})
    bench = out / 'four_state.sv'
    bench.write_text(f'''module tb;
logic rst_n,cfg_valid,cfg_ready,req_fire,req_valid,ram_wen,metadata_fill_good,raw_address_conflict,raw_fill_match;
logic [1:0] fg_state,request_count,lookup_candidate_select;
logic [3:0] lookup_candidate_conflict,lookup_candidate_fill_match;
logic equivalent;
logic [31:0] rng=32'h134dea26,values;
integer checks=0;
comparison dut({connections},.equivalent(equivalent));
initial begin
  for(integer sample=0;sample<200000;sample++) begin
    rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);values=rng;
    for(integer bit_index=0;bit_index<32;bit_index++) begin
      if ((bit_index+integer'(rng[4:0]))%11==0) values[bit_index]=1'bx;
      if ((bit_index+integer'(rng[9:5]))%17==0) values[bit_index]=1'bz;
    end
    {{{','.join(names)}}}=values[22:0];
    #1;
    if(equivalent!==1'b1)$fatal(1,"snapshot update differs sample=%0d",sample);
    checks++;
  end
  $display("CACHE_SNAPSHOT_FOUR_STATE_PASS checks=%0d",checks);$finish;
end
endmodule
''')
    binary = out / 'four_state.vvp'
    compiler = shutil.which('iverilog') or '/home/agent/.local/bin/iverilog'
    runner = shutil.which('vvp') or '/home/agent/.local/bin/vvp'
    compile_result = subprocess.run([compiler, '-g2012', '-s', 'tb', '-o', str(binary),
                                     str(models), str(bench)], capture_output=True, text=True)
    (out / 'compile.log').write_text(compile_result.stdout + compile_result.stderr)
    compile_result.check_returncode()
    completed = subprocess.run([runner, str(binary)], capture_output=True, text=True, timeout=120)
    (out / 'four_state.log').write_text(completed.stdout + completed.stderr)
    completed.check_returncode()
    match = re.search(r'CACHE_SNAPSHOT_FOUR_STATE_PASS checks=(\d+)', completed.stdout)
    if not match:
        raise RuntimeError('快照四态比较未完成')
    result = {'passed': True, 'input_constraints': False, 'profiles': reports,
              'four_state_comparisons': int(match[1]),
              'source_sha256': {name: hashlib.sha256(source_path(root).read_bytes()).hexdigest()
                                for name, root in roots.items()},
              'model_sha256': hashlib.sha256(models.read_bytes()).hexdigest(),
              'comparison_boundaries': 'all candidate comparison bits and selection controls are free inputs'}
    (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
