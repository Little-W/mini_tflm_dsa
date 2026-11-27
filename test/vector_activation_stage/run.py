#!/usr/bin/env python3
"""验证向量激活阶段的完整输出、配置采样边沿及四态数值行为。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'rtl/npu/conv'
REFERENCE = '9e3e5d6a6f47befe6c86aceacad7999923206458'
MODES = (
    ('generic', []),
    ('synthesis', ['-DSYNTHESIS=1']),
    ('fpga', ['-DXILINX_FPGA=1']),
    ('fpga_synthesis', ['-DSYNTHESIS=1', '-DXILINX_FPGA=1']),
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(command, log: Path) -> None:
    with log.open('w') as stream:
        subprocess.run(list(map(str, command)), cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=600)


def prepare_reference(out: Path, reference_revision: str) -> tuple[Path, Path]:
    original = subprocess.check_output(
        ['git', 'show', reference_revision + ':rtl/npu/conv/vector_activation_clamp.sv'],
        cwd=ROOT, text=True)
    clamp = out / 'reference_clamp.sv'
    clamp.write_text(original.replace('module vector_activation_clamp (',
                                     'module reference_clamp (', 1))
    current = (BASE / 'vector_activation_stage.sv').read_text()
    header = current[:current.index('\n);') + 3].replace(
        'module vector_activation_stage (', 'module reference_stage (', 1)
    reference = out / 'reference_stage.sv'
    reference.write_text(header + '''
    logic [3:0][31:0] direct_result;
    logic [31:0] add_result;
    reference_clamp u_reference (
        .clk(clk), .cfg_output_offset(cfg_output_offset),
        .cfg_minimum(cfg_minimum), .cfg_maximum(cfg_maximum),
        .i_quantized_value(i_quantized_value),
        .i_add_rounded_value(i_add_rounding_value),
        .i_average_floor(i_average_floor), .i_average_rounded(i_average_rounded),
        .i_average_divided(i_average_divided), .o_result(direct_result)
    );
    // 量化加法整体延迟一拍，其余公开结果保持原有周期。
    always_ff @(posedge clk) add_result <= direct_result[1];
    assign o_result[0] = direct_result[0];
    assign o_result[1] = add_result;
    assign o_result[2] = direct_result[2];
    assign o_result[3] = direct_result[3];
endmodule
`default_nettype wire
''')
    return clamp, reference


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default=REFERENCE)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference_clamp, reference_stage = prepare_reference(out, args.reference)
    current_sources = [BASE / 'vector_activation_clamp.sv', BASE / 'vector_activation_stage.sv']
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in current_sources}
    bench = out / 'tb.sv'
    bench.write_text('''
`timescale 1ns/1ps
// 每次输入变化前后检查全部输出，配置与数值允许独立变化并包含未知位。
module tb;
    reg clk = 0;
    reg signed [31:0] cfg_output_offset, cfg_minimum, cfg_maximum;
    reg signed [63:0] i_quantized_value, i_add_rounding_value;
    reg signed [7:0] i_average_floor, i_average_rounded;
    reg signed [8:0] i_average_divided;
    wire [3:0][31:0] actual, expected;
    integer seed = 261127;
    integer checks = 0;
    reference_stage reference_dut (.o_result(expected), .*);
    vector_activation_stage candidate_dut (.o_result(actual), .*);
    task check_results;
        if (actual !== expected)
            $fatal(1, "向量激活输出不一致，比较次数 %0d：expected=%h actual=%h", checks, expected, actual);
        checks = checks + 1;
    endtask
    initial begin
        for (integer sample = 0; sample < 131072; sample = sample + 1) begin
            cfg_output_offset = $random(seed);
            cfg_minimum = $random(seed);
            cfg_maximum = $random(seed);
            i_quantized_value = {$random(seed), $random(seed)};
            i_add_rounding_value = {$random(seed), $random(seed)};
            i_average_floor = $random(seed);
            i_average_rounded = $random(seed);
            i_average_divided = $random(seed);
            case (sample % 32)
                0: begin cfg_minimum = -128; cfg_maximum = 127; end
                1: begin cfg_minimum = 127; cfg_maximum = -128; end
                2: begin cfg_minimum = cfg_maximum; end
                3: begin i_add_rounding_value = $signed(i_average_divided); end
                4: begin i_quantized_value = 64'h7fffffffffffffff; cfg_output_offset = 127; end
                5: begin i_quantized_value = 64'h8000000000000000; cfg_output_offset = -128; end
                6: i_add_rounding_value = 255;
                7: i_add_rounding_value = -256;
                8: cfg_minimum = 'x;
                9: cfg_maximum = 'z;
                10: cfg_output_offset[sample % 32] = 1'bx;
                11: i_quantized_value[sample % 64] = 1'bz;
                12: i_add_rounding_value[sample % 64] = 1'bx;
                13: i_average_floor[sample % 8] = 1'bz;
                14: i_average_divided[sample % 9] = 1'bx;
                15: i_average_rounded[sample % 8] = 1'bz;
                16: begin i_quantized_value = 'x; i_add_rounding_value = 'z; end
                17: begin i_add_rounding_value = $signed(cfg_maximum[9:0]); end
                18: begin cfg_minimum = $signed(i_average_floor); cfg_maximum = $signed(i_average_divided); end
                19: cfg_output_offset = 0;
                default: begin
                    i_quantized_value = $signed(10'($random(seed)));
                    i_add_rounding_value = $signed(10'($random(seed)));
                    cfg_minimum = $signed(10'($random(seed)));
                    cfg_maximum = $signed(10'($random(seed)));
                    if (sample % 8 == 0) cfg_output_offset[(sample >> 5) % 8] = 1'bx;
                    if (sample % 8 == 1) i_add_rounding_value[(sample >> 5) % 64] = 1'bz;
                    if (sample % 8 == 2) cfg_minimum[(sample >> 5) % 32] = 1'bx;
                    if (sample % 8 == 3) cfg_maximum[(sample >> 5) % 32] = 1'bz;
                end
            endcase
            #1; check_results();
            clk = 1;
            #1; check_results();
            clk = 0;
        end
        $display("PASS comparisons=%0d", checks);
        $finish;
    end
endmodule
''')
    results = []
    for name, flags in MODES:
        commands = []
        for label, top, sources in (
            ('reference', 'reference_stage', [reference_clamp, reference_stage]),
            ('candidate', 'vector_activation_stage', current_sources),
        ):
            commands += ['read_slang --top ' + top + ' ' + shlex.join([*flags, *map(str, sources)]),
                         'prep -top ' + top + ' -flatten', 'opt -full',
                         'rename -top ' + label, 'design -stash ' + label]
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from candidate -as candidate candidate',
                     'equiv_make reference candidate proof', 'hierarchy -top proof',
                     'equiv_simple -seq 2', 'equiv_induct -seq 3', 'equiv_status -assert']
        script, proof_log = out / (name + '.ys'), out / (name + '_formal.log')
        script.write_text('\n'.join(commands) + '\n')
        execute([sys.executable, ROOT / 'scripts/fpga/open_fpga_synth.py', '--worker', script], proof_log)
        if 'Equivalence successfully proven!' not in proof_log.read_text():
            raise RuntimeError(str(proof_log))
        executable = out / (name + '.vvp')
        execute(['iverilog', '-g2012', *flags, '-s', 'tb', '-o', executable,
                 reference_clamp, reference_stage, *current_sources, bench], out / (name + '_compile.log'))
        simulation_log = out / (name + '_four_state.log')
        execute(['vvp', executable], simulation_log)
        if 'PASS comparisons=262144' not in simulation_log.read_text():
            raise RuntimeError(str(simulation_log))
        results.append({'mode': name, 'formal': True, 'four_state_comparisons': 262144,
                        'proof_log_sha256': digest(proof_log),
                        'simulation_log_sha256': digest(simulation_log)})
        print(name + ' PASS', flush=True)
    if hashes != {str(path.relative_to(ROOT)): digest(path) for path in current_sources}:
        raise RuntimeError('验证期间源码发生变化')
    report = {'passed': True, 'reference_revision': args.reference,
              'all_public_output_bits': 128, 'input_assumptions': [],
              'add_result_latency_cycles': 1, 'other_result_latency_unchanged': True,
              'source_sha256': hashes, 'modes': results, 'test_sha256': digest(Path(__file__))}
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'passed': True, 'four_state_comparisons': 1048576}))


if __name__ == '__main__':
    main()
