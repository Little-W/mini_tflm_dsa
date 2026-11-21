"""验证完整偏置组状态以及行边界的四态行为。"""
from pathlib import Path
import re,json,subprocess,sys,hashlib,argparse,importlib.util
ROOT=Path(__file__).resolve().parents[2]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--out',type=Path,required=True)
parser.add_argument('--source-root',type=Path,default=ROOT)
parser.add_argument('--reference',default='cfcc1a95ddcd93625636efc15b8c2b2b1835730f')
args=parser.parse_args();OUT=args.out.resolve();OUT.mkdir(parents=True,exist_ok=True)
relative=Path('rtl/npu/top/npu_top.sv')
texts={'current':(args.source_root/relative).read_text(),'reference':subprocess.check_output(['git','show',args.reference+':'+str(relative)],cwd=ROOT,text=True)}
spec=importlib.util.spec_from_file_location('bias_control_extract',ROOT/'test/bias_row_final_select/extract_control.py')
extract=importlib.util.module_from_spec(spec);spec.loader.exec_module(extract)
for label,text in texts.items():(OUT/f'{label}_control.sv').write_text(extract.module_source(text))
cases={label:{'top':'bias_row_control','sources':[str(OUT/f'{label}_control.sv')],'options':['-DSYNTHESIS=1','-DXILINX_FPGA=1','-GSIZE=16','-GREG_WIDTH=32','-GBIAS_GROUP_BLOCKS_MAX=32'],'configuration':'完整偏置组状态与行索引'}for label in texts}
(OUT/'cases.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2)+'\n')
profiles=[(1,1,32),(4,1,32),(16,4,32),(16,32,32),(16,64,32),(32,1,32),(32,32,16),(32,64,64)]
helper=ROOT/'rtl/common/unsigned_compare.sv';runs=[]
for size,groups,width in profiles:
 for fpga in [False,True]:
  commands=[]
  for label in ['reference','current']:
   definition='-DSYNTHESIS=1 -DXILINX_FPGA=1'if fpga else'-DASIC_SYNTHESIS=1'
   commands += [f'read_slang --top bias_row_control -GSIZE={size} -GBIAS_GROUP_BLOCKS_MAX={groups} -GREG_WIDTH={width} {definition} '+str(helper)+' '+str(OUT/f'{label}_control.sv'),'prep -top bias_row_control -flatten','async2sync','opt -full',f'rename bias_row_control {label}',f'design -stash {label}']
  commands+=['design -copy-from reference -as reference reference','design -copy-from current -as current current','equiv_make reference current equivalent','hierarchy -top equivalent','equiv_simple -seq 1','equiv_induct -seq 2','equiv_status -assert']
  script=OUT/f'formal_{size}_{groups}_{width}_{int(fpga)}.ys';script.write_text('\n'.join(commands)+'\n');log=script.with_suffix('.log')
  with log.open('w')as f:subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],stdout=f,stderr=subprocess.STDOUT,check=True,timeout=90)
  m=re.search(r'Of those cells (\d+) are proven and (\d+) are unproven',log.read_text());assert m and int(m[2])==0
  runs.append(dict(size=size,groups=groups,width=width,fpga=fpga,equivalent_bits=int(m[1]),passed=True))
  print(json.dumps(runs[-1]),flush=True)
