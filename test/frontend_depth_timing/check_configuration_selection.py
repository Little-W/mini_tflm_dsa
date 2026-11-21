#!/usr/bin/env python3
"""提取前端实际配置选择表达式，比较全部输入并准备独立映射案例。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = Path('rtl/npu/conv/conv_im2col_frontend.sv')
HELPER = Path('rtl/common/add_equal.sv')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unit(source, name, kind):
    if kind == 'group':
        first = source.index('  if (LANES <= 8) begin : g_short_group_lane')
        last = source.index('    for (genvar source = 0; source < 6;', first)
        body = source[first:last].replace('cfg.group_c', 'cfg_group_c') + '  end\n'
        return f'''module {name} #(parameter int LANES=8)(
input logic [31:0] stimulus,output logic [(LANES>4 ? 8 : 4):0] result);
localparam int p_saved_group_lanes=LANES>4 ? 8 : 4;
logic [15:0] cfg_group_c,ch_q;
logic [p_saved_group_lanes:0] group_range_cfg;
assign {{cfg_group_c,ch_q}}=stimulus;
{body}
assign result=group_range_cfg;
endmodule
'''
    first = source.index('  logic [LINE_BYTES:0] cfg_line_threshold')
    last = source.index('  always_ff @(posedge clk or negedge rst_n)', first)
    body = source[first:last].replace('cfg.', 'cfg_')
    return f'''module {name} #(parameter int LINE_BYTES=16)(
input logic [64:0] stimulus,output logic [95:0] result);
logic [15:0] cfg_input_c,cfg_kernel_w,cfg_stride_w,cfg_dilation_w;
logic cfg_input_s16;
logic [31:0] cfg_pixel_bytes,cfg_line_pixels,cfg_pf_step;
assign {{cfg_input_c,cfg_kernel_w,cfg_stride_w,cfg_dilation_w,cfg_input_s16}}=stimulus;
{body}
assign result={{cfg_pixel_bytes,cfg_line_pixels,cfg_pf_step}};
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-root', type=Path)
    parser.add_argument('--reference-expressions', type=Path,
                        default=Path(__file__).with_name('configuration_reference.sv'))
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source_paths = {
        'reference': (args.reference_root.resolve() / FRONTEND if args.reference_root else
                      args.reference_expressions.resolve()),
        'current': args.source_root.resolve() / FRONTEND,
    }
    hashes = {name: digest(path) for name, path in source_paths.items()}
    source = {name: path.read_text() for name, path in source_paths.items()}
    helper = args.source_root.resolve() / HELPER
    cases, runs = {}, []
    for kind, parameter, values, iw, ow in (
        ('group', 'LANES', (1, 2, 4, 5, 7, 8), 32, 9),
        ('prefetch', 'LINE_BYTES', (1, 8, 16, 32, 64, 128), 65, 96),
    ):
        files = []
        for label in source_paths:
            path = out / (kind + '_' + label + '.sv')
            if label == 'reference' and not args.reference_root:
                expression = re.search(r'\bmodule ' + kind + r'_reference\b.*?\bendmodule\b',
                                       source[label], re.S)
                if not expression:
                    raise ValueError('参考表达式模块缺失：' + kind)
                path.write_text(expression[0] + '\n')
            else:
                path.write_text(unit(source[label], kind + '_' + label, kind))
            files.append(path)
            width = ow
            wrapper = out / (kind + '_' + label + '_depth.sv')
            wrapper.write_text(f'''module {kind}_{label}_depth(input logic clk,
input logic [{iw-1}:0] stimulus, output logic [{width-1}:0] result);
logic [{iw-1}:0] input_q;
logic [{width-1}:0] selected_result;
always_ff @(posedge clk)begin input_q<=stimulus;result<=selected_result;end
{kind}_{label} u_select(.stimulus(input_q),.result(selected_result));
endmodule
''')
            cases[kind + '_' + label] = dict(top=kind + '_' + label + '_depth',
                sources=[str(path), str(wrapper)], options=['-DSYNTHESIS=1'],
                configuration='实际配置表达式两端使用普通寄存器，保留完整结果位宽')
        for parameter_value in values:
            folder = out / (kind + str(parameter_value))
            folder.mkdir(exist_ok=True)
            width = (9 if parameter_value > 4 else 5) if kind == 'group' else ow
            formal = folder / 'formal.sv'
            formal.write_text(f'''module comparison(input logic [{iw-1}:0] stimulus,output logic equivalent);
logic [{width-1}:0] reference_result,current_result;
{kind}_reference #(.{parameter}({parameter_value})) u_reference(.stimulus(stimulus),.result(reference_result));
{kind}_current #(.{parameter}({parameter_value})) u_current(.stimulus(stimulus),.result(current_result));
assign equivalent=reference_result==current_result;
endmodule
''')
            script, log = folder / 'formal.ys', folder / 'formal.log'
            script.write_text('read_slang --top comparison ' + ' '.join(
                shlex.quote(str(p)) for p in [helper, *files, formal]) +
                '\nprep -top comparison -flatten\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
            with log.open('w') as stream:
                subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'), '--worker', str(script)],
                               cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=90)
            assert 'SAT proof finished - no model found: SUCCESS!' in log.read_text()
            tb = folder / 'tb.sv'
            tb.write_text(f'''module tb;
reg [{iw-1}:0] stimulus,known;
wire [{width-1}:0] reference_result,current_result;
integer seed=32'h97f31a,checks=0;
{kind}_reference #(.{parameter}({parameter_value})) u_reference(.stimulus(stimulus),.result(reference_result));
{kind}_current #(.{parameter}({parameter_value})) u_current(.stimulus(stimulus),.result(current_result));
task check;
begin #1;checks=checks+1;
if(reference_result!==current_result)$fatal(1,"Configuration mismatch stimulus=%h old=%h new=%h",stimulus,reference_result,current_result);
end endtask
initial begin
for(integer sample=0;sample<64;sample++)begin
for(integer bit_i=0;bit_i<{iw};bit_i++)known[bit_i]=$random(seed);
if(sample==0)known='0;if(sample==1)known='1;
stimulus=known;check();
for(integer bit_i=0;bit_i<{iw};bit_i++)begin
stimulus=known;stimulus[bit_i]=1'bx;check();stimulus=known;stimulus[bit_i]=1'bz;check();
end end
for(integer sample=0;sample<4096;sample++)begin
for(integer bit_i=0;bit_i<{iw};bit_i++)begin
case($random(seed)&15)
0:stimulus[bit_i]=1'bx;1:stimulus[bit_i]=1'bz;default:stimulus[bit_i]=$random(seed);
endcase end
check();end
$display("CONFIGURATION_FOUR_STATE_PASS checks=%0d",checks);$finish;
end endmodule
''')
            executable = folder / 'simulation.vvp'
            with (folder / 'build.log').open('w') as stream:
                subprocess.run(['iverilog', '-g2012', '-s', 'tb', '-o', str(executable),
                                str(helper), *map(str, files), str(tb)], stdout=stream,
                               stderr=subprocess.STDOUT, check=True)
            result = subprocess.run(['vvp', str(executable)], text=True, capture_output=True, timeout=90)
            (folder / 'run.log').write_text(result.stdout + result.stderr)
            assert result.returncode == 0 and 'CONFIGURATION_FOUR_STATE_PASS' in result.stdout, result.stdout
            checks = int(result.stdout.split('checks=')[1].split()[0])
            row = dict(kind=kind, parameter={parameter: parameter_value}, passed=True,
                       strict_four_state_checks=checks, script_sha256=digest(script),
                       formal_log_sha256=digest(log), testbench_sha256=digest(tb),
                       simulation_log_sha256=digest(folder / 'run.log'))
            runs.append(row)
            print(json.dumps(row), flush=True)
    assert hashes == {name: digest(path) for name, path in source_paths.items()}
    (out / 'cases.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2) + '\n')
    summary = dict(passed=True, source_sha256=hashes, helper_sha256=digest(helper),
                   reference_scope=('完整前端源码中的实际表达式' if args.reference_root else
                                    'configuration_reference.sv 的完整组合表达式'),
                   inputs_constrained=False, runs=runs, runner_sha256=digest(Path(__file__)),
                   generated_source_sha256={p.name: digest(p) for p in out.glob('*.sv')})
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
