#!/usr/bin/env python3
"""检查实际矩阵引擎偏置资格表达式的二态等价及四态传播。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/top/npu_matrix_engine.sv')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def model(source, name):
    first = source.index('        assign bias_zero_i_base')
    last = source.index('    assign exec_dst_base', first)
    if '    localparam int unsigned p_bias_zero_groups' in source:
        flags_first = source.index('    localparam int unsigned p_bias_zero_groups')
        flags_last = source.index('    assign exec_bias_address', flags_first)
        flags = source[flags_first:flags_last]
    else:
        flags = '''
 assign bias_base_nonzero = i_bias_base != p_reg_width'(0);
 assign controller_bias_base_nonzero = p_controller_bias_w'(i_bias_base) != p_controller_bias_w'(0);
'''
    return f'''module {name} #(parameter p_reg_width=32,
 parameter p_controller_bias_w=p_reg_width<32?p_reg_width:32)(
 input logic [p_reg_width-1:0] i_bias_base, // 任意偏置地址
 input logic [31:0] exec_channel, // 任意当前帧的通道坐标
 input logic o_frame_mode_q, // 启用帧执行
 input logic o_is_mode, // 采用输入驻留数据流
 input logic ws_final_bias, // 在最终归约时加入权重驻留偏置
 input logic frame_exec_final, // 当前帧为最后归约帧
 input logic frame_exec_init, // 当前帧为初始化帧
 output logic [p_reg_width-1:0] controller_i_bias_base, // 控制器可见的偏置存在条件
 output logic [1:0] address_flags // 完整地址与控制器可见地址的非零标志
);
 logic [p_controller_bias_w-1:0] bias_zero_i_base,bias_zero_i_offset,bias_zero_i_target;
 logic bias_zero_i_carry,bias_zero_o_equal,exec_bias_present;
 logic bias_base_nonzero,controller_bias_base_nonzero;
 assign address_flags = {{bias_base_nonzero,controller_bias_base_nonzero}};
'''+flags+source[first:last]+'\nendmodule\n'


def execute(command, log):
    with log.open('w') as stream:
        subprocess.run(list(map(str, command)), cwd=ROOT, check=True,
                       stdout=stream, stderr=subprocess.STDOUT, timeout=180)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='0dae72bd')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(); out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    reference = subprocess.check_output(['git','show',args.reference+':'+str(SOURCE)],cwd=ROOT,text=True)
    current = (ROOT/SOURCE).read_text()
    core = model(reference,'original')+model(current,'selected')
    wrapper = '''module comparison #(parameter p_reg_width=32)(
 input logic [p_reg_width-1:0] i_bias_base, // 任意偏置地址
 input logic [31:0] exec_channel, // 任意当前通道坐标
 input logic o_frame_mode_q, // 任意帧执行模式
 input logic o_is_mode, // 任意数据流模式
 input logic ws_final_bias, // 任意最终偏置资格
 input logic frame_exec_final, // 任意末帧标志
 input logic frame_exec_init, // 任意首帧标志
 output logic equivalent // 两种结构的控制器偏置资格相同
);
 wire [p_reg_width-1:0] original_base,selected_base;
 wire [1:0] original_flags,selected_flags;
 original #(.p_reg_width(p_reg_width)) u_original(.controller_i_bias_base(original_base),.address_flags(original_flags),.*);
 selected #(.p_reg_width(p_reg_width)) u_selected(.controller_i_bias_base(selected_base),.address_flags(selected_flags),.*);
 assign equivalent=({original_base,original_flags}=={selected_base,selected_flags});
endmodule
'''
    source = out/'comparison.sv'; source.write_text(core+wrapper)
    resolve = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    sources = resolve([source], ROOT)
    formal = []
    for width in [1,16,31,32,33,64]:
        script,log = out/f'w{width}.ys',out/f'w{width}.log'
        script.write_text('read_slang --top comparison '+shlex.join([f'-Gp_reg_width={width}',*map(str,sources)])+
            '\nprep -top comparison -flatten\nsat -verify -prove equivalent 1\n')
        execute([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--worker',script],log)
        assert 'SUCCESS!' in log.read_text()
        formal.append({'width':width,'passed':True,'log_sha256':digest(log)})
    bench = core+'''module tb;
 reg [63:0] address;
 reg [31:0] channel;
 reg [4:0] flags;
 integer checks=0;
 reg [31:0] rng=32'h8a67139d;
 function automatic [31:0] random_word;
  rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);return rng;
 endfunction
 function automatic logic four(input logic [1:0] v);
  case(v)0:four=0;1:four=1;2:four=1'bx;3:four=1'bz;endcase
 endfunction
'''
    for width in [1,16,31,32,33,64]:
        bench += f'wire [{width-1}:0] original{width},selected{width};\n'
        bench += f'wire [1:0] original_flags{width},selected_flags{width};\n'
        for label in ['original','selected']:
            bench += f'''{label} #(.p_reg_width({width})) u_{label}{width}(
 .i_bias_base(address[{width-1}:0]),.exec_channel(channel),.o_frame_mode_q(flags[4]),
 .o_is_mode(flags[3]),.ws_final_bias(flags[2]),.frame_exec_final(flags[1]),
 .frame_exec_init(flags[0]),.controller_i_bias_base({label}{width}),.address_flags({label}_flags{width}));
'''
    bench += '''initial begin
 for(integer sample=0;sample<30000;sample++)begin
  address={random_word(),random_word()};channel=random_word();flags=5'(random_word());
  if(sample%7==0)begin address=0;channel=0;end
  if(sample%11==0)address=64'(0)-64'(channel<<2);
  if(sample%5==0)begin
   for(integer b=0;b<64;b++)address[b]=four(2'(random_word()));
   for(integer b=0;b<32;b++)channel[b]=four(2'(random_word()));
   for(integer b=0;b<5;b++)flags[b]=four(2'(random_word()));
  end
  #1;
'''
    for width in [1,16,31,32,33,64]:
        bench += f'  if({{original{width},original_flags{width}}}!=={{selected{width},selected_flags{width}}})$fatal(1,"Bias presence differs width={width}");checks++;\n'
    bench += '''end
 $display("BIAS_PRESENCE_FOUR_STATE_PASS checks=%0d",checks);$finish;
end
endmodule
'''
    path=out/'four_state.sv';path.write_text(bench)
    binary,log=out/'four_state.vvp',out/'four_state.log'
    execute(['iverilog','-g2012','-s','tb','-o',binary,path,
             *[ROOT/'rtl/common'/f for f in ['add_equal.sv','add_equal_bit.sv','add_equal_reduce.sv','zero_reduce.sv']]],
             out/'four_state_compile.log')
    execute(['vvp',binary],log)
    match=re.search(r'BIAS_PRESENCE_FOUR_STATE_PASS checks=(\d+)',log.read_text());assert match
    report={'passed':True,'reference_revision':args.reference,'inputs_constrained':False,
            'source_sha256':digest(ROOT/SOURCE),'formal_profiles':formal,
            'four_state_comparisons':int(match[1]),'four_state_log_sha256':digest(log),
            'test_sha256':digest(Path(__file__))}
    assert current==(ROOT/SOURCE).read_text()
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('BIAS_PRESENCE_PASS',flush=True)


if __name__=='__main__':
    main()
