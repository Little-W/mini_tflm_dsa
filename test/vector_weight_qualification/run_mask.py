#!/usr/bin/env python3
"""验证权重字节掩码和写请求非空归并。"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import subprocess
import sys


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command,log):
    with log.open('w')as stream:
        status=subprocess.run(list(map(str,command)),stdout=stream,stderr=subprocess.STDOUT,timeout=600)
    if status.returncode:raise RuntimeError(str(log))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in('source-root','reference-root','tool-root','out'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--iverilog',default='iverilog')
    parser.add_argument('--vvp',default='vvp')
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    rel=Path('rtl/npu/conv/vector_engine.sv');reference=(args.reference_root/rel).read_text();selected=(args.source_root/rel).read_text()
    original_start='  for (genvar channel = 0; channel < TILE; channel++) begin : g_weight_channel'
    selected_start='  localparam int WEIGHT_DMA_GROUPS='
    stop='  if (SHARED_STORAGE_ENABLE) begin : g_shared_weights'
    old_block=original_start+reference.split(original_start,1)[1].split(stop,1)[0]
    new_block=selected_start+selected.split(selected_start,1)[1].split(stop,1)[0]
    recovered=selected.replace(new_block,old_block,1).replace('assign write_capture = weights_i_wr_en && weight_write_nonempty;',
                                                           'assign write_capture = weights_i_wr_en && (|weights_i_wr_mask);',1)
    active_function=re.search(r'  // 有效通道数及逐通道资格共同保存，各数据端口直接读取这些寄存结果。\n  function automatic logic \[ACTIVE_COUNT_W\+TILE-1:0\] active_count_value.*?  endfunction\n',recovered,re.S)[0]
    recovered=recovered.replace(active_function,'',1).replace('  logic [TILE-1:0] active_lane_mask;\n','',1)
    recovered,active_updates=re.subn(r'\{active_lane_mask,active\}\s*<=\s*active_count_value\(([^;]+)\);',r'active<=\1;',recovered)
    assert active_updates==4
    for after,before in (
        ('assign quant_req_mask[lane] = active_lane_mask[lane];',"assign quant_req_mask[lane] = lane<active;"),
        ('accumulator_compute_fire && active_lane_mask[entry] &&',"accumulator_compute_fire && 32'(entry)<active &&"),
        ('state_pool_store && active_lane_mask[entry] &&',"state_pool_store && 32'(entry)<active &&"),
    ):
        assert recovered.count(after)==1
        recovered=recovered.replace(after,before,1)
    recovered=recovered.replace("      for (int lane=0;lane<TILE;lane++) assert(active_lane_mask[lane] === (32'(lane)<active));\n",'',1)
    assert recovered.count('{state_weight_read_phase,state_dw_execute,')==89
    recovered=recovered.replace('{state_weight_read_phase,state_dw_execute,','{state_dw_execute,')
    recovered=recovered.replace('logic [$bits(state_t)+12:0] state_control_value','logic [$bits(state_t)+11:0] state_control_value',1)
    recovered=recovered.replace('        (next_state==OUTPUT_INIT || next_state==DW_EXECUTE || next_state==DW_FINISH),\n','',1)
    recovered=recovered.replace('  logic state_weight_read_phase;\n','',1)
    recovered=recovered.replace('      assert(state_weight_read_phase === (state==OUTPUT_INIT || state==DW_EXECUTE || state==DW_FINISH));\n','',1)
    recovered=recovered.replace('      state_weight_read_phase);','      (state_output_init || state_dw_execute || state_dw_finish));',1)
    state_qualifier = 'logic state_dw_execute;' in recovered
    if state_qualifier:
        # 状态字的独立完整输入检查覆盖保存资格；此处核对其他源码。
        assert recovered.count('{state_dw_execute,state_pool_store,') == 89
        recovered=recovered.replace('{state_dw_execute,state_pool_store,','{state_pool_store,')
        recovered=recovered.replace('logic [$bits(state_t)+11:0] state_control_value','logic [$bits(state_t)+10:0] state_control_value',1)
        recovered=recovered.replace('        next_state==DW_EXECUTE,\n','',1)
        recovered=recovered.replace('  logic state_dw_execute;\n','',1)
        recovered=recovered.replace('      assert(state_dw_execute === (state==DW_EXECUTE));\n','',1)
        recovered=re.sub(r'\bstate_dw_execute\b','state==DW_EXECUTE',recovered)
        recovered=recovered.replace('握手与执行资格同状态一起保存，状态保持时也保持这些寄存输出。',
                                    '对外握手标志与状态同时更新，状态保持时也保持这些寄存输出。',1)
    assert re.sub(r'\s+','',recovered)==re.sub(r'\s+','',reference)
    for statement in('    assign weights_i_wr_data[8*channel+:8] = rd_data[p_dma_lane][7:0];\n',
                     '    assign weight_tap_data[channel] = $signed(weights_o_rd_data[8*channel+:8]);\n'):
        assert old_block.count(statement)==new_block.count(statement)==1
        old_block=old_block.replace(statement,'');new_block=new_block.replace(statement,'')
    header='''module NAME #(parameter integer TILE=16,BUS_BYTES=8,INPUT_INDEX_W=6)(
 input wire [INPUT_INDEX_W-1:0] rd_col_base,
 input wire [$clog2(TILE+1)-1:0] active,
 input wire [BUS_BYTES-1:0] valid,input wire weights_i_wr_en,
 output wire [TILE-1:0] weights_i_wr_mask,output wire write_capture
);
 wire rd_valid[BUS_BYTES];
 for(genvar i=0;i<BUS_BYTES;i++)assign rd_valid[i]=valid[i];
 wire [TILE-1:0] active_lane_mask;
 for(genvar lane=0;lane<TILE;lane++)assign active_lane_mask[lane]=(32'(lane)<active);
'''
    model_text=header.replace('NAME','reference_mask')+old_block+'assign write_capture=weights_i_wr_en&&(|weights_i_wr_mask);\nendmodule\n'
    model_text+=header.replace('NAME','selected_mask')+new_block+'assign write_capture=weights_i_wr_en&&weight_write_nonempty;\nendmodule\n'
    model_text+='''module mask_property #(parameter integer TILE=16,BUS_BYTES=8,INPUT_INDEX_W=6)(
 input wire [INPUT_INDEX_W-1:0] column,
 input wire [$clog2(TILE+1)-1:0] active,
 input wire [BUS_BYTES-1:0] valid,input wire enable,
 output wire identical
);
 wire [TILE-1:0] old_mask,new_mask;
 wire old_capture,new_capture;
 reference_mask #(.TILE(TILE),.BUS_BYTES(BUS_BYTES),.INPUT_INDEX_W(INPUT_INDEX_W)) old_value(column,active,valid,enable,old_mask,old_capture);
 selected_mask #(.TILE(TILE),.BUS_BYTES(BUS_BYTES),.INPUT_INDEX_W(INPUT_INDEX_W)) new_value(column,active,valid,enable,new_mask,new_capture);
 assign identical=({old_mask,old_capture}==={new_mask,new_capture});
endmodule
'''
    model=out/'model.sv';model.write_text(model_text)
    parameters=((16,8,6),(16,4,6),(7,4,5),(2,8,2),(32,16,7),(64,4,3),(4,8,32),(1,1,1))
    profiles=[]
    for tile,lanes,width in parameters:
        script=out/f't{tile}_b{lanes}_w{width}.ys'
        script.write_text(f'read_slang --top mask_property -GTILE={tile} -GBUS_BYTES={lanes} -GINPUT_INDEX_W={width} {model}\n'
                          'prep -top mask_property -flatten\nsat -verify -prove identical 1 -show-inputs -show-outputs\n')
        log=script.with_suffix('.log')
        run([sys.executable,args.tool_root/'scripts/fpga/open_fpga_synth.py','--worker',script],log)
        profiles.append({'tile':tile,'bus_bytes':lanes,'column_width':width,'passed':True,'log_sha256':sha(log)})
    bench=out/'bench.sv'
    text='''module tb;
 logic [31:0] column;
 logic [6:0] active;
 logic [15:0] valid;
 logic enable;
 wire [7:0] identical;
 integer i,j;
 integer unsigned rng=32'h9c083f17;
 function automatic integer unsigned random_next;
  rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);return rng;
 endfunction
 function automatic logic four(input logic[1:0] value);
  case(value)0:four=0;1:four=1;2:four=1'bx;3:four=1'bz;endcase
 endfunction
'''
    for i,(tile,lanes,width)in enumerate(parameters):
        active_width=tile.bit_length()
        text+=f'mask_property #(.TILE({tile}),.BUS_BYTES({lanes}),.INPUT_INDEX_W({width})) p{i}(column[{width-1}:0],active[{active_width-1}:0],valid[{lanes-1}:0],enable,identical[{i}]);\n'
    text+='''initial begin
 for(i=0;i<40000;i++)begin
  column=random_next();active=7'(random_next());valid=16'(random_next());enable=four(2'(random_next()));
  if(i%4==0)column=0;
  if(i%4==1)column=32'(8*(random_next()%8));
  if(i%5==0)for(j=0;j<32;j++)column[j]=four(2'(random_next()));
  if(i%5==1)for(j=0;j<7;j++)active[j]=four(2'(random_next()));
  if(i%5==2)for(j=0;j<16;j++)valid[j]=four(2'(random_next()));
  if(i%5==3)column[random_next()%32]=four(2'(random_next()));
  #1;if(identical!==8'hff)$fatal(1,"权重字节掩码或写入资格不一致");
 end
 $display("WEIGHT_MASK_PASS comparisons=%0d",8*i);$finish;
end
endmodule
'''
    bench.write_text(text);exe=out/'simulation.vvp'
    run([args.iverilog,'-g2012','-s','tb','-o',exe,model,bench],out/'compile.log')
    run([args.vvp,exe],out/'simulate.log')
    report={'passed':True,'source_sha256':sha(args.source_root/rel),'reference_sha256':sha(args.reference_root/rel),
            'profiles':profiles,'input_constraints':'none','four_state_comparisons':320000,
            'source_audit':'Weight byte qualification and reduction checked; saved state flags and active mask checked separately; other statements identical',
            'state_qualifier_updates_checked':89 if state_qualifier else 0,
            'active_mask_relation':'active_lane_mask[lane] == (32\'(lane) < active), separately proved on actual sequential source',
            'active_updates_checked':active_updates,
            'test_sha256':sha(Path(__file__)),'model_sha256':sha(model),'simulation_log_sha256':sha(out/'simulate.log')}
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))


if __name__=='__main__':main()
