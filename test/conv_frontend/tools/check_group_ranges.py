#!/usr/bin/env python3
"""验证分组通道边界的共享高位判断。"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[3]


def between(text,start,end):
    first=text.index(start);return text[first:text.index(end,first)]


def implementation(text,name):
    settings=between(text,'`ifdef ASIC_SYNTHESIS\n  localparam bit p_short_sum_dsp','  conv_cfg_t c;')
    group=between(text,'  if (LANES <= 8) begin : g_short_group_lane','  end else if (LANES <= 32768) begin : g_group_lane_range')+'  end\n'
    return '''module implementation_NAME #(parameter int LANES=8,
 parameter int SAVED_LANES=LANES>4?8:4)(
 input logic[15:0]cfg_group,group_count,ch_q,ch0_q,
 input logic[5:0][15:0]group_range_channel,
 input logic[SAVED_LANES:0]group_range_q,
 input logic[LANES-1:0]chunk_lane_allowed,
 output logic[7*(SAVED_LANES+1)+LANES:0]result);
 localparam int p_saved_group_lanes=SAVED_LANES;
 typedef struct packed {logic[15:0]group_c;}config_t;config_t c,cfg;
 logic[SAVED_LANES:0]group_range_cfg;
 logic[5:0][SAVED_LANES:0]group_range_next;
 logic[LANES-1:0]group_lane_allowed;
 logic group_after_chunk;
 logic[16:0]initial_group_remaining;
 assign c.group_c=group_count;
 assign cfg.group_c=cfg_group;
 assign initial_group_remaining={1'b0,c.group_c}-{1'b0,ch0_q};
'''.replace('NAME',name)+settings+group+'''
 assign result={group_range_cfg,group_range_next,group_lane_allowed,group_after_chunk};
endmodule
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,required=True)
    parser.add_argument('--reference-root',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    relative='rtl/npu/conv/conv_im2col_frontend.sv'
    current=args.source_root/relative;reference=args.reference_root/relative
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest()for p in(current,reference)}
    sv=args.out/'group_ranges.sv'
    sv.write_text(implementation(current.read_text(),'current')+implementation(reference.read_text(),'reference')+'''
module proof #(parameter int LANES=8,parameter int SAVED_LANES=LANES>4?8:4)(
 input logic[15:0]cfg_group,group_count,ch_q,ch0_q,
 input logic[5:0][15:0]group_range_channel,
 input logic[SAVED_LANES:0]group_range_q,
 input logic[LANES-1:0]chunk_lane_allowed,
 output logic equivalent);
 wire[7*(SAVED_LANES+1)+LANES:0]current_result,reference_result;
 implementation_current #(LANES,SAVED_LANES) current(.result(current_result),.*);
 implementation_reference #(LANES,SAVED_LANES) reference(.result(reference_result),.*);
 assign equivalent=current_result===reference_result;
endmodule
''')
    formal=[]
    for lanes in range(1,9):
        ys=args.out/f'l{lanes}.ys';log=args.out/f'l{lanes}.log'
        ys.write_text(f'read_slang --top proof -DSYNTHESIS=1 -DXILINX_FPGA=1 -GLANES={lanes} '+
            shlex.quote(str(sv))+'\nprep -top proof -flatten\ncheck -assert\n'
            'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        with log.open('w')as stream:
            run=subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(ys)],
                stdout=stream,stderr=subprocess.STDOUT,timeout=180)
        if run.returncode or 'SUCCESS!'not in log.read_text():raise RuntimeError(str(log))
        formal.append({'lanes':lanes,'passed':True,'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()})
    tb=args.out/'four_state.sv'
    tb.write_text('''module tb;
 parameter int LANES=8,SAVED_LANES=LANES>4?8:4;
 logic[15:0]cfg_group,group_count,ch_q,ch0_q;
 logic[5:0][15:0]group_range_channel;
 logic[SAVED_LANES:0]group_range_q;
 logic[LANES-1:0]chunk_lane_allowed;
 wire equivalent;
 proof #(LANES,SAVED_LANES) dut(.*);
 localparam int PW=160+SAVED_LANES+1+LANES;
 logic[PW-1:0]pattern;
 initial begin
  for(integer sample=0;sample<12000;sample++)begin
   for(integer bit_index=0;bit_index<PW;bit_index++)pattern[bit_index]=$urandom_range(0,1);
   {cfg_group,group_count,ch_q,ch0_q,group_range_channel,group_range_q,chunk_lane_allowed}=pattern;
   if(sample%2==0)for(integer source=0;source<6;source++)group_range_channel[source]=group_count-16'(sample%16);
   if(sample%3==0)ch_q=cfg_group-16'(sample%16);
   if(sample%5==0)ch0_q=group_count-16'(sample%16);
   pattern={cfg_group,group_count,ch_q,ch0_q,group_range_channel,group_range_q,chunk_lane_allowed};
   if(sample%3==0)pattern[sample%PW]=1'bx;
   if(sample%5==0)pattern[(sample*7)%PW]=1'bz;
   {cfg_group,group_count,ch_q,ch0_q,group_range_channel,group_range_q,chunk_lane_allowed}=pattern;
   #1;if(equivalent!==1'b1)$fatal(1,"group range four-state sample %0d",sample);
  end
  $display("GROUP_RANGE_FOUR_STATE_PASS checks=12000");$finish;
 end
endmodule
''')
    modes=[('generic',[]),('fpga',['-DXILINX_FPGA=1']),('asic',['-DASIC_SYNTHESIS=1'])]
    def event(task):
        mode,defines,lanes=task;label=f'{mode}_l{lanes}'
        binary=args.out/(label+'.vvp');log=args.out/(label+'.event.log')
        subprocess.run(['/home/agent/.local/bin/iverilog','-g2012','-s','tb',*defines,f'-Ptb.LANES={lanes}',
            '-o',str(binary),str(sv),str(tb)],check=True,capture_output=True)
        run=subprocess.run(['/home/agent/.local/bin/vvp',str(binary)],check=True,capture_output=True,text=True,timeout=60)
        log.write_text(run.stdout+run.stderr)
        if 'checks=12000'not in run.stdout:raise RuntimeError(str(log))
        return {'mode':mode,'lanes':lanes,'checks':12000,'passed':True,
            'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()}
    with ThreadPoolExecutor(max_workers=3)as workers:
        events=list(workers.map(event,[(m,d,l)for m,d in modes for l in range(1,9)]))
    assert hashes=={str(p):hashlib.sha256(p.read_bytes()).hexdigest()for p in(current,reference)}
    report={'passed':True,'source_sha256':hashes,'binary_input_constraints':[],
        'synthesis_configuration':['SYNTHESIS=1','XILINX_FPGA=1'],'formal':formal,
        'event_simulations':events,'four_state_checks':len(events)*12000}
    (args.out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'passed':True,'formal_profiles':8,'four_state_checks':len(events)*12000}))
if __name__=='__main__':main()
