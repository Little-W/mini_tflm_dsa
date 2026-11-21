#!/usr/bin/env python3
"""验证准备列数、相邻字标签共享及并行格式条件。"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[3]
PORTS='''input logic[31:0]addr,word_addr,next_byte_addr,reduction_len,tile_q0,
 input logic[TILE_COUNT_W-1:0]prepared_columns,col_remaining,
 input logic[$clog2(LANES+1)-1:0]chunk_count,
 input logic[LANES:0]chunk_selected,active_lane_allowed_q,column_lane_allowed_q,
 input logic[LANES-1:0]group_lane_allowed,
 input logic word_valid,input_s16,wait_word,past_active_q,narrow_output,word_output_q'''
PARAMS='parameter int LANES=8,WORD_BYTES=8,TILE_COUNT_W=5,NARROW_LANES=4'


def between(text,start,end):
    first=text.index(start);return text[first:text.index(end,first)]


def implementation(text,name):
    settings=between(text,'`ifdef ASIC_SYNTHESIS\n  localparam bit p_short_sum_dsp','  conv_cfg_t c;')
    word=between(text,'  if (LANES <= 8 && LANES <= p_cache_read_bytes) begin : g_short_word_advance','  // 连续读取只在耗尽当前缓存字时发起')
    lanes=between(text,'  for (genvar lane = 0; lane < LANES; lane++) begin : g_word_lane','  // 八位输入的配置偏移范围')
    prepared=between(text,'  if (TILE_COUNT_W < 32','  assign prepared_group_i_a')
    expected='chunk_lane_allowed[lane] = chunk_data_allowed[lane] && column_lane_allowed_q[lane];'
    if expected not in text:raise RuntimeError('Channel assignment missing')
    return f'module implementation_{name} #({PARAMS})({PORTS},\n'+'''
 output logic[TILE_COUNT_W+5*LANES+4:0]result);
 localparam int p_cache_read_bytes=WORD_BYTES;
 localparam int p_word_shift=$clog2(WORD_BYTES);
 localparam int CHUNK_COUNT_W=$clog2(LANES+1);
 localparam int WAIT_WORD=1;
 logic[0:0]state;
 typedef struct packed{logic input_s16;}config_t;config_t c;
 logic[p_word_shift+1:0]byte_offset_sum;
 logic[LANES:0]step_word_boundary,step_saved_hit;
 logic word_boundary,next_byte_saved_hit,chunk_reaches_end;
 logic[TILE_COUNT_W-1:0]prepared_active_columns;
 logic[LANES-1:0]chunk_lane_allowed,word_lane_allowed,chunk_end_lane,chunk_data_allowed;
 logic[LANES-1:0]lane_context_allowed,word_lane_s8,word_lane_s16,chunk_end_s8,chunk_end_s16;
 assign c.input_s16=input_s16;
 assign state={wait_word};
 assign byte_offset_sum={2'b0,addr[p_word_shift-1:0]}+((p_word_shift+2)'(chunk_count)<<c.input_s16);
 for(genvar lane=0;lane<LANES;lane++)begin:g_channel
  assign chunk_lane_allowed[lane]=chunk_data_allowed[lane]&&column_lane_allowed_q[lane];
 end
'''+settings+word+lanes+prepared+'''
 assign result={prepared_active_columns,step_word_boundary,step_saved_hit,word_boundary,
   next_byte_saved_hit,chunk_reaches_end,chunk_data_allowed,word_lane_allowed,chunk_lane_allowed};
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
    helper=args.source_root/'rtl/common/add_equal.sv'
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in(current,reference,helper)}
    sv=args.out/'stream_arithmetic.sv'
    sv.write_text(implementation(current.read_text(),'current')+implementation(reference.read_text(),'reference')+
        f'module proof #({PARAMS})({PORTS},output logic equivalent);\n'+'''
 wire[TILE_COUNT_W+5*LANES+4:0]current_result,reference_result;
 implementation_current #(LANES,WORD_BYTES,TILE_COUNT_W,NARROW_LANES) current(.result(current_result),.*);
 implementation_reference #(LANES,WORD_BYTES,TILE_COUNT_W,NARROW_LANES) reference(.result(reference_result),.*);
 assign equivalent=current_result===reference_result;
endmodule
''')
    profiles=[(1,2,1,1),(1,4,2,1),(2,2,3,1),(2,4,4,2),(3,3,5,2),(3,4,6,3),
        (4,4,8,2),(5,8,16,4),(6,8,17,4),(7,8,23,4),(8,8,24,4),(8,8,27,8),
        (8,8,30,4),(8,8,31,4),(8,8,32,4),(8,8,33,4),(16,16,5,4),
        (8,8,5,4),(8,8,2,4)]
    formal=[]
    for lanes,word_bytes,count_width,narrow_lanes in profiles:
        label=f'l{lanes}_b{word_bytes}_w{count_width}_n{narrow_lanes}'
        params=[f'-GLANES={lanes}',f'-GWORD_BYTES={word_bytes}',f'-GTILE_COUNT_W={count_width}',f'-GNARROW_LANES={narrow_lanes}']
        ys=args.out/(label+'.ys');log=args.out/(label+'.log')
        ys.write_text('read_slang --top proof -DSYNTHESIS=1 -DXILINX_FPGA=1 '+
            shlex.join(params+list(map(str,(helper,sv))))+
            '\nprep -top proof -flatten\ncheck -assert\n'
            'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        with log.open('w')as stream:
            run=subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(ys)],
                stdout=stream,stderr=subprocess.STDOUT,timeout=180)
        if run.returncode or 'SUCCESS!'not in log.read_text():raise RuntimeError(str(log))
        formal.append({'lanes':lanes,'word_bytes':word_bytes,'count_width':count_width,'narrow_lanes':narrow_lanes,
            'passed':True,'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()})
    tb=args.out/'four_state.sv'
    tb.write_text(f'module tb;\n {PARAMS};\n'+PORTS.replace('input ','').replace(',\n ',';\n ')+';\n'+'''
 wire equivalent;
 proof #(LANES,WORD_BYTES,TILE_COUNT_W,NARROW_LANES) dut(.*);
 localparam int PW=169+2*TILE_COUNT_W+$clog2(LANES+1)+4*LANES;
 logic[PW-1:0]pattern;
 initial begin
  for(integer sample=0;sample<12000;sample++)begin
   for(integer bit_index=0;bit_index<PW;bit_index++)pattern[bit_index]=$urandom_range(0,1);
   {addr,word_addr,next_byte_addr,reduction_len,tile_q0,prepared_columns,col_remaining,
    chunk_count,chunk_selected,active_lane_allowed_q,column_lane_allowed_q,group_lane_allowed,
    word_valid,input_s16,wait_word,past_active_q,narrow_output,word_output_q}=pattern;
   if(sample%2==0)word_addr=(addr+32'(sample%24))&(~32'(WORD_BYTES-1));
   if(sample%3==0)reduction_len=tile_q0+32'(sample%31);
   pattern={addr,word_addr,next_byte_addr,reduction_len,tile_q0,prepared_columns,col_remaining,
    chunk_count,chunk_selected,active_lane_allowed_q,column_lane_allowed_q,group_lane_allowed,
    word_valid,input_s16,wait_word,past_active_q,narrow_output,word_output_q};
   if(sample%3==0)pattern[sample%PW]=1'bx;
   if(sample%5==0)pattern[(sample*7)%PW]=1'bz;
   {addr,word_addr,next_byte_addr,reduction_len,tile_q0,prepared_columns,col_remaining,
    chunk_count,chunk_selected,active_lane_allowed_q,column_lane_allowed_q,group_lane_allowed,
    word_valid,input_s16,wait_word,past_active_q,narrow_output,word_output_q}=pattern;
   #1;if(equivalent!==1'b1)$fatal(1,"stream arithmetic four-state sample %0d",sample);
  end
  $display("STREAM_ARITHMETIC_FOUR_STATE_PASS checks=12000");$finish;
 end
endmodule
''')
    # 独立配置分别使用独立文件和仿真进程。
    modes=[('generic',[]),('fpga',['-DXILINX_FPGA=1']),('asic',['-DASIC_SYNTHESIS=1'])]
    def event(task):
        mode,defines,profile=task;lanes,word_bytes,count_width,narrow_lanes=profile
        label=f'{mode}_l{lanes}_b{word_bytes}_w{count_width}_n{narrow_lanes}'
        binary=args.out/(label+'.vvp');log=args.out/(label+'.event.log')
        subprocess.run(['/home/agent/.local/bin/iverilog','-g2012','-s','tb',*defines,
            f'-Ptb.LANES={lanes}',f'-Ptb.WORD_BYTES={word_bytes}',f'-Ptb.TILE_COUNT_W={count_width}',
            f'-Ptb.NARROW_LANES={narrow_lanes}','-o',str(binary),*map(str,(helper,sv,tb))],check=True,capture_output=True)
        run=subprocess.run(['/home/agent/.local/bin/vvp',str(binary)],check=True,capture_output=True,text=True,timeout=90)
        log.write_text(run.stdout+run.stderr)
        if 'checks=12000'not in run.stdout:raise RuntimeError(str(log))
        return {'mode':mode,'lanes':lanes,'word_bytes':word_bytes,'count_width':count_width,'narrow_lanes':narrow_lanes,
            'checks':12000,'passed':True,'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()}
    with ThreadPoolExecutor(max_workers=3)as workers:
        events=list(workers.map(event,[(m,d,p)for m,d in modes for p in profiles]))
    assert hashes=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in(current,reference,helper)}
    report={'passed':True,'source_sha256':hashes,'binary_input_constraints':[],
        'synthesis_configuration':['SYNTHESIS=1','XILINX_FPGA=1'],'formal':formal,
        'event_simulations':events,'four_state_checks':len(events)*12000}
    (args.out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'passed':True,'formal_profiles':len(formal),'four_state_checks':len(events)*12000}))
if __name__=='__main__':main()
