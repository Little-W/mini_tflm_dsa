#!/usr/bin/env python3
"""测量完整偏置地址判断与计算附属输入就绪条件的组合路径。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    header = '''// 寄存器输入覆盖偏置基址、两种数据流通道和全部控制条件。
module measure(
 input logic clk, // 测量时钟
 input logic [31:0] base, // 偏置字节基址
 input logic [31:0] ws, // 权重驻留通道序号
 input logic [31:0] is_channel, // 输入驻留通道序号
 input logic mode, // 数据流模式
 input logic [7:0] flags, // 帧模式、偏置末帧配置、帧位置、偏置状态、计算尾部和量化状态
 output logic ready // 寄存后的附属输入就绪条件
);
logic [31:0] bq,wq,iq;
logic mq,zero,nz,present,aux;
logic [7:0] fq;
always_ff @(posedge clk) begin
 bq<=base;wq<=ws;iq<=is_channel;mq<=mode;fq<=flags;ready<=aux;
end
(* keep=1 *) logic [5:0] nonzero;
for (genvar group=0;group<6;group++) begin : g_nonzero
 localparam integer p_bits=(32-6*group<6)?32-6*group:6;
 logic group_zero;
 zero_reduce #(.p_width(p_bits)) u_zero(.i_value(bq[6*group+:p_bits]),.o_zero(group_zero));
 assign nonzero[group]=!group_zero;
end
assign nz=|nonzero;
npu_bias_address_zero #(.p_width(32)) u_address(
 .i_base(bq),.i_ws_channel(wq),.i_is_channel(iq),.i_is_mode(mq),.o_zero(zero));
'''
    bodies = {
        'reference': '''assign present=fq[0]?(nz&&((mq||fq[1])?fq[3]:fq[2])&&!zero):nz;
assign aux=fq[6]&&(!present||fq[4]||fq[5])&&fq[7];
''',
        'current': '''(* keep=1 *) logic tail_and_quant;
npu_bias_presence u_presence(
 .i_frame_mode(fq[0]),.i_base_nonzero(nz),.i_is_mode(mq),.i_ws_final_bias(fq[1]),
 .i_frame_final(fq[3]),.i_frame_init(fq[2]),.i_address_zero(zero),
 .i_visible_base_nonzero(nz),.o_present(present));
assign tail_and_quant=fq[6]&&fq[7];
assign aux=tail_and_quant&&(!present||fq[4]||fq[5]);
'''}
    cases = {}
    for name, body in bodies.items():
        source = out/(name+'.sv')
        source.write_text(header+body+'endmodule\n')
        cases[name] = dict(top='measure', sources=[str(source)],
                           options=['-DSYNTHESIS=1', '-DXILINX_FPGA=1'],
                           configuration='完整 32 位偏置地址检查与控制器附属输入资格')
    config = out/'cases.json'
    config.write_text(json.dumps(cases, ensure_ascii=False, indent=2)+'\n')
    subprocess.run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--case-config', config,
                    '--cases', *bodies, '--through', 'pre_lut', '--out', out/'mapping'], check=True)
    results = {}
    for name in bodies:
        cost = out/'cost'/name
        subprocess.run([sys.executable, ROOT/'scripts/fpga/remap_fpga_luts.py',
                        '--source', out/'mapping'/name, '--out', cost, '--mode', 'physical-cost',
                        '--delay-target-ps', '6667', '--wire-delay-ps', '300', '--max-lut-inputs', '8'], check=True)
        results[name] = {item: json.loads((cost/(item+'.json')).read_text())
                         for item in ['manifest', 'metrics', 'verification']}
        results[name]['mapped_sha256'] = hashlib.sha256((cost/'mapped.json').read_bytes()).hexdigest()
    (out/'measurement.json').write_text(json.dumps(dict(top='measure', cases=results),
                                                   ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
