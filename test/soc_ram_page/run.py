#!/usr/bin/env python3
"""验证 AXI 存储器按尺寸并行生成的完整突发命令检查函数。"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/soc/soc_axi_ram.sv')
FUNCTION = re.compile(r'    function automatic logic axi_command_bad\([\s\S]*?    endfunction')
PROFILES = ((8,8),(16,32),(32,32),(32,64),(40,64),(32,128),(32,256),(32,512))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='36c6e6e3')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    original = subprocess.check_output(['git','show',args.reference+':'+str(SOURCE)],cwd=ROOT,text=True)
    current = (ROOT/SOURCE).read_text()
    assert FUNCTION.sub('',original) == FUNCTION.sub('',current), '函数以外的内容需要单独验证'
    bodies = [FUNCTION.search(text)[0].replace('axi_command_bad',name)
              for text,name in ((original,'reference_bad'),(current,'current_bad'))]
    wrapper = '''module command_check #(parameter integer AW=32, DW=64)(
 input wire [AW-1:0] address, input wire [7:0] length,
 input wire [2:0] size, input wire [1:0] burst,
 output wire reference_result, current_result, equivalent);
 localparam integer ADDR_LSB=$clog2(DW/8);
'''+ '\n'.join(bodies)+'''
 assign reference_result=reference_bad(address,length,size,burst);
 assign current_result=current_bad(address,length,size,burst);
 assign equivalent=reference_result==current_result;
endmodule
'''
    model = out/'command_check.sv'
    model.write_text(wrapper)
    report = dict(reference=args.reference, source_sha256=sha(ROOT/SOURCE),
                  reference_sha256=hashlib.sha256(original.encode()).hexdigest(),
                  only_command_check_changed=True, formal=[], four_state=[])
    for index,(address_width,data_width) in enumerate(PROFILES):
        script,log = out/f'proof_{index}.ys', out/f'proof_{index}.log'
        script.write_text(f'read_slang --top command_check -GAW={address_width} -GDW={data_width} '+
                          shlex.quote(str(model))+'\nprep -top command_check -flatten\n'+
                          'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],
                           stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=120)
        assert 'SAT proof finished - no model found: SUCCESS!' in log.read_text()
        report['formal'].append(dict(address_width=address_width,data_width=data_width,passed=True,
                                     constrained_inputs=False,script_sha256=sha(script),log_sha256=sha(log)))
        bench = out/f'four_state_{index}.sv'
        bench.write_text(f'''module tb;
 localparam integer AW={address_width}, DW={data_width}, WIDTH=AW+13;
 reg [WIDTH-1:0] stimulus,saved;
 wire [AW-1:0] address;
 wire [7:0] length;
 wire [2:0] size;
 wire [1:0] burst;
 wire reference_result,current_result,equivalent;
 assign {{address,length,size,burst}}=stimulus;
 command_check #(.AW(AW),.DW(DW)) u_check(.*);
 reg [31:0] rng=32'h967e1d85;
 integer checks=0;
 task check;
  #1;if(reference_result!==current_result)
   $fatal(1,"突发命令检查不同 stimulus=%b reference=%b current=%b",stimulus,reference_result,current_result);
  checks=checks+1;
 endtask
 task randomize;
  for(integer bit_index=0;bit_index<WIDTH;bit_index=bit_index+1)begin
   rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);stimulus[bit_index]=rng[0];
  end
 endtask
 initial begin
  stimulus='0;check();stimulus='1;check();stimulus='x;check();stimulus='z;check();
  for(integer trial=0;trial<8192;trial=trial+1)begin randomize();check();end
  for(integer trial=0;trial<256;trial=trial+1)begin
   randomize();check();saved=stimulus;
   for(integer bit_index=0;bit_index<WIDTH;bit_index=bit_index+1)begin
    stimulus=saved;stimulus[bit_index]=1'bx;check();
    stimulus=saved;stimulus[bit_index]=1'bz;check();
   end
  end
  $display("AXI_PAGE_FOUR_STATE_PASS checks=%0d",checks);$finish;
 end
endmodule
''')
        binary,run_log = out/f'four_state_{index}.vvp',out/f'four_state_{index}.log'
        with (out/f'four_state_{index}.compile.log').open('w') as stream:
            subprocess.run(['iverilog','-g2012','-s','tb','-o',str(binary),str(model),str(bench)],
                           stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=120)
        run = subprocess.run(['vvp',str(binary)],capture_output=True,text=True,timeout=120)
        run_log.write_text(run.stdout+run.stderr)
        match = re.search(r'AXI_PAGE_FOUR_STATE_PASS checks=(\d+)',run.stdout)
        assert run.returncode==0 and match, str(run_log)
        report['four_state'].append(dict(address_width=address_width,data_width=data_width,checks=int(match[1]),
                                         passed=True,bench_sha256=sha(bench),log_sha256=sha(run_log)))
        print('profile',index,'formal PASS','four_state',match[1],'PASS',flush=True)
    assert report['source_sha256']==sha(ROOT/SOURCE), '验证期间源码发生变化'
    report['passed']=True
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':
    main()
