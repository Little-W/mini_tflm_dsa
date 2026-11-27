#!/usr/bin/env python3
"""验证窗口目标的实际保存阶段、三种步长匹配以及公开四态结果。"""
import argparse
import hashlib
import json
from pathlib import Path
from source_sections import read_module, declarations, dependencies
import re
import shlex
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'test'))
from four_state_inputs import coverage_declarations, coverage_tasks, parse_coverage


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command,log,timeout=900):
    with log.open('w') as handle:
        subprocess.run(list(map(str,command)),cwd=ROOT,stdout=handle,
                       stderr=subprocess.STDOUT,check=True,timeout=timeout)
    return log.read_text()


PORTS='''(
 input logic clk, // 窗口工作时钟
 input logic rst_n, // 低有效复位
 input logic configure, // 当前边沿保存配置并结束原窗口
 input logic window_write, // 当前上下文满足窗口准备条件
 input logic [15:0] input_group, // 待保存通道组大小
 input logic [15:0] input_kernel_w, // 待保存卷积核宽度
 input logic [15:0] kx0_q, // 当前窗口起点的核列
 input logic [15:0] ky0_q, // 当前窗口起点的核行
 input logic [31:0] q0, // 正在准备的窗口归约起点
 input logic [31:0] tile_q0, // 查询描述符的完整归约序号
 output logic o_valid, // 已保存窗口有效
 output logic [2:0] o_match, // 三种完整目标的查询结果
 output logic [2:0][32:0] o_saved_targets, // 形式检查观察的完整已保存目标
 output logic [2:0] o_saved_eligible, // 形式检查观察的目标位置资格
 output logic [96:0] o_saved_context // 形式检查观察的配置和窗口上下文
);
'''

CONTEXT='''
 logic [15:0] group_c,last_group_channel_q,kernel_w,last_kernel_col_q;
 logic [31:0] window_next_q;
 logic window_prepare_write,valid;
 wire group_nonzero_q=|group_c;
 logic [3:0] incoming_tap_match_o_equal;
 // 配置优先于窗口准备，条件中的未知位沿用过程 if 的事件语义。
 always_comb begin
  window_prepare_write=0;
  if(configure)begin end
  else if(window_write)window_prepare_write=1;
 end
 always_ff @(posedge clk or negedge rst_n)begin
  if(!rst_n)begin
   group_c<=0;last_group_channel_q<=16'hffff;kernel_w<=0;last_kernel_col_q<=16'hffff;valid<=0;
  end else if(configure)begin
   group_c<=input_group;last_group_channel_q<=input_group-16'd1;
   kernel_w<=input_kernel_w;last_kernel_col_q<=input_kernel_w-16'd1;valid<=0;
  end else if(window_prepare_write)valid<=1;
 end
 always_ff @(posedge clk)begin
  if(rst_n&&window_prepare_write)window_next_q<=q0;
 end
 assign o_valid=valid;
 assign o_match=valid?incoming_tap_match_o_equal[3:1]:3'b0;
 assign o_saved_context={group_c,last_group_channel_q,kernel_w,last_kernel_col_q,window_next_q,valid};
'''


