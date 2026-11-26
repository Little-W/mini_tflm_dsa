#!/usr/bin/env python3
"""验证坐标步进结果、边界资格及未知值的逐位传播。"""
from formal_compilation import slang_command
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import argparse
import hashlib,json,runpy,shlex,subprocess,sys
root=Path(__file__).resolve().parents[2]
parser=argparse.ArgumentParser(description='验证坐标步进的完整定宽输出及四态传播。')
parser.add_argument('--out', type=Path, required=True)
parser.add_argument('--candidate', type=Path, nargs='+', required=True)
parser.add_argument('--reference', default='54a96b45')
args=parser.parse_args()
out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
reference_text=subprocess.check_output(['git','show',args.reference+':rtl/npu/conv/conv_coordinate_step.sv'],cwd=root,text=True)
resolve=runpy.run_path(str(root/'scripts/rtl/source_files.py'))['with_dependencies']
reference=out/'reference_renamed.sv'
reference.write_text(reference_text.replace('module conv_coordinate_step #','module coordinate_reference #'))
deps=resolve([*(p.resolve() for p in args.candidate),reference],root)
hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in deps}
widths=[17,18,31,32,35,64]
check=out/'check.sv'
check.write_text('''module check #(parameter int WIDTH=35)(input logic [WIDTH-1:0] a,b,input logic [15:0] limit,output logic equal);
logic [WIDTH-1:0] sum,expected;logic valid,expected_valid;
conv_coordinate_step #(.p_width(WIDTH)) u_candidate(.i_base(a),.i_delta(b),.i_limit(limit),.o_sum(sum),.o_valid(valid));
coordinate_reference #(.p_width(WIDTH)) u_reference(.i_base(a),.i_delta(b),.i_limit(limit),.o_sum(expected),.o_valid(expected_valid));
assign equal={valid,sum}=={expected_valid,expected};
endmodule
''')
def execute(cmd,log):
 with log.open('w') as stream:
  subprocess.run(list(map(str,cmd)),cwd=root,stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=600)
def prove(item):
 width,synthesis=item;key=f'width{width}_{"synthesis" if synthesis else "generic"}'
 options=[f'-GWIDTH={width}']+(['-DSYNTHESIS=1','-DXILINX_FPGA=1'] if synthesis else [])
 script=out/(key+'.ys');log=out/(key+'.log')
 script.write_text('\n'.join([slang_command(options)+'--top check '+shlex.join(options+list(map(str,deps+[check]))),'setattr -mod -unset keep_hierarchy','setattr -unset keep_hierarchy','prep -top check -flatten','opt -full','sat -prove equal 1 -verify'])+'\n')
 execute([sys.executable,root/'scripts/fpga/open_fpga_synth.py','--worker',script],log)
 print(key+' PASS',flush=True)
 return {'width':width,'synthesis':synthesis,'passed':True,'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()}
with ThreadPoolExecutor(max_workers=2) as pool:formal=list(pool.map(prove,[(w,s) for w in widths for s in [False,True]]))
tb=out/'tb.sv';lines=['module tb;logic [63:0] a,b;logic [15:0] limit;integer sample;']
for i,w in enumerate(widths):
 lines += [f'logic [{w-1}:0] got_{i},expected_{i};logic valid_{i},expected_valid_{i};',
 f'conv_coordinate_step #(.p_width({w})) u_candidate_{i}(.i_base(a[{w-1}:0]),.i_delta(b[{w-1}:0]),.i_limit(limit),.o_sum(got_{i}),.o_valid(valid_{i}));',
 f'coordinate_reference #(.p_width({w})) u_reference_{i}(.i_base(a[{w-1}:0]),.i_delta(b[{w-1}:0]),.i_limit(limit),.o_sum(expected_{i}),.o_valid(expected_valid_{i}));']
lines += ["initial begin for(sample=0;sample<30000;sample=sample+1) begin a={$random,$random};b={$random,$random};limit=$random;case(sample%12)","0: a='0; 1: b='1; 2: a[$urandom_range(63,0)]=1'bx; 3: b[$urandom_range(63,0)]=1'bz; 4: limit[$urandom_range(15,0)]=1'bx; 5: begin a='x;b='0;end 6: begin a='z;b='1;end 7: begin a='0;b='x;limit=0;end 8: begin a='0;b='0;limit='x;end 9: begin a[15:0]='x;b[31:16]='0;end 10: begin a[31:16]='x;b[15:0]='1;end 11: begin b=~a;limit=1;end endcase #1;"]
for i,w in enumerate(widths):
 lines += [f'if ({{valid_{i},got_{i}}} !== {{expected_valid_{i},expected_{i}}}) $fatal(1,"width={w} sample=%0d expected=%h got=%h",sample,{{expected_valid_{i},expected_{i}}},{{valid_{i},got_{i}}});']
lines += ['end $display("PASS comparisons=180000");$finish;end endmodule']
tb.write_text('\n'.join(lines)+'\n')
simulations=[]
for synthesis in [False,True]:
 key='simulation_synthesis' if synthesis else 'simulation_generic';binary=out/(key+'.vvp');log=out/(key+'.log')
 options=['-DSYNTHESIS=1','-DXILINX_FPGA=1'] if synthesis else []
 execute(['iverilog','-g2012','-s','tb',*options,'-o',binary,*deps,tb],out/(key+'_compile.log'))
 execute(['vvp',binary],log); assert 'PASS comparisons=180000' in log.read_text();binary.unlink()
 simulations.append({'synthesis':synthesis,'comparisons':180000,'passed':True,'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()});print(key+' PASS',flush=True)
assert hashes=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in deps}
(out/'validation.json').write_text(json.dumps({'passed':True,'reference':args.reference,'reference_sha256':hashlib.sha256(reference_text.encode()).hexdigest(),'all_outputs_compared':True,'input_constraints':False,'source_sha256':hashes,'formal':formal,'four_state':simulations},indent=2)+'\n')
