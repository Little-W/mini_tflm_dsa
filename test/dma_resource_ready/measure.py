#!/usr/bin/env python3
"""测量生产 DMA 资源资格与仲裁优先选择连接后的完整组合路径。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CHECK = runpy.run_path(str(HERE / 'check.py'))
GRANT = runpy.run_path(str(ROOT / 'test/window_dma_grant/check.py'))


def cone(arbiter, dma):
    inputs = [('rd_grant_client', 3), ('rd_pending_count_q', 3),
              ('rd_dma_start_q', 1), ('rd_dma_im2col_q', 1), ('conv_cfg_valid', 1),
              ('local_abort', 1), ('conv_job_q', 1), ('rst_n', 1), ('rd_dma_start', 1),
              ('win_req_valid', 1), ('win_req_ready', 1), ('win_busy', 1),
              ('ia_req', 1), ('kernel_req', 1), ('quant_req_eff', 1), ('bias_req', 1), ('dw_req', 1),
              ('conv_active', 1), ('conv_pending', 1), ('linear_busy', 1), ('linear_finish', 1),
              ('fe_busy', 1), ('job_conv', 1), ('linear_start_ready', 1),
              ('fe_output_valid', 1), ('guard_idle', 1), ('mux_idle', 1), ('inflight', 10)]
    width = sum(bits for _, bits in inputs)
    declarations = '\n'.join(f'    wire [{bits-1}:0] {name};' for name, bits in inputs)
    constants = re.search(r'    typedef enum logic \[2:0\] \{.*?\} client_e;', arbiter, re.S)[0]
    start = arbiter.rfind('    always_comb begin', 0, arbiter.index('rd_next_client = C_NONE;'))
    end = arbiter.index('    // 当前描述符交付', start)
    priority = arbiter[start:end]
    assignments = '\n'.join(CHECK['assignment'](arbiter, name) for name in
                            ('rd_pending_count', 'rd_active', 'dma_conv_cfg_valid', 'rd_reservation_space'))
    names = ['image_start_ready', 'rd_start_ready']
    if re.search(r'\bassign\s+rd_resource_ready\s*=', dma):
        names = ['image_resource_ready', 'image_start_ready', 'rd_resource_ready', 'rd_start_ready']
    resources = '\n'.join(CHECK['assignment'](dma, name) for name in names)
    replacements = {'conv_cfg_valid': 'dma_conv_cfg_valid', 'rd_im2col': 'rd_dma_im2col_q',
                    'rd_start_ready': 'rd_dma_start_ready', 'rd_resource_ready': 'rd_dma_resource_ready'}
    for old, new in replacements.items():
        resources = re.sub(r'\b' + old + r'\b', new, resources)
    state = GRANT['region'](arbiter).replace('o_next', 'grant_next')
    body = f'''// 两个生产模块的资源资格、配置关系和完整授予更新逻辑。
module ready_grant_cone (
    input wire [{width-1}:0] conditions, // 当前请求、资源、配置和授予状态
    output wire [7:0] result // 下一授予、后续请求方以及两类命令接收资格
);
{constants}
{declarations}
    wire [3:0] rd_pending_count;
    wire rd_active, dma_conv_cfg_valid, rd_reservation_space;
    wire image_resource_ready, image_start_ready, rd_dma_resource_ready, rd_dma_start_ready;
    wire [1:0] rd_client_inflight [5];
    client_e rd_next_client;
    logic [2:0] grant_next;
    assign {{{','.join(name for name, _ in inputs)}}} = conditions;
    for (genvar index = 0; index < 5; index++) begin : g_counts
        assign rd_client_inflight[index] = inflight[2*index +: 2];
    end
{assignments}
{resources}
{priority}
{state}
    assign result = {{grant_next, rd_next_client, image_start_ready, rd_dma_start_ready}};
endmodule

// 使用输入与输出寄存器限定资源资格及授予选择的连接路径。
module measure (
    input wire clk, // 同步测量时钟
    input wire [{width-1}:0] conditions, // 独立变化的全部条件输入
    output logic [7:0] result // 寄存后的完整结果
);
    logic [{width-1}:0] conditions_q;
    wire [7:0] result_d;
    always_ff @(posedge clk) begin
        conditions_q <= conditions;
        result <= result_d;
    end
    ready_grant_cone u_cone(.conditions(conditions_q), .result(result_d));
endmodule
'''
    return body, width


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='7c2942ea')
    parser.add_argument('--dma-reference', default='8009b2f7')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    cases, hashes = {}, {}
    for label in ('reference', 'current'):
        arbiter = (CHECK['reference'](args.reference, CHECK['ARBITER']) if label == 'reference'
                   else (ROOT / CHECK['ARBITER']).read_text())
        dma = (CHECK['reference'](args.dma_reference, CHECK['DMA']) if label == 'reference'
               else (ROOT / CHECK['DMA']).read_text())
        source, width = cone(arbiter, dma)
        path = out / (label + '.sv')
        path.write_text(source)
        hashes[label] = {'arbiter': hashlib.sha256(arbiter.encode()).hexdigest(),
                         'dma': hashlib.sha256(dma.encode()).hexdigest(),
                         'extracted_source': CHECK['digest'](path)}
        cases[label] = {'top': 'measure', 'sources': [str(path)],
                        'options': ['-DSYNTHESIS=1', '-DXILINX_FPGA=1'],
                        'configuration': '完整 DMA 接收资源与仲裁授予选择，全部输入和输出寄存'}
    config = out / 'cases.json'
    config.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + '\n')
    subprocess.run([sys.executable, ROOT / 'scripts/fpga/open_fpga_synth.py',
                    '--case-config', config, '--cases', *cases, '--through', 'pre_lut',
                    '--out', out / 'mapping'], cwd=ROOT, check=True)
    results = {}
    for label in cases:
        cost = out / label
        subprocess.run([sys.executable, ROOT / 'scripts/fpga/remap_fpga_luts.py',
                        '--source', out / 'mapping' / label, '--out', cost, '--mode', 'physical-cost',
                        '--delay-target-ps', '6667', '--wire-delay-ps', '300', '--max-lut-inputs', '8'],
                       cwd=ROOT, check=True)
        metrics = json.loads((cost / 'metrics.json').read_text())
        sys.path.insert(0, str(ROOT / 'scripts/fpga'))
        from netlist_metrics import connected_paths
        module = json.loads((cost / 'mapped.json').read_text())['modules']['measure']
        grant_bits = set(module['netnames']['conditions_q']['bits'][-3:])
        result_bits = set(module['ports']['result']['bits'][5:8])
        feedback = connected_paths(module,
            root_filter=lambda name, cell, port: bool(set(cell['connections'].get('Q', [])) & grant_bits),
            sink_filter=lambda name, cell, port: bool(set(cell['connections'].get('Q', [])) & result_bits))
        results[label] = {'resources': metrics['resources'], 'paths': metrics['paths'],
                          'grant_feedback_paths': feedback,
                          'verification': json.loads((cost / 'verification.json').read_text()),
                          'mapped_sha256': CHECK['digest'](cost / 'mapped.json')}
    report = {'scope': 'Connected resource readiness and complete grant-selection expressions',
              'source_sha256': hashes, 'independent_input_bits': width, 'cases': results,
              'measurement_script_sha256': CHECK['digest'](Path(__file__))}
    (out / 'measurement.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({label: {'logic_lut': result['resources']['logic_lut_cells'],
                              'maximum_cells': result['paths']['longest_register_path_cells']}
                      for label, result in results.items()}), flush=True)


if __name__ == '__main__':
    main()