def create_models(root,out):
    source,text=read_module(root,'descriptor')
    first=text.index('  assign negative_group =')
    last=text.index('  assign position_i_configure =',first)
    difference=re.search(r'`ifndef SYNTHESIS\s*logic \[32:0\] reduction_difference;.*?`endif',text,re.S)[0]
    block=(declarations(text,('negative_group','target_difference','target_difference_match','target_prepared_match'))+
           difference+'\n'+text[first:last]).replace('c.group_c','group_c').replace('c.kernel_w','kernel_w')
    if '.i_preparing_reduction(q0)' not in block or '.i_saved_reduction(window_next_q)' not in block:
        raise RuntimeError('正式窗口目标实例的准备和查询字段不完整')
    observation='''
 for(genvar index=0;index<3;index++)begin:g_observe
  if(REGISTER_DESCRIPTOR)begin:g_registered
   assign o_saved_targets[index]=g_target[index].g_direct.u_match.target_q;
   assign o_saved_eligible[index]=1'b0;
  end else begin:g_unregistered
   assign o_saved_targets[index]=g_target[index].g_prepared.target_q;
   assign o_saved_eligible[index]=g_target[index].g_prepared.target_eligible;
  end
 end
'''
    reference='''
 logic [16:0] negative_step;
 logic [2:0][32:0] step_value,target_value;
 logic [2:0] target_eligible;
 logic [32:0] difference_value;
 assign negative_step={group_nonzero_q,~last_group_channel_q};
 assign step_value[0]={17'd0,group_c};
 assign step_value[1]={{16{negative_step[16]}},negative_step};
 assign step_value[2]={{15{negative_step[16]}},negative_step,1'b0};
 assign difference_value={1'b0,tile_q0}-{1'b0,window_next_q};
 assign o_saved_targets=target_value;
 assign o_saved_eligible=REGISTER_DESCRIPTOR?3'b0:target_eligible;
 for(genvar index=0;index<3;index++)begin:g_target
  logic [32:0] prepared_value;
  assign prepared_value={1'b0,q0}+step_value[index];
  always_ff @(posedge clk)begin
   if(rst_n&&window_prepare_write)begin
    target_value[index]<=prepared_value;
    target_eligible[index]<=!prepared_value[32]&&
       (index==0?kx0_q<last_kernel_col_q:index==1?kx0_q!=0:
        kernel_w==3&&kx0_q==0&&ky0_q!=0);
   end
  end
`ifdef SYNTHESIS
  assign incoming_tap_match_o_equal[index+1]=REGISTER_DESCRIPTOR?
    ({1'b0,tile_q0}==target_value[index]):
    (target_eligible[index]&&(tile_q0==target_value[index][31:0]));
`else
  always_comb begin
   incoming_tap_match_o_equal[index+1]=difference_value==step_value[index];
   case(^{tile_q0,window_next_q,step_value[index]})
    1'b0,1'b1:incoming_tap_match_o_equal[index+1]={1'b0,tile_q0}==target_value[index];
    default:;
   endcase
  end
`endif
 end
'''
    models=out/'window_match.sv'
    models.write_text('module window_match_actual #(parameter bit REGISTER_DESCRIPTOR=1)'+PORTS+CONTEXT+block+observation+
        '\nendmodule\nmodule window_match_mathematical #(parameter bit REGISTER_DESCRIPTOR=1)'+PORTS+CONTEXT+reference+
        '''\nendmodule
module comparison #(parameter bit REGISTER_DESCRIPTOR=1)(
 input logic clk,rst_n,configure,window_write,
 input logic [15:0] input_group,input_kernel_w,kx0_q,ky0_q,
 input logic [31:0] q0,tile_q0,
 output logic equivalent);
 logic actual_valid,expected_valid;
 logic [2:0] actual_match,expected_match;
 logic [2:0][32:0] actual_targets,expected_targets;
 logic [2:0] actual_eligible,expected_eligible;
 logic [96:0] actual_context,expected_context;
 window_match_actual #(.REGISTER_DESCRIPTOR(REGISTER_DESCRIPTOR)) u_actual(.*,
  .o_valid(actual_valid),.o_match(actual_match),.o_saved_targets(actual_targets),.o_saved_eligible(actual_eligible),.o_saved_context(actual_context));
 window_match_mathematical #(.REGISTER_DESCRIPTOR(REGISTER_DESCRIPTOR)) u_expected(.*,
  .o_valid(expected_valid),.o_match(expected_match),.o_saved_targets(expected_targets),.o_saved_eligible(expected_eligible),.o_saved_context(expected_context));
 assign equivalent=({actual_valid,actual_match}=={expected_valid,expected_match})&&
   (actual_context==expected_context)&&
   (!actual_valid||({actual_targets,actual_eligible}=={expected_targets,expected_eligible}));
endmodule
''')
    return source,models


