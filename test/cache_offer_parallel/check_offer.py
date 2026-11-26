#!/usr/bin/env python3
"""验证预取重复检查的任意二态输入与未知值传播。"""
from pathlib import Path
import subprocess,json,hashlib,sys,shlex,argparse
r=Path(__file__).resolve().parents[2]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--out',type=Path,required=True)
args=parser.parse_args()
out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
model=out/'offer_proof.sv';model.write_text("""module offer_proof #(parameter W=25,E=10)(
 input logic i_fill_active,input logic [W-1:0] i_fill_tag,
 input logic [2*W-1:0] i_offer_tag,input logic [2*E-1:0] i_valid,
 input logic [2*E*W-1:0] i_tag,input logic i_next_fragment,
 output logic equivalent);
 logic expected_duplicate,expected_next,actual_duplicate,actual_next;
 conv_cache_offer_duplicate #(.p_tag_width(W),.p_entries(E)) u_actual(
 .i_fill_active,.i_fill_tag,.i_offer_tag,.i_valid,.i_tag,.i_next_fragment,
 .o_choose_next(actual_next),.o_duplicate(actual_duplicate));
 always_comb begin
  expected_duplicate=i_fill_active && i_fill_tag==i_offer_tag[0+:W];
  for(integer e=0;e<E;e++)
   if(i_valid[e] && i_tag[e*W+:W]==i_offer_tag[0+:W]) expected_duplicate=1;
  expected_next=expected_duplicate && i_next_fragment;
  if(expected_next)begin
   expected_duplicate=i_fill_active && i_fill_tag==i_offer_tag[W+:W];
   for(integer e=0;e<E;e++)
    if(i_valid[E+e] && i_tag[(E+e)*W+:W]==i_offer_tag[W+:W]) expected_duplicate=1;
  end
 end
 assign equivalent={expected_duplicate,expected_next}==={actual_duplicate,actual_next};
endmodule
""")
bench="""module tb;
 localparam W=WIDTH_VALUE,E=ENTRIES_VALUE;
 logic i_fill_active,i_next_fragment;
 logic [W-1:0] i_fill_tag;
 logic [2*W-1:0] i_offer_tag;
 logic [2*E-1:0] i_valid;
 logic [2*E*W-1:0] i_tag;
 wire equivalent;
 integer checks=0;
 logic [31:0] random_state=32'h71fa290d;
 offer_proof #(.W(W),.E(E)) dut(.*);
 function automatic logic [31:0] advance(input logic [31:0] value);
 logic [31:0] result;
 result=value^(value<<13);result=result^(result>>17);return result^(result<<5);
 endfunction
 function automatic logic four(input logic [1:0] value);
 case(value)0:return 0;1:return 1;2:return 1'bx;3:return 1'bz;endcase
 endfunction
 task automatic check;
 #1;if(equivalent!==1'b1)$fatal(1,"offer differs W=%0d E=%0d trial=%0d",W,E,checks);checks++;
 endtask
 initial begin
 for(integer trial=0;trial<65536;trial++)begin
  for(integer bit_index=0;bit_index<2*W;bit_index++)begin
   random_state=advance(random_state);i_offer_tag[bit_index]=random_state[0];
  end
  i_fill_tag=i_offer_tag[(trial%2)*W+:W];
  for(integer entry=0;entry<2*E;entry++)begin
   i_tag[entry*W+:W]=i_offer_tag[(entry/E)*W+:W];
   random_state=advance(random_state);i_valid[entry]=four(random_state[1:0]);
   if(random_state[2])i_tag[entry*W+((random_state>>3)%W)]=four(random_state[6:5]);
   if(random_state[7])i_tag[entry*W+((random_state>>8)%W)]=~i_tag[entry*W+((random_state>>8)%W)];
  end
  random_state=advance(random_state);i_fill_active=four(random_state[1:0]);i_next_fragment=four(random_state[3:2]);
  if(random_state[4])i_fill_tag[(random_state>>5)%W]=four(random_state[9:8]);
  if(random_state[10])i_offer_tag[(random_state>>11)%(2*W)]=four(random_state[15:14]);
  check();
 end
 $display("OFFER_PASS W=%0d E=%0d checks=%0d",W,E,checks);$finish;
 end
endmodule
"""
sources=[model,r/'rtl/npu/dma/cache/conv_cache_offer_duplicate.sv',r/'rtl/npu/dma/cache/conv_cache_snapshot_equal.sv'];reports=[]
for width,entries in [(1,1),(2,3),(25,10),(29,9)]:
 for fpga in (False,True):
  name=f'w{width}_e{entries}_'+('fpga' if fpga else 'generic');flags=['-DSYNTHESIS=1','-DXILINX_FPGA=1'] if fpga else []
  script=out/(name+'.ys');log=out/(name+'_formal.log')
  script.write_text('read_slang --top offer_proof '+shlex.join([f'-GW={width}',f'-GE={entries}',*(flags if fpga else ['-USYNTHESIS']),*map(str,sources)])+'\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\nprep -top offer_proof -flatten\ncheck -assert\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
  with log.open('w') as f:subprocess.run([sys.executable,r/'scripts/fpga/open_fpga_synth.py','--worker',script],stdout=f,stderr=subprocess.STDOUT,check=True,timeout=120)
  assert 'SUCCESS!' in log.read_text()
  tb=out/(name+'_tb.sv');tb.write_text(bench.replace('WIDTH_VALUE',str(width)).replace('ENTRIES_VALUE',str(entries)))
  binary=out/(name+'.vvp');sim=out/(name+'_simulation.log')
  with (out/(name+'_compile.log')).open('w') as f:subprocess.run(['iverilog','-g2012','-s','tb',*flags,'-o',str(binary),*map(str,sources),str(tb)],stdout=f,stderr=subprocess.STDOUT,check=True)
  with sim.open('w') as f:subprocess.run(['vvp',binary],stdout=f,stderr=subprocess.STDOUT,check=True,timeout=120)
  assert f'OFFER_PASS W={width} E={entries} checks=65536' in sim.read_text()
  record={'width':width,'entries':entries,'fpga':fpga,'arbitrary_input_proof':True,'four_state_checks':65536,'passed':True,'formal_log_sha256':hashlib.sha256(log.read_bytes()).hexdigest(),'simulation_log_sha256':hashlib.sha256(sim.read_bytes()).hexdigest()};reports.append(record);print(json.dumps(record),flush=True)
(out/'summary.json').write_text(json.dumps({'passed':True,'input_constraints':[],'checks':reports,'source_sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}},indent=2)+'\n')
