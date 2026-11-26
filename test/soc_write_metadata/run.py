#!/usr/bin/env python3
"""验证写地址缓存的目的标志与两个完整地址存储槽逐周期一致。"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'rtl/soc/soc_cpu_write_address_metadata.sv'
PROFILES = [
    dict(ADDR_WIDTH=32, CPU_MEM_DP=65536, CPU_RAM_BASE=0, NPU_AXIL_BASE=0x10000000),
    dict(ADDR_WIDTH=40, CPU_MEM_DP=1031, CPU_RAM_BASE=8195, NPU_AXIL_BASE=0x10000000),
    dict(ADDR_WIDTH=64, CPU_MEM_DP=1, CPU_RAM_BASE=0, NPU_AXIL_BASE=0),
    dict(ADDR_WIDTH=32, CPU_MEM_DP=524288, CPU_RAM_BASE=-1048576, NPU_AXIL_BASE=0x10000000),
    dict(ADDR_WIDTH=32, CPU_MEM_DP=1031, CPU_RAM_BASE=0x02000000, NPU_AXIL_BASE=0x02000000),
    dict(ADDR_WIDTH=32, CPU_MEM_DP=16, CPU_RAM_BASE=0x10000000, NPU_AXIL_BASE=0x10000000),
]

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, log):
    with log.open('w') as stream:
        subprocess.run(list(map(str, command)), cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=300)


def model(source):
    original = subprocess.check_output(['git','show','8b3728c0:rtl/soc/soc_axi_interconnect.sv'], cwd=ROOT, text=True)
    pattern = r'    function automatic logic \[4:0\] decode_cpu_flags.*?    endfunction'
    function = re.search(pattern, original, re.S).group(0)
    actual_function = re.search(pattern, source, re.S).group(0)
    normalize = lambda text: re.sub(r'\s+|//[^\n]*', '', text)
    if normalize(function) != normalize(actual_function):
        raise RuntimeError('地址窗口译码函数与参照定义不同')
    header = source[:source.index('    localparam int unsigned CPU_ADDR_LSB')]
    header = header.replace('module soc_cpu_write_address_metadata', 'module reference')
    return header + '''    localparam int unsigned CPU_ADDR_LSB=2;
    localparam int unsigned CPU_RANGE_BITS=2+((CPU_MEM_DP<=1)?0:$clog2(CPU_MEM_DP));
''' + function + '''
    logic [ADDR_WIDTH-1:0] first_address_q, second_address_q;
    logic write_select_q, read_select_q;
    (* keep = 1 *) wire [4:0] first_flags_q=decode_cpu_flags(first_address_q);
    (* keep = 1 *) wire [4:0] second_flags_q=decode_cpu_flags(second_address_q);
    assign o_input_dest_flags=decode_cpu_flags(i_addr);
    assign o_dest_flags=decode_cpu_flags(read_select_q?second_address_q:first_address_q);
    always_ff @(posedge clk) begin
        if(!rst_n) begin
            first_address_q<='0;second_address_q<='0;
            write_select_q<=0;read_select_q<=0;
        end else begin
            if(i_push)begin
                if(write_select_q)second_address_q<=i_addr;
                else first_address_q<=i_addr;
                write_select_q<=!write_select_q;
            end
            if(i_pop)read_select_q<=!read_select_q;
        end
    end
endmodule
`default_nettype wire
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    source=SOURCE.read_text();reference=out/'reference.sv';reference.write_text(model(source))
    report={'passed':False,'source_sha256':digest(SOURCE),'inputs_constrained':False,'formal':[]}
    for index,parameters in enumerate(PROFILES):
        folder=out/f'formal_{index}';folder.mkdir(exist_ok=True)
        options=' '.join(f'-G{k}={v}' for k,v in parameters.items())
        commands=[]
        for top,path,name in [('reference',reference,'reference'),('soc_cpu_write_address_metadata',SOURCE,'actual')]:
            commands += [f'read_slang --top {top} {options} {shlex.quote(str(path))}',
                         f'prep -top {top} -flatten','memory_map','opt_clean',
                         f'rename {top} {name}',f'design -stash {name}']
        commands += ['design -copy-from reference -as reference reference','design -copy-from actual -as actual actual',
                     'equiv_make reference actual equivalent','hierarchy -top equivalent',
                     'equiv_simple -seq 1','opt_clean','equiv_induct -seq 2','equiv_status -assert']
        script=folder/'run.ys';script.write_text('\n'.join(commands)+'\n');log=folder/'formal.log'
        run([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--worker',script],log)
        text=log.read_text();counts=re.search(r'Of those cells (\d+) are proven and (\d+) are unproven',text)
        assert counts and not int(counts[2]) and 'Equivalence successfully proven' in text
        report['formal'].append({'parameters':parameters,'passed':True,'equivalent_bits':int(counts[1]),'log_sha256':digest(log)})
        print('metadata formal',index,'PASS',flush=True)
    declarations=[];comparisons=[]
    for index,parameters in enumerate(PROFILES):
        arguments=','.join(f'.{k}({v})' for k,v in parameters.items())
        addr=f"{parameters['ADDR_WIDTH']}'(i_addr)"
        declarations.append(f'''wire[4:0] old_input_{index},old_saved_{index},new_input_{index},new_saved_{index};
reference #({arguments}) old_{index}(.clk,.rst_n,.i_push,.i_pop,.i_addr({addr}),
.o_input_dest_flags(old_input_{index}),.o_dest_flags(old_saved_{index}));
soc_cpu_write_address_metadata #({arguments}) new_{index}(.clk,.rst_n,.i_push,.i_pop,.i_addr({addr}),
.o_input_dest_flags(new_input_{index}),.o_dest_flags(new_saved_{index}));''')
        comparisons.append(f'''if({{old_input_{index},old_saved_{index}}}!=={{new_input_{index},new_saved_{index}}})
$fatal(1,"metadata mismatch profile={index} cycle=%0d",cycle);''')
    tb=out/'tb.sv';tb.write_text('''module tb;
logic clk=0,rst_n=0,i_push=0,i_pop=0;
logic[63:0] i_addr=0;
integer seed=32'h1265a719,cycle=0;
'''+ '\n'.join(declarations)+'''
task check;
 begin #1;
'''+ '\n'.join(comparisons)+'''
 end
endtask
initial begin
 #1;clk=1;#1;clk=0;rst_n=1;
 for(cycle=0;cycle<50000;cycle=cycle+1)begin
  rst_n=(cycle%127)!=0;i_push=$random(seed);i_pop=$random(seed);
  for(integer bit_index=0;bit_index<64;bit_index=bit_index+1)begin
   case($random(seed)&15)
    0:i_addr[bit_index]=1'bx;
    1:i_addr[bit_index]=1'bz;
    default:i_addr[bit_index]=$random(seed);
   endcase
  end
  if(cycle%7==0)i_addr={$random(seed),$random(seed)};
  if(cycle%31==0)i_push=1'bx;
  if(cycle%37==0)i_pop=1'bz;
  if(cycle%41==0)rst_n=1'bx;
  check();clk=1;check();clk=0;
 end
 $display("WRITE_METADATA_PASS cycles=%0d profiles=6",cycle);$finish;
end
endmodule
''')
    converted=[]
    for path in [SOURCE,reference]:
        target=out/('sim_'+path.name)
        target.write_text(path.read_text().replace('parameter int unsigned','parameter integer').replace('localparam int unsigned','localparam integer'))
        converted.append(target)
    binary=out/'simulation';run(['iverilog','-g2012','-s','tb','-o',binary,*converted,tb],out/'build.log')
    run(['vvp',binary],out/'run.log');assert 'WRITE_METADATA_PASS cycles=50000 profiles=6' in (out/'run.log').read_text()
    assert source==SOURCE.read_text()
    report.update(passed=True,four_state={'cycles_per_profile':50000,'profiles':6,'compared_cycles':300000,
                                       'log_sha256':digest(out/'run.log')})
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'passed':True,'formal_profiles':6,'four_state_cycles':300000}))

if __name__=='__main__':main()