def bench_text(vectors):
    fields='{rst_n,configure,window_write,input_group,input_kernel_w,kx0_q,ky0_q,q0,tile_q0}'
    text='''module tb;
 logic clk=0,rst_n=0,configure=0,window_write=0;
 logic [15:0] input_group,input_kernel_w,kx0_q,ky0_q;
 logic [31:0] q0,tile_q0;
 logic [1:0] actual_valid,expected_valid;
 logic [1:0][2:0] actual_match,expected_match;
 localparam integer INPUT_W=131;
 logic [INPUT_W-1:0] values;
 logic [31:0] rng=32'h7251abc9,prepared_base=0;
 logic [15:0] active_group=0;
 integer checks=0,configurations=0,preparations=0,holds=0;
 integer positive_matches[0:2];
 for(genvar mode=0;mode<2;mode++)begin:g_mode
  window_match_actual #(.REGISTER_DESCRIPTOR(mode)) u_actual(.*,
   .o_valid(actual_valid[mode]),.o_match(actual_match[mode]),.o_saved_targets(),.o_saved_eligible(),.o_saved_context());
  window_match_mathematical #(.REGISTER_DESCRIPTOR(mode)) u_expected(.*,
   .o_valid(expected_valid[mode]),.o_match(expected_match[mode]),.o_saved_targets(),.o_saved_eligible(),.o_saved_context());
 end
INPUT_COVERAGE
 function automatic [31:0] random_word;
  rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);return rng;
 endfunction
 task check;
 begin
  #1;observe_inputs();
  if({actual_valid,actual_match}!=={expected_valid,expected_match})
   $fatal(1,"Window result differs before edge cycle=%0d",checks);
  clk=1;#1;
  if({actual_valid,actual_match}!=={expected_valid,expected_match})
   $fatal(1,"Window result differs after edge cycle=%0d",checks);
  if(rst_n===1'b1&&configure===1'b1)configurations++;
  if(rst_n===1'b1&&configure===1'b0&&window_write===1'b1)preparations++;
  if(rst_n===1'b1&&configure===1'b0&&window_write===1'b0&&actual_valid[1]===1'b1)holds++;
  for(integer index=0;index<3;index++)if(actual_match[1][index]===1'b1)positive_matches[index]++;
  clk=0;checks++;
 end
 endtask
 initial begin
  for(integer index=0;index<3;index++)positive_matches[index]=0;
  initialize_input_coverage();FIELDS='0;check();
  // 每个独立输入均单独覆盖 0、1、X、Z。
  for(integer state_index=0;state_index<4;state_index++)begin
   for(integer bit_index=0;bit_index<INPUT_W;bit_index++)begin
    values='0;
    case(state_index)0:values[bit_index]=0;1:values[bit_index]=1;
      2:values[bit_index]=1'bx;3:values[bit_index]=1'bz;endcase
    FIELDS=values;check();
   end
  end
  rst_n=0;configure=0;window_write=0;check();rst_n=1;
  for(integer cycle=0;cycle<VECTORS;cycle++)begin
   input_group=random_word();input_kernel_w=3;kx0_q=random_word();ky0_q=random_word();
   configure=cycle%16==0;window_write=cycle%16==1;
   if(configure)begin
    case(cycle%64)0:input_group=0;16:input_group=1;32:input_group=16'hffff;default:;endcase
    active_group=input_group;
   end
   q0=random_word();
   if(window_write)begin
    case(cycle%64)1:q0=0;17:q0=32'hffffffff;33:q0=32'h80000000;default:;endcase
    prepared_base=q0;
   end
   case(cycle%3)
    0:tile_q0=prepared_base+32'(active_group);
    1:tile_q0=prepared_base-32'(active_group);
    2:tile_q0=prepared_base-(32'(active_group)<<1);
   endcase
   if(cycle%5==3)tile_q0[random_word()%32]=1'bx;
   if(cycle%7==4)tile_q0[random_word()%32]=1'bz;
   if(cycle%31==0)input_group[random_word()%16]=1'bx;
   if(cycle%29==1)q0[random_word()%32]=1'bz;
   check();
  end
  if(configurations==0||preparations==0||holds==0)$fatal(1,"Window protocol events are incomplete");
  for(integer index=0;index<3;index++)if(positive_matches[index]==0)$fatal(1,"Window target match was not exercised");
  check_input_coverage();
  $display("WINDOW_MATCH_PASS cycles=%0d comparisons=%0d configure=%0d prepare=%0d hold=%0d matches=%0d,%0d,%0d",
   checks,checks*4,configurations,preparations,holds,positive_matches[0],positive_matches[1],positive_matches[2]);
  $finish;
 end
endmodule
'''
    return text.replace('FIELDS',fields).replace('VECTORS',str(vectors)).replace('INPUT_COVERAGE',
        coverage_declarations('INPUT_W')+coverage_tasks('INPUT_W',fields))


