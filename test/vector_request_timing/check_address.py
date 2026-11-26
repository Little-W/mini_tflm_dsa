#!/usr/bin/env python3
"""检查参数行描述符的完整父模块等价与四态传播。"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import argparse
import hashlib
import json
import re
import runpy
import shlex
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
RTL=Path('rtl/npu/conv/vector_engine_address.sv')
MODES=(('generic',['-USYNTHESIS','-UXILINX_FPGA']),
       ('synthesis',['-DSYNTHESIS=1','-UXILINX_FPGA']),
       ('fpga',['-USYNTHESIS','-DXILINX_FPGA=1']),
       ('fpga_synthesis',['-DSYNTHESIS=1','-DXILINX_FPGA=1']))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def execute(command,log,timeout=600):
    with Path(log).open('w') as stream:
        subprocess.run(list(map(str,command)),cwd=ROOT,stdout=stream,
                       stderr=subprocess.STDOUT,check=True,timeout=timeout)


def fragment(name,text):
    first=text.index('  assign parameter_stride_i_b =')
    last=text.index('  // 配置检查期间保存参数行描述符',first)
    return '''// 参数地址采用完整三十二位数值，保留原组合计算及未知值条件。
module '''+name+'''(
  input logic [31:0] i_bias, // 偏置数组首地址
  input logic [31:0] i_multiplier, // 乘数数组首地址
  input logic [31:0] i_shift, // 移位数组首地址
  output logic [33:0] o_result // 行间步长、两行资格和三行资格
);
  typedef struct packed {logic [31:0] bias_base,multiplier_base,shift_base;} cfg_t;
  cfg_t c;
  logic [31:0] parameter_stride_i_b,parameter_row_stride_next;
  logic parameter_stride_carry,parameter_stride_equal,parameter_bases_equal;
  logic parameter_two_rows_next,parameter_three_rows_next;
  logic parameter_bias_before_multiplier,unused_parameter_bias_equal;
  assign c={i_bias,i_multiplier,i_shift};
'''+text[first:last]+'''
  assign o_result={parameter_three_rows_next,parameter_two_rows_next,parameter_row_stride_next};
endmodule
'''


BENCH='''`timescale 1ns/1ps
// 随机地址、边界地址、相等地址及逐位未知地址的四态比较。
module tb;
logic [31:0] i_bias,i_multiplier,i_shift;
wire [33:0] expected,actual;
int unsigned random_state=32'h674d2f31;
integer checks=0;
reference ref_dut(.*,.o_result(expected));
current cur_dut(.*,.o_result(actual));
function automatic int unsigned next_random();
  random_state^=random_state<<13;random_state^=random_state>>17;random_state^=random_state<<5;
  return random_state;
endfunction
task automatic check;
  #1;
  if(actual!==expected)$fatal(1,"parameter address differs case=%0d expected=%h actual=%h",checks,expected,actual);
  checks++;
endtask
initial begin
  for(integer sample=0;sample<131072;sample++)begin
    i_bias=next_random();i_multiplier=next_random();i_shift=next_random();
    case(sample%16)
      0:i_shift=i_multiplier;
      1:i_shift=i_multiplier+(i_multiplier-i_bias);
      2:begin i_bias=0;i_shift='1;end
      3:begin i_multiplier=0;i_shift=1;end
      4:begin i_multiplier='1;i_shift=0;end
      5:i_bias[(sample>>4)%32]=1'bx;
      6:i_multiplier[(sample>>4)%32]=1'bx;
      7:i_shift[(sample>>4)%32]=1'bx;
      8:i_bias[(sample>>4)%32]=1'bz;
      9:i_multiplier[(sample>>4)%32]=1'bz;
      10:i_shift[(sample>>4)%32]=1'bz;
      11:begin i_bias='x;i_multiplier='z;i_shift='x;end
      12:begin i_bias='1;i_multiplier='1;i_shift='1;end
      13:begin i_shift=i_multiplier;i_shift[(sample>>4)%32]=1'bx;end
      default:begin end
    endcase
    check();
  end
  $display("PARAMETER_ADDRESS_PASS checks=%0d",checks);$finish;
end
endmodule
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--reference',default='57b61b24')
    parser.add_argument('--jobs',type=int,default=2)
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    resolve=runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    reference=out/'reference_address.sv'
    reference.write_bytes(subprocess.check_output(['git','show',args.reference+':'+str(RTL)],cwd=ROOT))
    sources={label:resolve([source],ROOT) for label,source in [('reference',reference),('current',ROOT/RTL)]}
    hashes={str(p):digest(p) for paths in sources.values() for p in paths}
    jobs=[]
    for mode,flags in MODES:
        for registered in (0,1):
            name=f'{mode}_registered{registered}'
            options=['-Gp_tile=16','-Gp_bus_width=64','-Gp_dma_size=64','-Gp_pe_count=8',
                     '-Gp_window_lanes=8','-Gp_shared_storage_enable=1','-Gp_shared_quant_enable=0',
                     f'-Gp_registered_read_phase={registered}']
            commands=[]
            for label,paths in sources.items():
                commands += ['read_slang --top vector_engine_address '+shlex.join(flags+options+list(map(str,paths))),
                  'setattr -mod -unset keep_hierarchy','setattr -unset keep_hierarchy',
                  'prep -top vector_engine_address -flatten','memory_map','async2sync','opt -full',
                  'rename -top '+label,'design -stash '+label]
            commands += ['design -copy-from reference -as reference reference',
              'design -copy-from current -as current current','equiv_make reference current proof',
              'hierarchy -top proof','opt -full','equiv_simple -short -seq 1','equiv_induct -seq 2',
              'equiv_simple -seq 1','equiv_status -assert']
            script=out/(name+'.ys');script.write_text('\n'.join(commands)+'\n');jobs.append((name,mode,flags,registered,script))
    def formal(job):
        name,mode,flags,registered,script=job;log=out/(name+'.log')
        execute([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--worker',script],log)
        text=log.read_text();assert 'Equivalence successfully proven!' in text
        row={'mode':mode,'macro_options':flags,'registered_read_phase':registered,'passed':True,
             'equivalence_points':int(re.findall(r'Found (\d+) \$equiv cells',text)[-1]),'log_sha256':digest(log)}
        print(json.dumps(row),flush=True);return row
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:proofs=list(pool.map(formal,jobs))
    models=out/'parameter_models.sv';models.write_text(fragment('reference',reference.read_text())+fragment('current',(ROOT/RTL).read_text()))
    bench=out/'tb.sv';bench.write_text(BENCH);dependencies=resolve([models],ROOT);four=[]
    for mode,flags in MODES:
        defines=[v for v in flags if v.startswith('-D')];exe=out/(mode+'.vvp')
        execute(['iverilog','-g2012','-s','tb',*defines,'-o',exe,*dependencies,bench],out/(mode+'_compile.log'))
        log=out/(mode+'_four_state.log');execute(['vvp',exe],log)
        assert 'PARAMETER_ADDRESS_PASS checks=131072' in log.read_text()
        four.append({'mode':mode,'macro_options':flags,'passed':True,'comparisons':131072,'log_sha256':digest(log)})
    assert all(digest(p)==h for p,h in hashes.items())
    (out/'summary.json').write_text(json.dumps({'passed':True,'reference_commit':args.reference,'input_constraints':[],
      'all_parent_outputs_and_state_compared':True,'formal':proofs,'four_state':four,'source_sha256':hashes,
      'runner_sha256':digest(__file__)},indent=2)+'\n')


if __name__=='__main__':main()
