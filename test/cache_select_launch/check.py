#!/usr/bin/env python3
"""比较实际替换发送及预取有效位表达式，穷举全部控制输入的四态组合。"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import runpy
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
PORTS = (
    ('capacity_ready', 'select_fill_capacity_ready'),
    ('victim_conflict', 'select_victim_conflict'),
    ('prefetch', 'select_prefetch'),
    ('prefetch_ready', 'select_prefetch_ready'),
    ('demand_ready', 'select_demand_ready'),
    ('hint_busy', 'select_hint_busy'),
    ('fire', 'req_fire'),
    ('set_match', 'select_request_set_match'),
    ('hit', 'lookup_hit'),
)
MODES = {'generic': '`undef SYNTHESIS\n`undef XILINX_FPGA\n',
         'fpga': '`define SYNTHESIS 1\n`define XILINX_FPGA 1\n'}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='3b1c0c5b664d28397dcb257ad8b9cbadea730b6b')
    args = parser.parse_args()
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    path = 'rtl/npu/dma/cache/conv_windowed_cache.sv'
    reference = subprocess.check_output(['git', 'show', args.reference + ':' + path], cwd=ROOT).decode()
    busy_start = reference.index('  conv_cache_select_busy #(.p_prefetch(1\'b1)) u_prefetch_busy')
    busy_end = reference.index('  always_comb begin', busy_start)
    launch_start = reference.index('  logic select_launch_eligible;')
    launch_end = reference.index('    select_way_next=0;', launch_start)
    declarations = ',\n'.join('  input logic ' + name for _, name in PORTS)
    reference_path = out / 'reference.sv'
    reference_path.write_text('module reference(\n' + declarations + ',\n'
        '  output logic select_launch, select_prefetch_launch);\n'
        '  logic select_prefetch_blocked, select_demand_blocked;\n' +
        reference[busy_start:busy_end] + reference[launch_start:launch_end] +
        '  end\n  assign select_prefetch_launch = select_launch && select_prefetch;\nendmodule\n')
    checked_start = reference.index("    else if (cfg_valid && cfg_ready) pf_hit_checked <= 1'b0;")
    checked_end = reference.index('\n  end', checked_start)
    checked_process = reference[checked_start:checked_end].replace('else if', 'if', 1)
    for expression, replacement in (
        ('cfg_valid && cfg_ready', 'control[0]'),
        ('metadata_enable && metadata_fill', 'control[3]'),
        ('fill_set==pf_set', 'control[4]'),
        ('select_set==pf_set', 'control[6]'),
        ('pf_pending', 'control[1]'),
        ('pf_lookup_ready', 'control[2]'),
        ('select_launch', 'control[5]'),
        ('pf_hit_checked', 'next_checked'),
        ('<=', '='),
    ):
        checked_process = checked_process.replace(expression, replacement)
    reference_path.write_text(reference_path.read_text() +
        'module reference_check(input logic [6:0] control, output logic next_checked);\n'
        '  always_comb begin\n' + checked_process + '\n  end\nendmodule\n')
    source = ROOT / 'rtl/npu/dma/cache/conv_cache_select_launch.sv'
    checked = ROOT / 'rtl/npu/dma/cache/conv_cache_prefetch_check.sv'
    busy = ROOT / 'rtl/npu/dma/cache/conv_cache_select_busy.sv'
    resolve = runpy.run_path(str(ROOT / 'scripts/rtl/source_files.py'))['with_dependencies']
    design_sources = resolve([source, checked, busy], ROOT)
    sources = {str(p): digest(p) for p in (*design_sources, reference_path)}
    reference_instance = '  reference old(\n' + ',\n'.join(
        f'    .{name}(stimulus[{index}])' for index, (_, name) in enumerate(PORTS)) + ',\n' + \
        '    .select_launch(expected[0]), .select_prefetch_launch(expected[1]));\n'
    current_instance = '  conv_cache_select_launch dut(\n' + ',\n'.join(
        f'    .i_{short}(stimulus[{index}])' for index, (short, _) in enumerate(PORTS)) + ',\n' + \
        '    .o_launch(actual[0]), .o_prefetch_launch(actual[1]));\n'
    instances = reference_instance + current_instance + '''
  reference_check old_check(.control(stimulus[6:0]), .next_checked(expected[2]));
  conv_cache_prefetch_check dut_check(
    .i_configure(stimulus[0]), .i_pending(stimulus[1]), .i_lookup_ready(stimulus[2]),
    .i_fill_busy(stimulus[3]), .i_fill_set_match(stimulus[4]), .i_launch(stimulus[5]),
    .i_launch_set_match(stimulus[6]), .o_next_checked(actual[2]));
'''
    results = []
    for mode, definitions in MODES.items():
        prefix = definitions + ''.join(f'`include "{p}"\n' for p in (*design_sources, reference_path))
        proof = out / (mode + '_proof.sv')
        proof.write_text(prefix + 'module proof(input logic [8:0] stimulus, output logic [2:0] actual);\n'
            '  wire [2:0] expected;\n' + instances +
            '  always_comb assert(actual == expected);\nendmodule\n')
        script = out / (mode + '.ys')
        script.write_text(f'read_slang --top proof {proof}\n'
            'setattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n'
            'prep -top proof -flatten\nchformal -lower\n'
            'sat -verify -prove-asserts -show-inputs\n')
        formal_log = out / (mode + '_formal.log')
        with formal_log.open('w') as stream:
            subprocess.run([sys.executable, ROOT / 'scripts/fpga/open_fpga_synth.py', '--worker', script],
                           stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=120)
        assert 'SUCCESS' in formal_log.read_text()
        bench = out / (mode + '_tb.sv')
        bench.write_text(prefix + '''
module tb;
  logic [8:0] stimulus;
  wire [2:0] actual, expected;
  integer checks = 0;
  integer launched = 0;
  integer prefetched = 0;
  integer unknown_results = 0;
''' + instances + '''
  function automatic logic value4(input integer value);
    case(value & 3)
      0: value4 = 1'b0;
      1: value4 = 1'b1;
      2: value4 = 1'bx;
      3: value4 = 1'bz;
    endcase
  endfunction
  initial begin
    if ($bits(stimulus) != 9) $fatal(1, "stimulus width");
    for (integer code = 0; code < 262144; code++) begin
      for (integer index = 0; index < 9; index++)
        stimulus[index] = value4(code >> (2 * index));
      #1;
      if (actual !== expected)
        $fatal(1, "select launch code=%0d inputs=%b actual=%b expected=%b",
               code, stimulus, actual, expected);
      checks++;
      if (actual[0] === 1'b1) launched++;
      if (actual[1] === 1'b1) prefetched++;
      if ((^actual) === 1'bx) unknown_results++;
    end
    if (!launched || !prefetched || !unknown_results) $fatal(1, "coverage");
    $display("SELECT_LAUNCH_PASS checks=%0d launched=%0d prefetched=%0d unknown=%0d",
             checks, launched, prefetched, unknown_results);
    $finish;
  end
endmodule
''')
        binary = out / (mode + '.vvp')
        build = subprocess.run([shutil.which('iverilog') or 'iverilog', '-g2012', '-s', 'tb',
                                '-o', str(binary), str(bench)], stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, check=True, timeout=120)
        (out / (mode + '_build.log')).write_text(build.stdout)
        simulation = subprocess.run([shutil.which('vvp') or 'vvp', str(binary)], stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, check=True, timeout=120)
        simulation_log = out / (mode + '_four_state.log'); simulation_log.write_text(simulation.stdout)
        result = re.search(r'SELECT_LAUNCH_PASS checks=(\d+) launched=(\d+) prefetched=(\d+) unknown=(\d+)',
                           simulation.stdout)
        assert result
        checks, launched, prefetched, unknown = map(int, result.groups())
        row = dict(mode=mode, passed=True, input_constraints=[], four_state_checks=checks,
                   coverage=dict(launched=launched, prefetched=prefetched, unknown_results=unknown),
                   formal_log_sha256=digest(formal_log), simulation_log_sha256=digest(simulation_log))
        results.append(row); print(json.dumps(row), flush=True)
    assert all(digest(p) == expected for p, expected in sources.items())
    (out / 'summary.json').write_text(json.dumps(dict(passed=True, reference_commit=args.reference,
        source_sha256=sources, reference_controller_sha256=hashlib.sha256(reference.encode()).hexdigest(),
        runner_sha256=digest(__file__), results=results,
        four_state_checks=sum(row['four_state_checks'] for row in results)), indent=2) + '\n')


if __name__ == '__main__':
    main()
