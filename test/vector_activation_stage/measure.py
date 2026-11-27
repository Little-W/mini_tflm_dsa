#!/usr/bin/env python3
"""测量量化加法限幅或完整向量引擎的逻辑资源与寄存器组合路径。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = '9e3e5d6a6f47befe6c86aceacad7999923206458'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--scope', choices=('add', 'engine'), default='add')
    parser.add_argument('--reference', default=REFERENCE)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    conv = ROOT / 'rtl/npu/conv'
    resolve = runpy.run_path(str(ROOT / 'scripts/rtl/source_files.py'))['with_dependencies']
    if args.scope == 'engine':
        reference = out / 'reference_engine.sv'
        reference.write_text(subprocess.check_output(
            ['git', 'show', args.reference + ':rtl/npu/conv/vector_engine.sv'], cwd=ROOT, text=True))
        options = ['-DSYNTHESIS=1', '-DXILINX_FPGA=1', '-GTILE=16', '-GBUS_WIDTH=64',
                   '-GPE_COUNT=8', '-GWINDOW_LANES=8', '-GSHARED_STORAGE_ENABLE=1',
                   '-GSHARED_QUANT_ENABLE=0', '-GSHARED_STORAGE_ADDR_WIDTH=12']
        cases = {label: {'top': 'vector_engine', 'sources': list(map(str, resolve([source], ROOT))),
                         'options': options, 'configuration': '16 通道、8 个 PE、64 位总线、共享存储和本地量化'}
                 for label, source in (('reference', reference), ('candidate', conv / 'vector_engine.sv'))}
    else:
        reference = out / 'reference_clamp.sv'
        reference.write_text(subprocess.check_output(
            ['git', 'show', args.reference + ':rtl/npu/conv/vector_activation_clamp.sv'], cwd=ROOT, text=True))
        header = '''// 为限幅逻辑设置完整输入与输出寄存器，用于连接后的组合路径测量。
module add_registers (
    input logic clk, // 统一测量时钟
    input logic [95:0] i_config, // 输出偏移、激活下限和激活上限
    input logic [63:0] i_value, // 已完成舍入的量化加法结果
    output logic [31:0] o_result // 寄存后的完整限幅结果
);
    logic [95:0] config_r;
    logic [63:0] value_r;
    logic [3:0][31:0] result;
    always_ff @(posedge clk) begin
        config_r <= i_config;
        value_r <= i_value;
        o_result <= result[1];
    end
'''
        cases = {}
        for label in ('reference', 'candidate'):
            wrapper = out / (label + '_registers.sv')
            module = 'vector_activation_clamp' if label == 'reference' else 'vector_activation_stage'
            value_port = 'i_add_rounded_value' if label == 'reference' else 'i_add_rounding_value'
            wrapper.write_text(header + '    ' + module + ' u_clamp (\n' + '''
        .clk(clk), .cfg_output_offset(config_r[31:0]),
        .cfg_minimum(config_r[63:32]), .cfg_maximum(config_r[95:64]),
        .i_quantized_value(64'd0),
''' + '        .' + value_port + '''(value_r),
        .i_average_floor(8'd0), .i_average_rounded(8'd0),
        .i_average_divided(9'd0), .o_result(result)
    );
endmodule
''')
            source = reference if label == 'reference' else conv / 'vector_activation_stage.sv'
            sources = [source] if label == 'reference' else resolve([source], ROOT)
            cases[label] = {'top': 'add_registers', 'sources': list(map(str, [*sources, wrapper])),
                            'options': ['-DSYNTHESIS=1', '-DXILINX_FPGA=1'],
                            'configuration': '量化加法限幅，全部配置和数值输入及完整结果输出连接测量寄存器'}
    configuration = out / 'cases.json'
    configuration.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + '\n')
    subprocess.run([sys.executable, ROOT / 'scripts/fpga/open_fpga_synth.py',
                    '--case-config', configuration, '--cases', 'reference', 'candidate',
                    '--out', out, '--through', 'pre_lut'], cwd=ROOT, check=True)
    results = {}
    for label in cases:
        target = out / (label + '_cost')
        subprocess.run([sys.executable, ROOT / 'scripts/fpga/remap_fpga_luts.py',
                        '--source', out / label, '--out', target, '--mode', 'physical-cost',
                        '--delay-target-ps', '6667', '--wire-delay-ps', '300',
                        '--max-lut-inputs', '8'], cwd=ROOT, check=True)
        metrics = json.loads((target / 'metrics.json').read_text())
        results[label] = {'resources': metrics['resources'],
                          'longest_register_path_cells': metrics['paths']['longest_register_path_cells'],
                          'complete_connected_graph': metrics['paths']['graph_complete'],
                          'manifest': json.loads((out / label / 'manifest.json').read_text())}
    report = {'reference_revision': args.reference, 'scope': args.scope, 'results': results,
              'timing_method': '完整映射图的寄存器间组合单元计数；器件频率由 Vivado 时序分析确定',
              'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
