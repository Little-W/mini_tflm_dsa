#!/usr/bin/env python3
"""检查配置准备、等待和复位期间实际容量寄存级的四态行为。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from run_pipeline_formal import ROOT, TOP, FIELDS, harness
from run_top_formal import capacity_module
from rtl_reference import read_rtl_source


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--reference',default='e379425d783c7a134e165eb180f0bbf6c0c1a4b0')
    parser.add_argument('--iverilog',default='iverilog')
    parser.add_argument('--vvp',default='vvp')
    args=parser.parse_args()
    out=args.out.resolve()
    out.mkdir(parents=True,exist_ok=True)
    source=(ROOT/TOP).read_text()
    sources=[out/'candidate.sv',out/'reference.sv',out/'harness.sv',out/'tb.sv',
             ROOT/'rtl/npu/control/ps_capacity_limits.sv',ROOT/'rtl/common/onehot_check.sv']
    sources[0].write_text(capacity_module(source,'capacity_pipeline',sequential=True))
    sources[1].write_text(capacity_module(read_rtl_source(f'{args.reference}:{TOP}',cwd=ROOT,text=True),
                                        'capacity_reference'))
    sources[2].write_text(harness())
    declarations='\n'.join('    logic [31:0] i_'+field+" = '0;" for field in FIELDS)
    sources[3].write_text('''`timescale 1ns/1ps
module pipeline_tb #(parameter integer BANKS=7);
    logic clk=0, core_rst_n=0, i_load=0, i_compact=0;
    logic ctrl_sa_ready=0, frame_scheduler_ready=0;
'''+declarations+'''
    integer submissions=0, stalls=0, checks=0, resets=0;
    integer known_invalid=0, unknown_values=0;
    configuration_pipeline_formal #(.p_total_banks(BANKS)) dut (.*);
    initial begin
        #1;
        for (integer cycle=0;cycle<20000;cycle=cycle+1) begin
            core_rst_n=(cycle%257)!=0;
            if (!core_rst_n) resets=resets+1;
            i_load=$urandom_range(0,1);
            i_compact=$urandom_range(0,1);
            ctrl_sa_ready=$urandom_range(0,1);
            frame_scheduler_ready=$urandom_range(0,1);
            i_cfg_w_reuse_eff_s2=$urandom_range(1,16);
            i_cfg_ia_reuse_eff_s2=1 << $urandom_range(0,5);
            i_cfg_stream_k_s2=$urandom_range(0,2048);
            i_cfg_stream_m_s2=$urandom_range(0,1024);
            i_cfg_n_s2=$urandom_range(0,256);
            i_shared_ia_banks_q=1 << $urandom_range(0,2);
            i_ps_control_q=$urandom_range(0,63);
            if (cycle%7==0) i_cfg_ia_reuse_eff_s2=$urandom;
            if (cycle%11==0) i_shared_ia_banks_q=$urandom;
            if (cycle%13==0) i_cfg_ia_reuse_eff_s2[3]=1'bx;
            if (cycle%17==0) i_ps_control_q[3:2]=2'bxz;
            if (cycle%19==0) i_cfg_stream_k_s2[6]=1'bz;
            #2;
            if (core_rst_n && dut.cfg_stage2_valid) begin
                if (dut.candidate_phase>=2 && dut.reference_bank_range===1'b1) begin
                    if (dut.i_raw_fits_q !== dut.reference_raw || dut.i_long_fits_q !== dut.reference_long)
                        $fatal(1,"Capacity register mismatch");
                    checks=checks+2;
                end
                if (dut.candidate_phase>=3) begin
                    if (dut.candidate_slice !== dut.reference_slice) $fatal(1,"Slice register mismatch");
                    checks=checks+1;
                end
                if (dut.candidate_phase>=4) begin
                    if (dut.candidate_rows !== dut.reference_rows) $fatal(1,"Directory rows mismatch");
                    checks=checks+1;
                end
                if (dut.candidate_phase>=5) begin
                    if (dut.candidate_invalid_state !== dut.reference_invalid) $fatal(1,"Capacity flag mismatch");
                    checks=checks+1;
                end
                if (dut.candidate_phase==7 && !(ctrl_sa_ready && frame_scheduler_ready)) stalls=stalls+1;
                if (dut.candidate_fire) begin
                    submissions=submissions+1;
                    if (dut.reference_invalid===1'b1) known_invalid=known_invalid+1;
                    if ((^dut.reference_slice===1'bx) || (^dut.reference_rows===1'bx) ||
                        (dut.reference_invalid===1'bx))
                        unknown_values=unknown_values+1;
                end
            end
            clk=1; #2; clk=0;
        end
        if (submissions<100 || stalls<100 || unknown_values<10 ||
            unknown_values==submissions || known_invalid<10)
            $fatal(1,"Configuration coverage incomplete");
        $display("{\\"passed\\":true,\\"banks\\":%0d,\\"cycles\\":20000,\\"submissions\\":%0d,\\"stalls\\":%0d,\\"checks\\":%0d,\\"resets\\":%0d,\\"known_invalid\\":%0d,\\"unknown_values\\":%0d}",
                 BANKS,submissions,stalls,checks,resets,known_invalid,unknown_values);
        $finish;
    end
endmodule
''')
    digest=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
    report=dict(passed=False,reference=args.reference,source_sha256={str(TOP):digest(ROOT/TOP)},
                generated_sha256={path.name:digest(path) for path in sources},runs=[])
    for banks in (6,7,9):
        binary=out/f'banks{banks}.vvp'
        with (out/f'banks{banks}_build.log').open('w') as log:
            subprocess.run([args.iverilog,'-g2012','-DGEMMORA_PS_POOL_BYTES=49152','-s','pipeline_tb',
                            f'-Ppipeline_tb.BANKS={banks}','-o',str(binary),*map(str,sources)],
                           cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
        result=subprocess.run([args.vvp,str(binary)],cwd=ROOT,text=True,capture_output=True,timeout=60,check=True)
        (out/f'banks{banks}.log').write_text(result.stdout+result.stderr)
        record=json.loads(next(line for line in result.stdout.splitlines() if line.startswith('{')))
        report['runs'].append(record)
        print(json.dumps(record),flush=True)
    if digest(ROOT/TOP)!=report['source_sha256'][str(TOP)]:
        raise RuntimeError('Top source changed during comparison')
    report['passed']=True
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':
    main()
