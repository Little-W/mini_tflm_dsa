#!/usr/bin/env python3
"""检查实际传输步长选择的等价关系与寄存器之间的局部组合级数。"""
from pathlib import Path
import hashlib, json, runpy, shlex, subprocess, sys
import argparse
ROOT=Path(__file__).resolve().parents[2]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source-root',type=Path,default=ROOT)
parser.add_argument('--out',type=Path,required=True)
args=parser.parse_args()
root=args.source_root.resolve();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
read=runpy.run_path(str(ROOT/'test/frontend_pipeline/source_sections.py'))['read_module']
gp,g=read(root,'geometry');sp,s=read(root,'stream')
source_hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [gp,sp]}
a=g.index('      logic [LANES:0][17:0] channel_sum;');b=g.index('    end else begin : g_general',a)
body=g[a:b].replace('epoch_o_sum[candidate]','result').replace('c.group_offset','group_offset')
body=body.replace("      assign unused_epoch_carry[candidate] = 1'b0;\n",'')
a=s.index('  assign chunk_selected[0]');b=s.index('  if (CHUNK_COUNT_W + 1 < 32)',a)
selection=s[a:b]
header=''' #(parameter int LANES=16, CHUNK_COUNT_W=$clog2(LANES+1))(
input logic [15:0]group_offset,ch_q,
input logic [LANES-1:0]chunk_lane_allowed,
output logic [31:0]result,
output logic [CHUNK_COUNT_W-1:0]chunk_count
);
localparam bit p_contiguous_chunk=1;
logic [31:0] ch;
logic [LANES:0] chunk_selected;
assign ch={16'd0,ch_q};
always_comb begin
chunk_count='0;
for(int lane=0;lane<LANES;lane++)
if(chunk_lane_allowed[lane])chunk_count=CHUNK_COUNT_W'(lane+1);
end
'''
reference='module reference'+header+body.replace('chunk_selected[step]',"chunk_count == CHUNK_COUNT_W'(step)")+'\nendmodule\n'
candidate='module candidate'+header+selection+body+'\nendmodule\n'
model=out/'epoch_select.sv';model.write_text(reference+candidate+'''
module comparison #(parameter int LANES=16, CHUNK_COUNT_W=$clog2(LANES+1))(
input logic [15:0] group_offset,ch_q,
input logic [LANES-1:0] chunk_lane_allowed,
output logic equivalent);
logic [31:0] result_reference,result_candidate;
logic [CHUNK_COUNT_W-1:0] count_reference,count_candidate;
logic prefix_mask;
reference #(.LANES(LANES)) u_ref(.result(result_reference),.chunk_count(count_reference),.*);
candidate #(.LANES(LANES)) u_candidate(.result(result_candidate),.chunk_count(count_candidate),.*);
assign prefix_mask=(chunk_lane_allowed&(chunk_lane_allowed+LANES'(1)))=='0;
assign equivalent=!prefix_mask||((result_reference==result_candidate)&&(count_reference==count_candidate));
endmodule
''')
for name in ['reference','candidate']:
 with model.open('a') as f:f.write(f'''
module registered_{name} #(parameter int LANES=16,CHUNK_COUNT_W=$clog2(LANES+1))(
input logic clk,input logic [15:0]group_offset,ch_q,
input logic [LANES-1:0]chunk_lane_allowed,
output logic [31:0]result_q,output logic[CHUNK_COUNT_W-1:0]count_q);
logic[15:0]group_offset_saved,ch_saved;
logic[LANES-1:0]mask_saved;
logic[31:0]result;
logic[CHUNK_COUNT_W-1:0]count;
always_ff @(posedge clk)begin
 group_offset_saved<=group_offset;ch_saved<=ch_q;mask_saved<=chunk_lane_allowed;
 result_q<=result;count_q<=count;
end
{name} #(.LANES(LANES)) u_calc(.group_offset(group_offset_saved),.ch_q(ch_saved),.chunk_lane_allowed(mask_saved),.result(result),.chunk_count(count));
endmodule
''')
worker=ROOT/'scripts/fpga/open_fpga_synth.py'
proofs=[]
for lanes in range(1,17):
 script=out/f'proof{lanes}.ys';log=out/f'proof{lanes}.log'
 script.write_text(f'read_slang --top comparison -GLANES={lanes} {model}\nprep -top comparison -flatten\ncheck -assert\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
 with log.open('w') as f:r=subprocess.run([sys.executable,str(worker),'--worker',str(script)],stdout=f,stderr=subprocess.STDOUT,timeout=120)
 assert r.returncode==0 and 'SUCCESS!' in log.read_text(),log
 proofs.append(lanes)
 print('proof',lanes,flush=True)
sys.path.insert(0,str(ROOT/'scripts/fpga'))
from netlist_metrics import resources,connected_paths,register_origins
cases={}
for name in ['reference','candidate']:
 folder=out/name;folder.mkdir(exist_ok=True);top='registered_'+name
 script=folder/'run.ys';log=folder/'run.log';pre=folder/'pre.il';mapped=folder/'mapped.json'
 script.write_text(f'read_slang --top {top} -GLANES=16 {model}\nread_verilog -lib -specify -overwrite +/xilinx/cells_sim.v\nhierarchy -check -top {top}\nsynth_xilinx -top {top} -family xc7 -noiopad -noclkbuf -flatten -run begin:map_luts\nwrite_rtlil {pre}\nsynth_xilinx -top {top} -family xc7 -noiopad -noclkbuf -flatten -run map_luts:\ncheck -assert\nwrite_json {mapped}\n')
 with log.open('w') as f:r=subprocess.run([sys.executable,str(worker),'--worker',str(script)],stdout=f,stderr=subprocess.STDOUT,timeout=180)
 assert r.returncode==0,log
 m=json.loads(mapped.read_text())['modules'][top]
 for k,v in register_origins(pre).items():
  if k in m['cells']:m['cells'][k].setdefault('attributes',{})['fpga_register_origin']=v
 m['cells']={k:v for k,v in m['cells'].items() if v['type']!='$scopeinfo'}
 paths=connected_paths(m,limit=4,group_limit=4)
 mask=connected_paths(m,limit=4,group_limit=4,root_filter=lambda n,c,p:'mask_saved' in c.get('attributes',{}).get('fpga_register_origin',''),sink_filter=lambda n,c,p:'result_q' in c.get('attributes',{}).get('fpga_register_origin',''))
 assert paths['graph_complete'] and mask['graph_complete']
 cases[name]={'resources':resources(m['cells']),'paths':paths,'mask_paths':mask}
 print(name,'lut',cases[name]['resources']['logic_lut_cells'],'carry4',cases[name]['resources']['carry4'],'registers',cases[name]['resources']['flip_flops'],'depth',paths['longest_register_path_cells'],'mask_depth',mask['longest_register_path_cells'],flush=True)
assert source_hashes=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [gp,sp]}
summary={'passed':True,'scope':'16 通道独立纪元计算；保留计数输出寄存器；xc7 布局前映射','proved_lanes':proofs,'prefix_mask_required':True,'source_sha256':source_hashes,'model_sha256':hashlib.sha256(model.read_bytes()).hexdigest(),'cases':cases}
(out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
