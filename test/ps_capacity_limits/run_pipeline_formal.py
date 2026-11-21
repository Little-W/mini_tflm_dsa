#!/usr/bin/env python3
"""证明配置提交时实际顶层寄存值等于参考容量公式。"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

from run_top_formal import ROOT, PARAMETERS, capacity_module
from rtl_reference import read_rtl_source

TOP=Path('rtl/npu/top/npu_top.sv')
FIELDS=('cfg_w_reuse_eff_s2','cfg_ia_reuse_eff_s2','cfg_stream_k_s2',
        'cfg_stream_m_s2','cfg_n_s2','shared_ia_banks_q','ps_control_q')


def harness():
    inputs=',\n'.join('    input logic [31:0] i_'+name for name in FIELDS)
    declarations='\n'.join('    logic [31:0] '+name+';' for name in FIELDS)
    reset='\n'.join('            '+name+" <= '0;" for name in FIELDS)
    capture='\n'.join('                '+name+' <= i_'+name+';' for name in FIELDS)
    text=f'''module configuration_pipeline_formal #(\n{PARAMETERS}) (
    input logic clk, core_rst_n, i_load, i_compact,
    input logic ctrl_sa_ready, frame_scheduler_ready,
{inputs}
);
{declarations}
    logic cfg_compact_s2, cfg_stage2_valid;
    logic [p_rows_width-1:0] i_ps_rows;
    logic [p_frames_width-1:0] i_ps_frames;
    logic i_raw_fits_q, i_long_fits_q;
    logic candidate_raw, candidate_long, candidate_invalid;
    logic candidate_invalid_state, candidate_bank_range, candidate_fire;
    logic [2:0] candidate_phase;
    logic [31:0] candidate_slice;
    logic [63:0] candidate_rows;
    logic reference_raw, reference_long, reference_invalid, reference_bank_range;
    logic [31:0] reference_slice;
    logic [63:0] reference_rows;
    // 配置进入第 2 级后保持至提交；该保持条件对应实际顶层的阶段接收条件。
    always_ff @(posedge clk or negedge core_rst_n) begin
        if (!core_rst_n) begin
            cfg_stage2_valid <= 1'b0;
            cfg_compact_s2 <= 1'b0;
{reset}
        end else begin
            if (candidate_fire) cfg_stage2_valid <= 1'b0;
            if (!cfg_stage2_valid && i_load) begin
                cfg_stage2_valid <= 1'b1;
                cfg_compact_s2 <= i_compact;
{capture}
            end
        end
    end
    capacity_pipeline #(.p_max_rows(p_max_rows), .p_rows_width(p_rows_width),
        .p_frames_width(p_frames_width), .p_total_banks(p_total_banks),
        .p_bank_bytes(p_bank_bytes)) u_candidate (.*,
        .o_raw_calc(candidate_raw), .o_long_calc(candidate_long),
        .o_invalid_calc(candidate_invalid), .o_bank_in_range(candidate_bank_range),
        .o_slice_tiles(candidate_slice), .o_admission_rows(candidate_rows),
        .o_rows_state(i_ps_rows), .o_frames_state(i_ps_frames),
        .o_raw_state(i_raw_fits_q), .o_long_state(i_long_fits_q),
        .o_invalid_state(candidate_invalid_state), .o_fire(candidate_fire),
        .o_phase(candidate_phase));
    capacity_reference #(.p_max_rows(p_max_rows), .p_rows_width(p_rows_width),
        .p_frames_width(p_frames_width), .p_total_banks(p_total_banks),
        .p_bank_bytes(p_bank_bytes)) u_reference (.*,
        .o_raw_calc(reference_raw), .o_long_calc(reference_long),
        .o_invalid_calc(reference_invalid), .o_bank_in_range(reference_bank_range),
        .o_slice_tiles(reference_slice), .o_admission_rows(reference_rows));
`ifdef FORMAL
    always_comb begin
        if (core_rst_n && cfg_stage2_valid) begin
            assert(candidate_fire == (candidate_phase==7 && ctrl_sa_ready && frame_scheduler_ready));
            if (candidate_phase>=2 && reference_bank_range) begin
                assert(i_raw_fits_q==reference_raw);
                assert(i_long_fits_q==reference_long);
            end
            if (candidate_phase>=3) assert(candidate_slice==reference_slice);
            if (candidate_phase>=4) assert(candidate_rows==reference_rows);
            if (candidate_phase>=5) assert(candidate_invalid_state==reference_invalid);
        end
    end
`endif
endmodule
'''
    return text


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--reference',default='e379425d783c7a134e165eb180f0bbf6c0c1a4b0')
    parser.add_argument('--reference-root',type=Path)
    parser.add_argument('--bank-counts',type=int,nargs='+',default=[6,7,8,9])
    parser.add_argument('--bank-bytes',type=int,nargs='+',default=[2048,8192])
    args=parser.parse_args()
    out=args.out.resolve()
    out.mkdir(parents=True,exist_ok=True)
    source=(ROOT/TOP).read_text()
    digest=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
    sources=[out/'candidate.sv',out/'reference.sv',out/'formal.sv',
             ROOT/'rtl/npu/control/ps_capacity_limits.sv',ROOT/'rtl/common/onehot_check.sv',
             ROOT/'rtl/common/parallel_prefix_add.sv', ROOT/'rtl/common/unsigned_compare.sv']
    sources[0].write_text(capacity_module(source,'capacity_pipeline',sequential=True))
    reference_text=((args.reference_root/TOP).read_text() if args.reference_root else
                    read_rtl_source(f'{args.reference}:{TOP}',cwd=ROOT,text=True))
    sources[1].write_text(capacity_module(reference_text,'capacity_reference'))
    sources[2].write_text(harness())
    def commit_phase(text):
        expression=re.search(r'assign cfg_stage2_fire\s*=.*?;',text,flags=re.S)[0]
        return int(re.search(r"cfg_capacity_phase\s*==\s*(?:3'd)?([0-7])",expression)[1])
    report=dict(passed=False,reference=str(args.reference_root.resolve()) if args.reference_root else args.reference,
                source_sha256={str(TOP):digest(ROOT/TOP)},
                reference_source_sha256=hashlib.sha256(reference_text.encode()).hexdigest(),
                generated_sha256={path.name:digest(path) for path in sources},
                proof_scope='Actual configuration counter and captures; arbitrary fields latched at stage-2 entry',
                reset_assumption='First sampled cycle has core_rst_n=0; later reset and ready inputs arbitrary',
                configuration_extra_cycles=commit_phase(source)-commit_phase(reference_text),runs=[])
    for banks in args.bank_counts:
        for bank_bytes in args.bank_bytes:
            folder=out/f'banks{banks}_bytes{bank_bytes}'
            folder.mkdir(exist_ok=True)
            script=folder/'run.ys'
            script.write_text('read_slang --top configuration_pipeline_formal -DFORMAL=1 -DGEMMORA_PS_POOL_BYTES=49152 '+
                              f'-Gp_total_banks={banks} -Gp_bank_bytes={bank_bytes} '+
                              shlex.join(map(str,sources))+'\nprep -top configuration_pipeline_formal -flatten\n'
                              'memory_map\nasync2sync\nopt_clean\nchformal -lower\nopt_clean\n'
                              'sat -seq 2 -tempinduct -maxsteps 12 -set-at 1 core_rst_n 0 '
                              '-prove-asserts -verify -timeout 90\n')
            log=folder/'formal.log'
            with log.open('w') as stream:
                result=subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),
                                       '--worker',str(script)],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,timeout=120)
            text=log.read_text()
            passed=result.returncode==0 and 'Induction step proven: SUCCESS!' in text
            record=dict(banks=banks,bank_bytes=bank_bytes,passed=passed,
                        script_sha256=digest(script),log_sha256=digest(log))
            report['runs'].append(record)
            print(json.dumps(record),flush=True)
            if not passed:
                print(text[-10000:])
                raise RuntimeError('Configuration pipeline proof did not complete')
    if digest(ROOT/TOP)!=report['source_sha256'][str(TOP)]:
        raise RuntimeError('Top source changed during proof')
    report['passed']=True
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':
    main()
