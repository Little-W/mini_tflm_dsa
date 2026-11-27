#!/usr/bin/env python3
"""比较配置跨组位置的完整结果、四态传播和寄存器之间组合级数。"""
from pathlib import Path
import argparse
import hashlib
import json
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT/'rtl/npu/conv/conv_cfg_skip_group.sv'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(script, log):
    with log.open('w') as stream:
        subprocess.run([sys.executable, str(ROOT/'scripts/fpga/open_fpga_synth.py'), '--worker', str(script)],
                       stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=180)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    model = out/'model.sv'
    model.write_text('''module reference_cfg (
  input wire logic [31:0] i_reduction,
  input wire logic [15:0] i_group_channels,
  output logic [32:0] o_result
);
  logic unused_carry;
  parallel_prefix_add #(.p_width(33),.p_group_width(8),.p_preserve_groups(1'b1)) u_add (
    .i_a({1'b0,i_reduction}),.i_b({16'd0,i_group_channels,1'b0}),.i_carry(1'b0),
    .o_sum(o_result),.o_carry(unused_carry)
  );
endmodule
module cfg_comparison (
  input wire logic [31:0] i_reduction,
  input wire logic [15:0] i_group_channels,
  output logic o_equivalent
);
  logic [32:0] actual, reference_result;
  conv_cfg_skip_group u_candidate(.i_reduction,.i_group_channels,.o_result(actual));
  reference_cfg u_reference(.i_reduction,.i_group_channels,.o_result(reference_result));
  assign o_equivalent=actual===reference_result;
endmodule
''')
    for name, module in [('reference','reference_cfg'),('candidate','conv_cfg_skip_group')]:
        with model.open('a') as stream:
            stream.write('module registered_'+name+'''(
  input wire logic clk,
  input wire logic [31:0] reduction,
  input wire logic [15:0] group_a, group_b,
  input wire logic vector_mode,
  output logic [32:0] result_q
);
  logic [31:0] reduction_q;
  logic [15:0] group_a_q, group_b_q;
  logic vector_q;
  logic [32:0] result;
  always_ff @(posedge clk) begin
    reduction_q<=reduction;group_a_q<=group_a;group_b_q<=group_b;vector_q<=vector_mode;
    result_q<=result;
  end
  '''+module+''' u_calculation(.i_reduction(reduction_q),
    .i_group_channels(vector_q?group_a_q:group_b_q),.o_result(result));
endmodule
''')
    resolver = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))
    sources = resolver['with_dependencies']([SOURCE,model],ROOT)
    hashes = {str(path.relative_to(ROOT)):digest(path) for path in resolver['input_files'](sources,ROOT)
              if path.is_relative_to(ROOT)}
    script, log = out/'formal.ys', out/'formal.log'
    script.write_text(shlex.join(['read_slang','--top','cfg_comparison','-DSYNTHESIS=1',*map(str,sources)])+
                      '\nprep -top cfg_comparison -flatten\nsat -verify -prove o_equivalent 1\n')
    execute(script,log)
    if 'SUCCESS!' not in log.read_text():raise RuntimeError('配置跨组位置形式证明未完成')
    formal_hash=digest(log)
    bench=out/'four_state.sv';bench.write_text('''module cfg_four_state;
logic[31:0]i_reduction;logic[15:0]i_group_channels;logic equivalent;
logic[47:0]stimulus;assign{i_reduction,i_group_channels}=stimulus;
cfg_comparison u_compare(.i_reduction,.i_group_channels,.o_equivalent(equivalent));
integer random_state=32'h66231879;
function automatic integer random_word;
 random_state=random_state^(random_state<<13);random_state=random_state^(random_state>>17);
 random_state=random_state^(random_state<<5);return random_state;
endfunction
initial begin
 for(integer sample=0;sample<16384;sample++)begin
  stimulus={16'(random_word()),32'(random_word())};
  case(sample%16)
   0:stimulus='0;1:stimulus='1;2:stimulus='x;3:stimulus='z;
   4,5,6,7:stimulus[sample%48]=1'bx;
   8,9,10,11:stimulus[sample%48]=1'bz;
   default:begin end
  endcase
  #1;if(equivalent!==1'b1)$fatal(1,"cfg group mismatch sample=%0d",sample);
 end
 $display("CFG_GROUP_FOUR_STATE_PASS samples=16384");$finish;
end
endmodule
''')
    binary, log=out/'four_state.vvp',out/'four_state.log'
    with log.open('w')as stream:
        subprocess.run(['iverilog','-g2012','-DSYNTHESIS=1','-s','cfg_four_state','-o',str(binary),
                        *map(str,sources),str(bench)],stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=120)
        subprocess.run(['vvp',str(binary)],stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=120)
    if 'CFG_GROUP_FOUR_STATE_PASS' not in log.read_text():raise RuntimeError('配置跨组位置四态比较未完成')
    report=dict(passed=True,formal_log_sha256=formal_hash,four_state_samples=16384,
                four_state_log_sha256=digest(log),source_sha256=hashes,mapping={})
    sys.path.insert(0,str(ROOT/'scripts/fpga'))
    from netlist_metrics import resources,connected_paths,register_origins
    for name in ('reference','candidate'):
        top='registered_'+name
        pre,mapped,script,log=[out/(name+suffix)for suffix in ('.il','.json','.ys','.log')]
        script.write_text(shlex.join(['read_slang','--top',top,'-DSYNTHESIS=1',*map(str,sources)])+'\n'+
            'read_verilog -lib -specify -overwrite +/xilinx/cells_sim.v\n'+
            f'synth_xilinx -top {top} -family xc7 -abc9 -noiopad -noclkbuf -flatten -run begin:map_luts\n'+
            f'write_rtlil {pre}\n'+
            f'synth_xilinx -top {top} -family xc7 -abc9 -noiopad -noclkbuf -flatten -run map_luts:\n'+
            f'check -assert\nwrite_json {mapped}\n')
        execute(script,log)
        module=json.loads(mapped.read_text())['modules'][top]
        for key,value in register_origins(pre).items():
            if key in module['cells']:module['cells'][key].setdefault('attributes',{})['fpga_register_origin']=value
        module['cells']={key:value for key,value in module['cells'].items()if value['type']!='$scopeinfo'}
        paths=connected_paths(module,limit=6,group_limit=6)
        if not paths['graph_complete']:raise RuntimeError('配置跨组位置组合连接统计不完整')
        report['mapping'][name]=dict(resources=resources(module['cells']),paths=paths,log_sha256=digest(log))
        print('CFG_GROUP_MAPPING '+json.dumps(dict(name=name,
             lut=report['mapping'][name]['resources']['logic_lut_cells'],depth=paths['longest_register_path_cells'])),flush=True)
    if any(digest(ROOT/path)!=value for path,value in hashes.items()):raise RuntimeError('验证过程中源码发生变化')
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('CFG_GROUP_PASS formal=1 four_state=16384',flush=True)


if __name__=='__main__':main()
