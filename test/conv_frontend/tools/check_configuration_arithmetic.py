#!/usr/bin/env python3
"""验证前端配置范围与末列条件的完整输入及四态传播。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'test/frontend_pipeline'))
from source_sections import read_module, declarations


def between(text, start, stop):
    first = text.index(start)
    return text[first:text.index(stop, first)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    rtl, text = read_module(args.source_root, 'geometry')
    stream_path, stream_text = read_module(args.source_root, 'stream')
    parent = args.source_root/'rtl/npu/conv/conv_im2col_frontend.sv'
    pkg = args.source_root/'rtl/npu/conv/conv_im2col_pkg.sv'
    helper = args.source_root/'rtl/common/add_equal.sv'
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (rtl,stream_path,parent,pkg,helper)}
    groups = declarations(text, ('cfg_group_within_input', 'cfg_s8_offset_valid'))+between(
        text, '  assign cfg_group_within_input =', '  // 配置乘积经过寄存器后检查溢出。')
    columns = ('logic cfg_output_last,cfg_kernel_last,cfg_incoming_kernel_last;\n'+
        declarations(text, ('cfg_last_output_col', 'cfg_last_kernel_col',
                            'unused_cfg_output_col_carry', 'unused_cfg_kernel_col_carry'))+
        between(text, '  assign {unused_cfg_output_col_carry, cfg_last_output_col}',
                '  // 列号加一后的末列关系'))
    next_group = between(stream_text, '  assign cfg_next_group_low =', '  parallel_prefix_add #(.p_width(33)')
    for statement in (
        "row_wrap_q <= cfg.output_w != 16'd0 && cfg_output_last;",
        "tap_wrap_q <= cfg.kernel_w != 16'd0 && cfg_kernel_last;",
        "incoming_tap_wrap_q <= cfg.kernel_w != 16'd0 && cfg_incoming_kernel_last;",
    ):
        if statement not in parent.read_text():
            raise RuntimeError('Expected configuration consumer missing')
    source = args.out/'configuration.sv'
    source.write_text('''module proof(input conv_im2col_pkg::conv_cfg_t cfg,
 input logic[15:0]ox_q,kx_q,kx0_q,input logic[31:0]q0,output logic equivalent);
 logic[37:0]current_result,reference_result;
 logic[32:0]cfg_next_group,reference_next_group;
 logic[16:0]cfg_next_group_low,cfg_next_group_high,reference_low,reference_high;
 assign reference_low={1'b0,q0[15:0]}+{1'b0,cfg.group_c};
 assign reference_high={1'b0,q0[31:16]}+17'd1;
 assign reference_next_group={reference_low[16]?reference_high:{1'b0,q0[31:16]},reference_low[15:0]};
''' + columns + groups + next_group + '''
 assign current_result={cfg_next_group,cfg_s8_offset_valid,cfg_group_within_input,
   cfg.output_w!=0 && cfg_output_last,
   cfg.kernel_w!=0 && cfg_kernel_last,
   cfg.kernel_w!=0 && cfg_incoming_kernel_last};
 assign reference_result={reference_next_group,
   $signed(cfg.input_offset)>=-127 && $signed(cfg.input_offset)<=128,
   17'(cfg.group_offset)+17'(cfg.group_c)<=17'(cfg.input_c),
   cfg.output_w!=0 && ox_q==cfg_last_output_col,
   cfg.kernel_w!=0 && kx_q==cfg_last_kernel_col,
   cfg.kernel_w!=0 && kx0_q==cfg_last_kernel_col};
 assign equivalent=current_result===reference_result;
endmodule
''')
    script, log = args.out/'configuration.ys', args.out/'configuration.log'
    script.write_text('read_slang --top proof -DSYNTHESIS=1 -DXILINX_FPGA=1 '+
        shlex.join(map(str,(pkg,helper,source)))+
        '\nprep -top proof -flatten\ncheck -assert\n'
        'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
    with log.open('w') as stream:
        run=subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),
            '--worker',str(script)],stdout=stream,stderr=subprocess.STDOUT,timeout=180)
    if run.returncode or 'SUCCESS!' not in log.read_text():
        raise RuntimeError(str(log))
    tb=args.out/'four_state.sv'
    tb.write_text('''module tb;
 conv_im2col_pkg::conv_cfg_t cfg;
 logic[15:0]ox_q,kx_q,kx0_q;
 logic[31:0]q0;
 wire equivalent;
 proof dut(.*);
 logic[$bits(cfg)+80-1:0]pattern;
 integer checks=0;
 initial begin
   for(integer sample=0;sample<20000;sample++)begin
     for(integer bit_index=0;bit_index<$bits(pattern);bit_index++)
       pattern[bit_index]=$urandom_range(0,1);
     if(sample%3==0)pattern[sample%$bits(pattern)]=1'bx;
     if(sample%5==0)pattern[(sample*7)%$bits(pattern)]=1'bz;
     {cfg,ox_q,kx_q,kx0_q,q0}=pattern;
     #1;
     if(equivalent!==1'b1)$fatal(1,"configuration four-state comparison");
     checks++;
   end
   $display("CONFIGURATION_FOUR_STATE_PASS checks=%0d",checks);$finish;
 end
endmodule
''')
    simulations=[]
    for name,defines in [('generic',[]),('fpga',['-DXILINX_FPGA=1']),('asic',['-DASIC_SYNTHESIS=1'])]:
        binary=args.out/(name+'.vvp')
        subprocess.run(['/home/agent/.local/bin/iverilog','-g2012','-s','tb',*defines,
            '-o',str(binary),*map(str,(pkg,helper,source,tb))],capture_output=True,check=True)
        run=subprocess.run(['/home/agent/.local/bin/vvp',str(binary)],capture_output=True,
            text=True,check=True,timeout=60)
        logpath=args.out/(name+'.log');logpath.write_text(run.stdout+run.stderr)
        if 'checks=20000' not in run.stdout:raise RuntimeError('Coverage incomplete')
        simulations.append({'mode':name,'samples':20000,'passed':True,
            'log_sha256':hashlib.sha256(logpath.read_bytes()).hexdigest()})
    if hashes!={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (rtl,stream_path,parent,pkg,helper)}:
        raise RuntimeError('Source changed')
    report={'passed':True,'source_sha256':hashes,'binary_input_constraints':[],
        'synthesis_configuration':['SYNTHESIS=1','XILINX_FPGA=1'],
        'formal_log_sha256':hashlib.sha256(log.read_bytes()).hexdigest(),
        'binary_results':38,'four_state_simulations':simulations,'four_state_samples':60000}
    (args.out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
