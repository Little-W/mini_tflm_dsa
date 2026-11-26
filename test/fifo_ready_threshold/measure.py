#!/usr/bin/env python3
"""分别测量容量比较和保留全部数据存储的输出 FIFO。"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--reference',default='07a199ac')
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    reference=subprocess.check_output(['git','rev-parse',args.reference],cwd=ROOT,text=True).strip()
    old=out/'reference.sv';old.write_bytes(subprocess.check_output([
        'git','show',reference+':rtl/npu/writeback/fifo_bank_watermark.sv'],cwd=ROOT))
    wrapper=out/'fifo_threshold_timing.sv'
    wrapper.write_text('''// 为组合容量比较提供明确的输入和输出寄存器。
module fifo_threshold_timing(
    input logic clk, // 比较寄存器使用的工作时钟。
    input logic [5:0] ready, // 已完成写入的存储体数量。
    input logic [5:0] threshold, // 预先准备的接收阈值。
    input logic partial, // 当前存在尚未完成的写入。
    output logic full // 保存容量比较结果。
);
    logic [5:0] ready_q,threshold_q;
    logic partial_q,full_d;
    always_ff @(posedge clk)begin
        ready_q<=ready;threshold_q<=threshold;partial_q<=partial;full<=full_d;
    end
    fifo_bank_watermark #(.p_banks(32),.p_count_width(6),.p_precomputed_threshold(1)) u_threshold(
        .i_reserve(32'd0),.i_ready_banks(ready_q),.i_partial_write(partial_q),
        .i_ready_threshold(threshold_q),.o_full(full_d));
endmodule
''')
    cases={}
    parameters=dict(VLEN=16,BANKS=32,BUS_WIDTH=64,p_cyclic_storage=1,p_precomputed_watermark=1)
    for version in ('reference','current'):
        for scope in ('threshold','fifo'):
            top='fifo_threshold_timing' if scope=='threshold' else 'vec_s8_to_fifo_full'
            sources=([str(old)] if version=='reference' else [])+[
                str(wrapper if scope=='threshold' else ROOT/'rtl/npu/writeback/vec_s8_to_fifo_full.sv')]
            options=['-DSYNTHESIS=1','-DXILINX_FPGA=1']
            if scope=='fifo':options += [f'-G{k}={v}'for k,v in parameters.items()]
            cases[version+'_'+scope]=dict(top=top,sources=sources,options=options,
                configuration='32个输出存储体、预计算阈值、64位总线')
    config=out/'cases.json';config.write_text(json.dumps(cases,ensure_ascii=False,indent=2)+'\n')
    subprocess.run([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--case-config',config,
        '--cases',*cases,'--out',out/'mapping','--through','pre_lut'],cwd=ROOT,check=True)
    rows={}
    for name in cases:
        cost=out/'cost'/name
        subprocess.run([sys.executable,ROOT/'scripts/fpga/remap_fpga_luts.py','--source',out/'mapping'/name,
            '--out',cost,'--mode','physical-cost','--delay-target-ps','6667','--wire-delay-ps','300',
            '--max-lut-inputs','8','--discard-abc9-temporaries'],cwd=ROOT,check=True)
        rows[name]=dict(manifest=json.loads((cost/'manifest.json').read_text()),
            summary=json.loads((cost/'summary.json').read_text()),
            mapped_sha256=hashlib.sha256((cost/'mapped.json').read_bytes()).hexdigest())
        print(name,rows[name]['summary']['resources']['lut_sites_nominal_before_packing'],
              rows[name]['summary']['longest_register_path_cells'],flush=True)
    (out/'measurement.json').write_text(json.dumps(dict(reference_commit=reference,
        parameters=parameters,cases=rows),ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
