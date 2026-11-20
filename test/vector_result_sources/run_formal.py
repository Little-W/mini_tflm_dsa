#!/usr/bin/env python3
"""在已证明的写入互斥关系下比较结果缓冲的全部存储位。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/conv/vector_engine.sv')


def extract(text):
    first = text.index('  // 串行结果共用字节数据选择')
    last = text.index('  always_ff @(posedge clk or negedge rst_n) begin', first)
    return text[first:last]


def normalized(text):
    return re.sub(r'\s+', '', re.sub(r'//[^\n]*', '', text))


def unit(name, body, enums, proof=False):
    outputs = 'output logic state_equal,valid_mode' if proof else 'output logic signed[31:0] result_buf[TILE]'
    return f'''module {name} #(
parameter int TILE=16,PE_COUNT=8,TILE_INDEX_W=$clog2(TILE+PE_COUNT+1),ACTIVE_COUNT_W=$clog2(TILE+1)
)(input logic clk,rst_n,input logic [5:0] state,input vector_engine_pkg::vector_engine_cfg_t c,
input logic writeback_busy,q_active,input logic [5:0] q_valid,
input logic [TILE_INDEX_W-1:0] q_index_5,compute_index,quant_index,reduce_index,
input logic [ACTIVE_COUNT_W-1:0] active,
input logic soft_out_we,input logic [$clog2(TILE)-1:0] soft_out_index,input logic [7:0] soft_out_data,
input logic avg_done,input logic signed[31:0] add_clamped,avg_power_result,avg_div_result,q_clamped_data,reduce_next,
input logic signed[31:0] pe_result[PE_COUNT],acc_buf[TILE],{outputs});
import vector_engine_pkg::*;
logic depthwise,softmax_s8;
assign depthwise=c.op==DW_S8;assign softmax_s8=c.op==SOFTMAX_S8;
''' + enums + '\n' + body + '\nendmodule\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='b2995131')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (ROOT / SOURCE).read_text()
    reference = read_rtl_source(f'{args.reference}:{SOURCE}', cwd=ROOT, text=True)
    old, new = extract(reference), extract(current)
    if normalized(current.replace(new, old, 1)) != normalized(reference):
        raise RuntimeError('存在尚未比较的 RTL 修改')
    enums = re.search(r'  typedef enum logic \[5:0\].*?} state_t;', current, re.S)[0]
    packages = [ROOT / 'rtl/npu/conv/conv_im2col_pkg.sv', ROOT / 'rtl/npu/conv/vector_engine_pkg.sv']
    proof = out / 'proof.sv'
    body = '''logic signed[31:0] r_data[TILE],n_data[TILE];
logic [32*TILE-1:0] r_bits,n_bits;logic [4:0] modes;
reference #(.TILE(TILE),.PE_COUNT(PE_COUNT)) r(.*, .result_buf(r_data));
current #(.TILE(TILE),.PE_COUNT(PE_COUNT)) n(.*, .result_buf(n_data));
assign r_bits={>>{r_data}};assign n_bits={>>{n_data}};assign state_equal=r_bits==n_bits;
assign modes[0]=depthwise && state!=IDLE && state!=FAILED && state!=DONE && q_active && q_valid[5];
assign modes[1]=softmax_s8 && soft_out_we;
assign modes[2]=(state==ADD_STORE && !writeback_busy && compute_index<TILE_INDEX_W'(active)) ||
    state==AVG_POWER_STORE || (state==AVG_WAIT && avg_done) || (state==VECTOR_REDUCE && reduce_index+1>=TILE);
assign modes[3]=state==EXECUTE_COMMIT && c.op==VEC_HADAMARD && !writeback_busy;
assign modes[4]=state==POOL_STORE;
assign valid_mode=(modes & (modes-5'd1))==5'd0;
'''
    proof.write_text(unit('reference', old, enums) + unit('current', new, enums) + unit('proof', body, enums, proof=True))
    sources = ' '.join(shlex.quote(str(path)) for path in packages + [proof])
    report = {'reference_commit': subprocess.check_output(['git','rev-parse',args.reference],cwd=ROOT,text=True).strip(),
              'source_sha256': hashlib.sha256(current.encode()).hexdigest(),
              'actual_source_expressions': True, 'other_logic_unchanged': True,
              'initial_relation': '两份任意且相同的完整结果存储内容',
              'control_relation': '量化、Softmax、串行结果、并行乘积和池化写入互斥', 'checks': []}
    for tile, pes in ((16,8),(16,4),(8,4),(3,3),(1,1)):
        folder = out / f'tile{tile}_pe{pes}'
        folder.mkdir(exist_ok=True)
        script = folder / 'proof.ys'
        script.write_text(f'read_slang --top proof -GTILE={tile} -GPE_COUNT={pes} {sources}\n'
                          'prep -top proof -flatten\nsat -seq 2 -set-at 1 state_equal 1 -set valid_mode 1 '
                          '-prove-skip 1 -prove state_equal 1 -verify\n')
        log = folder / 'formal.log'
        with log.open('w') as stream:
            subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],
                           cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True)
        if 'SUCCESS!' not in log.read_text():
            raise RuntimeError('结果状态比较未完成')
        report['checks'].append({'tile':tile,'pes':pes,'compared_state_bits':32*tile,'passed':True,
                                'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()})
    cases = {}
    for label, body in (('reference',old),('current',new)):
        source = out / (label+'.sv')
        source.write_text(unit('result_store',body,enums))
        cases[label] = {'top':'result_store','options':['-D','SYNTHESIS=1'],
                        'sources':[str(path) for path in packages]+[str(source)],'configuration':'TILE16 PE8 完整结果存储'}
    (out/'cases.json').write_text(json.dumps(cases,indent=2,ensure_ascii=False)+'\n')
    report['passed']=True
    (out/'summary.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({'passed':True,'checks':len(report['checks'])}),flush=True)


if __name__ == '__main__':
    main()
