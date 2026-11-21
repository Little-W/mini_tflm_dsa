#!/usr/bin/env python3
"""提取实际配置相位与帧模式表达式，证明各消费阶段的结果和启动周期一致。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
TOP = Path('rtl/npu/top/npu_top.sv')
HELPER = Path('rtl/common/onehot_check.sv')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def section(text, first, last):
    start = text.index(first)
    return text[start:text.index(last, start)]


def model(source, name):
    phase = section(source, '        assign cfg_stage2_fire =',
                    '        always_ff @(posedge clk) begin\n            if (cfg_start_event)')
    shape = section(source, '        logic [REG_WIDTH-1:0] w_reuse_shape_i_value;',
                    '        wire [31:0] frame_slice_tiles_calc =')
    rows = section(source, '        wire [63:0] ps_admission_rows_calc =',
                   '        wire [63:0] ps_admission_words =')
    for marker in ('cfg_capacity_phase==1', 'cfg_capacity_phase==2',
                   'cfg_capacity_phase==3', 'cfg_capacity_phase==4',
                   '.start(cfg_stage2_fire && use_frame_commands_s2)',
                   'frame_mode_q <= use_frame_commands_s2;'):
        if marker not in source:
            raise ValueError('配置消费条件发生变化，需要更新检查：' + marker)
    return f'''module {name} #(parameter int REG_WIDTH=32,
    parameter bit FRAME_EXEC_ENABLED=1'b1)(
    input wire clk,core_rst_n,i_load,ctrl_sa_ready,frame_scheduler_ready,
    input wire [REG_WIDTH-1:0] i_reuse,
    input wire [31:0] i_control,i_slice,
    input wire [63:0] i_rows,
    input wire i_long_fits,
    output logic cfg_stage2_valid,
    output wire cfg_stage2_fire,
    output logic [2:0] cfg_capacity_phase,
    output wire o_use_frames,o_start_frame,o_start_direct,
    output wire [63:0] o_rows,
    output logic o_frame_mode
);
    logic [REG_WIDTH-1:0] cfg_w_reuse_eff_s2;
    logic [31:0] ps_control_q,frame_slice_tiles_s2;
    logic [63:0] ps_max_frame_rows;
    logic ps_long_capacity_fits;
    localparam int SIZE_SHIFT=4;
{phase}
{shape}
{rows}
    // 输入在配置进入第二级时保存；容量与分片按实际相位产生。
    always_ff @(posedge clk or negedge core_rst_n) begin
        if(!core_rst_n) begin
            cfg_stage2_valid<=1'b0;
            cfg_w_reuse_eff_s2<='0;
            ps_control_q<='0;
            o_frame_mode<=1'b0;
        end else begin
            if(cfg_stage2_fire) begin
                cfg_stage2_valid<=1'b0;
                o_frame_mode<=use_frame_commands_s2;
            end
            if(!cfg_stage2_valid && i_load) begin
                cfg_stage2_valid<=1'b1;
                cfg_w_reuse_eff_s2<=i_reuse;
                ps_control_q<=i_control;
            end
        end
    end
    always_ff @(posedge clk) begin
        if(cfg_stage2_valid && cfg_capacity_phase==3'd0)
            ps_max_frame_rows<=i_rows;
        if(cfg_stage2_valid && cfg_capacity_phase==3'd1)
            ps_long_capacity_fits<=i_long_fits;
        if(cfg_stage2_valid && cfg_capacity_phase==3'd2)
            frame_slice_tiles_s2<=i_slice;
    end
    assign o_use_frames=use_frame_commands_s2;
    assign o_start_frame=cfg_stage2_fire && use_frame_commands_s2;
    assign o_start_direct=cfg_stage2_fire && !use_frame_commands_s2;
    assign o_rows=ps_admission_rows;
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-root', type=Path)
    parser.add_argument('--reference-ref', default='aa0a169c')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = (str(args.reference_root.resolve()) if args.reference_root else
                 subprocess.check_output(['git', 'rev-parse', args.reference_ref],
                                         cwd=ROOT, text=True).strip())
    reference_path = args.reference_root.resolve() / TOP if args.reference_root else out / 'reference_input.sv'
    if not args.reference_root:
        reference_path.write_bytes(subprocess.check_output(['git', 'show', f'{reference}:{TOP}'], cwd=ROOT))
    paths = {'candidate': args.source_root.resolve() / TOP,
             'reference': reference_path,
             'helper': args.source_root.resolve() / HELPER}
    hashes = {label: digest(path) for label, path in paths.items()}
    files = []
    for label in ('reference', 'candidate'):
        target = out / (label + '.sv')
        target.write_text(model(paths[label].read_text(), label))
        files.append(target)
    harness = out / 'formal.sv'
    harness.write_text('''module configuration_formal #(
    parameter int REG_WIDTH=32, parameter bit FRAME_EXEC_ENABLED=1'b1)(
    input wire clk,core_rst_n,i_load,ctrl_sa_ready,frame_scheduler_ready,
    input wire [REG_WIDTH-1:0] i_reuse,
    input wire [31:0] i_control,i_slice,
    input wire [63:0] i_rows,input wire i_long_fits,output wire bad
);
    wire reference_valid,candidate_valid,reference_fire,candidate_fire;
    wire [2:0] reference_phase,candidate_phase;
    wire reference_use,candidate_use,reference_frame_start,candidate_frame_start;
    wire reference_direct_start,candidate_direct_start,reference_mode,candidate_mode;
    wire [63:0] reference_rows,candidate_rows;
    reference #(.REG_WIDTH(REG_WIDTH),.FRAME_EXEC_ENABLED(FRAME_EXEC_ENABLED)) r(.*,
        .cfg_stage2_valid(reference_valid),.cfg_stage2_fire(reference_fire),
        .cfg_capacity_phase(reference_phase),.o_use_frames(reference_use),
        .o_start_frame(reference_frame_start),.o_start_direct(reference_direct_start),
        .o_rows(reference_rows),.o_frame_mode(reference_mode));
    candidate #(.REG_WIDTH(REG_WIDTH),.FRAME_EXEC_ENABLED(FRAME_EXEC_ENABLED)) c(.*,
        .cfg_stage2_valid(candidate_valid),.cfg_stage2_fire(candidate_fire),
        .cfg_capacity_phase(candidate_phase),.o_use_frames(candidate_use),
        .o_start_frame(candidate_frame_start),.o_start_direct(candidate_direct_start),
        .o_rows(candidate_rows),.o_frame_mode(candidate_mode));
    assign bad=core_rst_n && (
        {reference_valid,reference_fire,reference_phase,reference_mode,
         reference_frame_start,reference_direct_start} !=
        {candidate_valid,candidate_fire,candidate_phase,candidate_mode,
         candidate_frame_start,candidate_direct_start} ||
        (candidate_valid && candidate_phase>=3'd3 && reference_use!=candidate_use) ||
        (candidate_valid && candidate_phase>=3'd4 && reference_rows!=candidate_rows));
endmodule
''')
    files.extend([harness, paths['helper']])
    report = {'passed': False, 'reference': reference, 'source_sha256': hashes,
              'generated_sha256': {str(path): digest(path) for path in files},
              'scope': '实际相位计数、帧资格公式、目录行数计算和捕获；比较相位三至七的消费值、启动资格及提交后的帧模式',
              'input_values_constrained': False,
              'input_capture': '复用数和控制字在配置进入第二级时保存；行数、容量结果和分片分别在相位零、一、二保存',
              'reset': '第一个采样周期复位，后续复位、输入和就绪信号任意',
              'runs': []}
    for width, enabled in ((1, 0), (1, 1), (8, 1), (16, 1), (32, 0), (32, 1)):
        script = out / f'width{width}_frame{enabled}.ys'
        log = script.with_suffix('.log')
        script.write_text('read_slang --top configuration_formal ' +
            f'-GREG_WIDTH={width} -GFRAME_EXEC_ENABLED={enabled} ' + shlex.join(map(str, files)) +
            '\nprep -top configuration_formal -flatten\nmemory_map\nasync2sync\nopt -full\n' +
            'sat -seq 2 -tempinduct -maxsteps 12 -set-at 1 core_rst_n 0 '
            '-prove bad 0 -verify -timeout 90\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                            '--worker', str(script)], stdout=stream, stderr=subprocess.STDOUT,
                           check=True, timeout=120)
        if 'Induction step proven: SUCCESS!' not in log.read_text():
            raise RuntimeError('配置阶段等价检查未完成：' + str(log))
        row = {'REG_WIDTH': width, 'FRAME_EXEC_ENABLED': enabled, 'passed': True,
               'script_sha256': digest(script), 'log_sha256': digest(log)}
        report['runs'].append(row)
        print(json.dumps(row), flush=True)
    if hashes != {label: digest(path) for label, path in paths.items()}:
        raise RuntimeError('验证期间源码发生变化')
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