def mapping_inputs(out,sources):
    """保留完整配置及窗口保存寄存器，供独立 FPGA 路径测量使用。"""
    wrapper=out/'registered_window_match.sv';blocks=[];cases={}
    for label in ('actual','mathematical'):
        for registered in (0,1):
            top=f'registered_window_match_{label}'+('' if registered else '_direct')
            blocks.append(f'''// 实际窗口保存和查询关系的寄存器测量入口。
module {top}(
 input logic clk, // 测量时钟
 input logic [130:0] inputs, // 配置、准备及查询完整输入
 output logic o_valid, // 保存的窗口有效结果
 output logic [2:0] o_match // 保存的三种目标匹配结果
);
 logic [130:0] inputs_q;
 logic valid_next;
 logic [2:0] matches_next;
 always_ff @(posedge clk)begin inputs_q<=inputs;o_valid<=valid_next;o_match<=matches_next;end
 window_match_{label} #(.REGISTER_DESCRIPTOR({registered})) u_match(
  .clk(clk),.rst_n(inputs_q[130]),.configure(inputs_q[129]),.window_write(inputs_q[128]),
  .input_group(inputs_q[127:112]),.input_kernel_w(inputs_q[111:96]),
  .kx0_q(inputs_q[95:80]),.ky0_q(inputs_q[79:64]),.q0(inputs_q[63:32]),.tile_q0(inputs_q[31:0]),
  .o_valid(valid_next),.o_match(matches_next),.o_saved_targets(),.o_saved_eligible(),.o_saved_context());
endmodule
''')
            cases[top]=dict(top=top,options=['-DSYNTHESIS=1'],sources=list(map(str,[*sources,wrapper])),
                configuration='131 位完整输入，实际窗口保存寄存器和四位查询输出')
    wrapper.write_text('\n'.join(blocks))
    (out/'cases.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2)+'\n')
    for top in cases:
        run(['iverilog','-g2012','-DSYNTHESIS=1','-s',top,'-o',out/(top+'.vvp'),*sources,wrapper],out/(top+'_compile.log'))
    return wrapper


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,default=ROOT)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--vectors',type=int,default=120000)
    args=parser.parse_args()
    if args.vectors<256:parser.error('--vectors must be at least 256')
    root,out=args.source_root.resolve(),args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    source,models=create_models(root,out)
    sources=dependencies(root,[models])
    tracked=[source,*[path for path in sources if path.is_relative_to(root)]]
    hashes={str(path.relative_to(root)):digest(path) for path in tracked}
    cases=[]
    for mode in ('generic','fpga'):
        for registered in (0,1):
            name=f'{mode}_{registered}'
            flags=[] if mode=='generic' else ['-DSYNTHESIS=1','-DXILINX_FPGA=1']
            script=out/(name+'.ys');log=out/(name+'.log')
            script.write_text('read_slang --top comparison '+shlex.join(flags+[f'-GREGISTER_DESCRIPTOR={registered}',*map(str,sources)])+
              '\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n'
              'prep -top comparison -flatten\nasync2sync\nopt -full\ncheck -assert\n'
              'sat -seq 2 -maxsteps 8 -set-init-zero -tempinduct -verify -prove equivalent 1\n')
            result=run([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--worker',script],log)
            if 'SUCCESS!' not in result:raise RuntimeError(str(log))
            cases.append(dict(mode=mode,register_descriptor=registered,passed=True,unbounded_induction=True,log_sha256=digest(log)))
    bench=out/'tb_window_match.sv';bench.write_text(bench_text(args.vectors))
    run(['iverilog','-g2012','-s','tb','-o',out/'sim',*sources,bench],out/'compile.log')
    numeric=run(['vvp',out/'sim'],out/'numeric.log')
    match=re.search(r'WINDOW_MATCH_PASS cycles=(\d+) comparisons=(\d+) configure=(\d+) prepare=(\d+) hold=(\d+) matches=(\d+),(\d+),(\d+)',numeric)
    if match is None:raise RuntimeError(str(out/'numeric.log'))
    wrapper=mapping_inputs(out,sources)
    if hashes!={str(path.relative_to(root)):digest(path) for path in tracked}:raise RuntimeError('检查期间源码发生变化')
    result=dict(passed=True,source_sha256=hashes,formal=cases,
        four_state=dict(passed=True,cycles=int(match[1]),result_comparisons=int(match[2]),
          input_coverage=parse_coverage(numeric),configuration_events=int(match[3]),window_prepare_events=int(match[4]),
          window_hold_cycles=int(match[5]),positive_matches=list(map(int,match.groups()[5:])),log_sha256=digest(out/'numeric.log')),
        generated_mapping_entries=4,
        generated_sha256={path.name:digest(path) for path in (models,bench,wrapper)},
        scope='配置保存、窗口目标准备及描述符查询的实际时钟关系；两种描述符模式的完整三十三位结果和公开四态匹配')
    (out/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({key:result[key] for key in ('passed','four_state')},ensure_ascii=False))


if __name__=='__main__':main()
