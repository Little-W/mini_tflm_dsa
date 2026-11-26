#!/usr/bin/env python3
"""测量偏置地址完整检查与模式选择的寄存器间组合路径。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='3f1e890234caf2b7b882bd1be2976a8797813b97')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    header = '''// 偏置地址检查的寄存输入与输出测量模块。
module measure(
    input logic clk, // 测量时钟
    input logic [31:0] base, // 偏置字节基址
    input logic [31:0] ws, // 权重驻留通道
    input logic [31:0] is_channel, // 输入驻留通道
    input logic mode, // 数据流模式
    output logic zero // 寄存后的零地址结果
);
logic [31:0] bq,wq,iq;
logic modeq,zero_c;
always_ff @(posedge clk) begin
    bq<=base; wq<=ws; iq<=is_channel; modeq<=mode; zero<=zero_c;
end
'''
    body = '''npu_bias_address_zero #(.p_width(32)) u_match(
    .i_base(bq),.i_ws_channel(wq),.i_is_channel(iq),.i_is_mode(modeq),.o_zero(zero_c));
'''
    reference = out/'reference_bias.sv'
    reference.write_bytes(subprocess.check_output(['git', 'show',
        args.reference+':rtl/npu/top/npu_bias_address_zero.sv'], cwd=ROOT))
    bodies = {'reference': body, 'current': body}
    cases = {}
    for name, body in bodies.items():
        source = out/(name+'.sv')
        source.write_text(header+body+'endmodule\n')
        sources = [str(source), str(reference if name == 'reference' else
            ROOT/'rtl/npu/top/npu_bias_address_zero.sv')]
        cases[name] = {'top': 'measure', 'sources': sources,
            'options': ['-DSYNTHESIS=1', '-DXILINX_FPGA=1'],
            'configuration': '32 位偏置地址完整零值检查'}
    config = out/'cases.json'
    config.write_text(json.dumps(cases, indent=2)+'\n')
    subprocess.run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py',
        '--case-config', config, '--cases', *bodies, '--out', out/'mapping',
        '--through', 'pre_lut'], check=True, cwd=ROOT)
    records = {}
    for name in bodies:
        source, cost = out/'mapping'/name, out/'cost'/name
        subprocess.run([sys.executable, ROOT/'scripts/fpga/remap_fpga_luts.py',
            '--source', source, '--out', cost, '--mode', 'physical-cost',
            '--delay-target-ps', '6667', '--wire-delay-ps', '300',
            '--max-lut-inputs', '8'], check=True, cwd=ROOT)
        module = json.loads((cost/'mapped.json').read_text())['modules']['measure']
        origins = register_origins(source/'pre_lut.il', 'measure')
        for cell_name, cell in module['cells'].items():
            if cell_name in origins:
                cell.setdefault('attributes', {})['fpga_register_origin'] = origins[cell_name]
        records[name] = {
            'manifest': json.loads((cost/'manifest.json').read_text()),
            'summary': json.loads((cost/'summary.json').read_text()),
            'metrics': json.loads((cost/'metrics.json').read_text()),
            'mode_paths': connected_paths(module,
                root_filter=lambda name, cell, port: cell.get('attributes', {}).get('fpga_register_origin') == 'modeq',
                limit=1, group_limit=0),
            'mapped_sha256': hashlib.sha256((cost/'mapped.json').read_bytes()).hexdigest()}
    report = {'top': 'measure', 'address_width': 32, 'reference': args.reference, 'cases': records}
    (out/'measurement.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