models=[]
for label in ['reference','current']:
 text=(OUT/f'{label}_control.sv').read_text()
 expressions=[]
 for name in ['is_bias_row_increment','is_bias_row_wrap','is_bias_row_step','is_bias_row_clear','is_bias_row_next']:
  expressions.append(re.search(r'assign '+name+r'\s*=.*?;',text,re.S)[0])
 extra=''
 if 'assign is_bias_row_distance'in text:extra='logic [IS_BIAS_VALID_W:0] is_bias_row_distance;\n'+re.search(r'assign is_bias_row_distance\s*=.*?;',text,re.S)[0]
 block=re.search(r'        always_comb begin\n            is_bias_read_idx =.*?\n        end\n',text,re.S)[0]
 models.append('''module LABEL #(parameter ROWS=512, W=(ROWS<=1)?1:$clog2(ROWS), V=(ROWS<=1)?1:$clog2(ROWS)+1)(
 input logic [W-1:0] is_bias_row_idx,input logic [V-1:0] is_bias_rows_valid,
 input logic is_mode,acc_data_valid,init_cfg_ia,send_ia_trigger,bias_sleep,
 output wire [2*W:0] observed);
 localparam IS_BIAS_ROW_W=W,IS_BIAS_VALID_W=V;
 logic [W-1:0] is_bias_read_idx,is_bias_row_increment,is_bias_row_step,is_bias_row_next;
 logic is_bias_row_wrap,is_bias_row_clear;
'''.replace('LABEL',label)+extra+'\n'+'\n'.join(expressions)+block+'''
 assign observed={is_bias_row_next,is_bias_read_idx,is_bias_row_wrap};
endmodule
''')
bench='''module tb;
 reg [15:0] row_value,valid_value;reg [4:0] flags;reg step=0;
 reg [31:0] seed=32'h2fcd6789;integer checks=0;
 function automatic [31:0] random_word;
 begin seed=seed^(seed<<13);seed=seed^(seed>>17);seed=seed^(seed<<5);random_word=seed;end
 endfunction
 function automatic four_value(input [1:0] v);
 case(v)0:four_value=0;1:four_value=1;2:four_value=1'bx;3:four_value=1'bz;endcase
 endfunction
'''
rows=[1,2,3,4,16,64,512,1024,2048]
comparisons=0
for index,row_count in enumerate(rows):
 width=1 if row_count<=1 else(row_count-1).bit_length();valid_width=1 if row_count<=1 else width+1;out_width=2*width+1;comparisons+=out_width
 bench+=f'wire [{out_width-1}:0] r{index},c{index};\n'
 for label,prefix in [('reference','r'),('current','c')]:
  bench+=f'''{label} #(.ROWS({row_count})) u_{label}{index}(.is_bias_row_idx(row_value[{width-1}:0]),.is_bias_rows_valid(valid_value[{valid_width-1}:0]),.is_mode(flags[0]),.acc_data_valid(flags[1]),.init_cfg_ia(flags[2]),.send_ia_trigger(flags[3]),.bias_sleep(flags[4]),.observed({prefix}{index}));\n'''
 bench+=f'always @(negedge step)if(r{index}!==c{index})$fatal(1,"Bias row four-state mismatch rows={row_count}");\n'
bench+='''initial begin
 for(integer sample=0;sample<30000;sample++)begin
 for(integer index=0;index<16;index++)begin
 row_value[index]=sample[0]?four_value(2'(random_word())):1'(random_word());
 valid_value[index]=sample[0]?four_value(2'(random_word())):1'(random_word());
 end
 for(integer index=0;index<5;index++)flags[index]=sample[0]?four_value(2'(random_word())):1'(random_word());
 #1;step=1;#1;step=0;checks+=COUNT;
 end
 #1;$display("PASS comparisons=%0d",checks);$finish;
 end
endmodule
'''.replace('COUNT',str(comparisons))
(OUT/'four_state.sv').write_text('\n'.join(models)+bench)
with(OUT/'four_state_build.log').open('w')as f:subprocess.run(['iverilog','-g2012','-s','tb','-o',str(OUT/'four_state.vvp'),str(OUT/'four_state.sv')],stdout=f,stderr=subprocess.STDOUT,check=True)
r=subprocess.run(['vvp',str(OUT/'four_state.vvp')],text=True,capture_output=True,timeout=90);(OUT/'four_state.log').write_text(r.stdout+r.stderr);r.check_returncode();assert f'PASS comparisons={30000*comparisons}'in r.stdout
result={'reference':args.reference,'rtl_sha256':{label:hashlib.sha256(text.encode()).hexdigest()for label,text in texts.items()},'runner_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'passed':True,'profiles':runs,'equivalent_bits':sum(r['equivalent_bits']for r in runs),'four_state_samples':30000,'four_state_output_comparisons':30000*comparisons,'source_sha256':{name:hashlib.sha256((OUT/f'{name}_control.sv').read_bytes()).hexdigest()for name in ['reference','current']},'inputs_constrained':False}
(OUT/'summary.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'passed':True,'equivalent_bits':result['equivalent_bits'],'four_state_output_comparisons':result['four_state_output_comparisons']}))
