#!/usr/bin/env python3
"""测量实际帧完成、控制器、部分和读取选择与共享存储连接后的完整组合路径。"""
from pathlib import Path
import argparse,hashlib,json,re,subprocess,runpy,sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/fpga'))
from netlist_metrics import connected_paths,register_origins
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--reference',default='8009b2f7')
parser.add_argument('--out',type=Path,required=True)
parser.add_argument('--prepare-only',action='store_true')
args=parser.parse_args()
OUT=args.out.resolve()
OUT.mkdir(parents=True,exist_ok=True)
reference=subprocess.check_output(['git','rev-parse',args.reference],cwd=ROOT,text=True).strip()
files=['rtl/npu/control/npu_controller.sv','rtl/npu/control/npu_ia_issue_select.sv',
       'rtl/npu/top/npu_bias_address_zero.sv','rtl/npu/top/npu_bias_presence.sv',
       'rtl/npu/ps_compact/ps_frame_read_enable.sv']

def ports(text,module):
 header=text[text.index('module '+module):text.index('\n);',text.index('module '+module))]
 return re.findall(r'^\s*(input|output)\s+(?:(?:wire|logic|reg|signed)\s+)*(\[[^]]+\])?\s*(\w+)(\s*\[[^]]+\])?',header,re.M)

cases={}
for name in ['reference','candidate']:
 folder=OUT/name;folder.mkdir(exist_ok=True)
 copied={}
 for relative in files:
  p=folder/Path(relative).name
  p.write_bytes(subprocess.check_output(['git','show',reference+':'+relative],cwd=ROOT) if name=='reference' else (ROOT/relative).read_bytes())
  copied[Path(relative).stem]=p
 cp=ports(copied['npu_controller'].read_text(),'npu_controller')
 rp=ports((ROOT/'rtl/npu/buffers/ia_ps_channel_ram.sv').read_text(),'ia_ps_channel_ram')
 declarations=['input logic clk, // 测量时钟','input logic rst_n, // 低有效复位',
   'input logic [31:0] i_bias_address, // 完整偏置基址',
   'input logic [31:0] i_ws_channel, // 权重驻留通道',
   'input logic [31:0] i_is_channel, // 输入驻留通道',
   'input logic [5:0] i_bias_flags, // 帧模式、数据流、末帧偏置和帧位置',
   'input logic [8:0] i_ps_flags, // 部分和读取条件与共享端口选择',
   'input logic [8:0] i_frame_status, // 帧完成状态与输出运行状态',
   'input logic [2:0] i_output_conditions, // 量化输出分组和输入输出待处理状态']
 internals=['logic [31:0] bias_address_q,ws_channel_q,is_channel_q;',
   'logic [5:0] bias_flags_q;','logic [8:0] ps_flags_q;','logic [8:0] frame_status_q;','logic [2:0] output_conditions_q;','logic frame_complete;',
   'logic address_zero,base_nonzero,bias_present,frame_phase,issue_eligible,issue_qualified;',
   'logic frame_accept,frame_read;','logic [3:0] memory_read_enable;']
 updates=['bias_address_q<=i_bias_address;ws_channel_q<=i_ws_channel;is_channel_q<=i_is_channel;',
   'bias_flags_q<=i_bias_flags;ps_flags_q<=i_ps_flags;',
   'frame_status_q<=i_frame_status;output_conditions_q<=i_output_conditions;']
 cc=[]
 for direction,width,port,unpacked in cp:
  if port in ['clk','rst_n']:cc.append('.'+port+'('+port+')');continue
  if port=='bias_base':cc.append('.bias_base(32\'(bias_present))');continue
  if port=='o_ia_issue_eligible':cc.append('.o_ia_issue_eligible(issue_eligible)');continue
  if port=='i_ia_issue_qualified':cc.append('.i_ia_issue_qualified(issue_qualified)');continue
  declarations.append(f'{direction} logic {width} c_{port}{unpacked}, // 控制器{direction}信号 {port}')
  if direction=='input':
   internals.append(f'logic {width} {port}_q{unpacked};');updates.append(f'{port}_q<=c_{port};');cc.append(f'.{port}({port}_q)')
  else:
   internals.append(f'logic {width} {port}{unpacked};');updates.append(f'c_{port}<={port};');cc.append(f'.{port}({port})')
 rc=[]
 for direction,width,port,unpacked in rp:
  if port in ['clk','rst_n']:rc.append('.'+port+'('+port+')');continue
  declarations.append(f'{direction} logic {width} m_{port}{unpacked}, // 共享存储{direction}信号 {port}')
  if direction=='input':
   internals.append(f'logic {width} mem_{port}_q{unpacked};');updates.append(f'mem_{port}_q<=m_{port};')
   rc.append(f'.{port}(memory_read_enable)' if port=='i_ps_read_en' else f'.{port}(mem_{port}_q)')
  else:
   internals.append(f'logic {width} mem_{port}{unpacked};');updates.append(f'm_{port}<=mem_{port};');rc.append(f'.{port}(mem_{port})')
 declarations[-1]=declarations[-1].replace(', //',' //',1)
 text='''// 连接偏置判断、完整控制器、部分和读取选择和真实共享 RAM，保存全部外部输入输出。
module measure #(
 parameter REG_WIDTH=32, SIZE=16, BUS_WIDTH=64, DATA_WIDTH=16, WEIGHT_WIDTH=16,
 parameter p_addr_width=12, p_bank_count_width=3
)(
'''+ '\n'.join(declarations)+'\n);\n'+'\n'.join(internals)+'\nalways_ff @(posedge clk) begin\n'+'\n'.join(updates)+'\nend\n'
 text+='''(* keep=1 *) logic [5:0] base_zero_groups;
for(genvar g=0;g<6;g++)begin:g_zero
 localparam integer N=(32-6*g<6)?32-6*g:6;
 zero_reduce #(.p_width(N)) u_zero(.i_value(bias_address_q[6*g+:N]),.o_zero(base_zero_groups[g]));
end
assign base_nonzero=!(&base_zero_groups);
npu_bias_presence u_presence(
 .i_frame_mode(bias_flags_q[0]),.i_base_nonzero(base_nonzero),.i_is_mode(bias_flags_q[1]),
 .i_ws_final_bias(bias_flags_q[2]),.i_frame_final(bias_flags_q[3]),.i_frame_init(bias_flags_q[4]),
 .i_address_zero(address_zero),.i_visible_base_nonzero(base_nonzero),.o_present(bias_present)'''
 text+=(', .o_frame_phase(frame_phase)' if name=='candidate' else '')+');\n'
 text+='''npu_bias_address_zero #(.p_width(32)) u_zero_address(
 .i_base(bias_address_q),.i_ws_channel(ws_channel_q),.i_is_channel(is_channel_q),
 .i_is_mode(bias_flags_q[1]),.o_zero(address_zero)'''
 if name=='candidate':text+=''',.i_issue_eligible(issue_eligible),.i_frame_mode(bias_flags_q[0]),
 .i_base_nonzero(base_nonzero),.i_frame_phase(frame_phase),.i_visible_base_nonzero(base_nonzero),
 .i_bias_available(bias_valid_q || bias_sleep_q),.i_frame_incomplete(!oa_calc_over_q),.i_output_complete(oa_calc_over_q),.o_issue(issue_qualified)'''
 text+=');\n'
 cc=[c.replace('.oa_calc_over(oa_calc_over_q)', '.oa_calc_over(frame_complete)').replace('.quant_params_valid(quant_params_valid_q)', '.quant_params_valid((quant_params_valid_q || (bias_flags_q[0] && !bias_flags_q[3])) && (!output_conditions_q[0] || output_conditions_q[1]))').replace('.fifo_full_flag(fifo_full_flag_q)', '.fifo_full_flag(fifo_full_flag_q && output_conditions_q[2])') for c in cc]
 text+='completion u_completion(.i_controls({bias_flags_q[0],frame_status_q[8:6],partial_sum_calc_over_q,frame_status_q[5:4],bias_flags_q[3],frame_status_q[3:2],oa_calc_over_q}),.o_complete(frame_complete));\n'
 text+='npu_controller #(.REG_WIDTH(REG_WIDTH),.SIZE(SIZE),.BUS_WIDTH(BUS_WIDTH),.DATA_WIDTH(DATA_WIDTH),.WEIGHT_WIDTH(WEIGHT_WIDTH)'+(', .p_external_ia_issue(1\'b1)' if name=='candidate' else '')+') u_controller(\n'+',\n'.join(cc)+');\n'
 text+='''assign frame_accept=send_ia_trigger && !ps_flags_q[0];
ps_frame_read_enable u_read_enable(
 .i_request(ps_flags_q[1] && !ps_flags_q[0]),.i_accept(frame_accept),.i_accepted(ps_flags_q[2]),
 .i_first_ready(ps_flags_q[3]),.i_continue_ready(ps_flags_q[4]),.i_fault(ps_flags_q[5]),.o_read_enable(frame_read));
assign memory_read_enable=!ps_flags_q[7]?4'b0:ps_flags_q[8]?mem_i_ps_read_en_q:{4{frame_read}};
ia_ps_channel_ram #(.p_shared_write_stage(1'b1),.p_ia_nonempty_writes(1'b1),
 .p_allow_inactive_return_updates(1'b1),.p_paired_ia_ports(1'b1),
 .p_bank_bytes(8192),.p_total_bytes(57344)) u_ram(
'''+',\n'.join(rc)+');\nendmodule\n'
 completion_model=runpy.run_path(str(ROOT/'test/matrix_frame_complete/run.py'))['model']
 parent=(subprocess.check_output(['git','show',reference+':rtl/npu/top/npu_matrix_engine.sv'],cwd=ROOT,text=True) if name=='reference' else (ROOT/'rtl/npu/top/npu_matrix_engine.sv').read_text())
 completion=completion_model(parent,'completion')
 if 'assign frame_issue_incomplete' in completion:
  completion=completion.replace('logic exec_oa_complete;','logic exec_oa_complete;\nlogic frame_issue_incomplete;')
 text+=completion
 if name=='candidate':text=text.replace('.i_accept(frame_accept)', '.i_accept(send_ia_trigger),.i_accept_permit(!ps_flags_q[0])')
 text=text.replace('.i_frame_incomplete(!oa_calc_over_q)', '.i_frame_incomplete(!(frame_status_q[8] && (frame_status_q[7] && (frame_status_q[6] || partial_sum_calc_over_q) && (!bias_flags_q[3] || frame_status_q[3] || (frame_status_q[2] && oa_calc_over_q))) && (frame_status_q[5] || frame_status_q[4])))')
 wrapper=folder/'measure.sv';wrapper.write_text(text)
 cases[name]={'top':'measure','sources':[str(wrapper),*map(str,copied.values())],
 'options':['-DSYNTHESIS=1','-DXILINX_FPGA=1'],'configuration':'完整偏置及控制器到共享 RAM 的组合连接'}
(OUT/'cases.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2)+'\n')

if args.prepare_only:
 sys.exit(0)
subprocess.run([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--case-config',OUT/'cases.json',
 '--cases',*cases,'--out',OUT/'pre','--through','pre_lut'],cwd=ROOT,check=True)
report=dict(reference_commit=reference,configuration='生产控制路径、全部公开输入输出及真实共享 RAM',cases={})
for label in cases:
 folder=OUT/'mapped'/label
 subprocess.run([sys.executable,ROOT/'scripts/fpga/remap_fpga_luts.py','--source',OUT/'pre'/label,
  '--out',folder,'--mode','physical-cost','--delay-target-ps','6667','--wire-delay-ps','300',
  '--max-lut-inputs','8','--discard-abc9-temporaries'],cwd=ROOT,check=True)
 metrics=json.loads((folder/'metrics.json').read_text())
 module=json.loads((folder/'mapped.json').read_text())['modules']['measure']
 for cell,origin in register_origins(OUT/'pre'/label/'pre_lut.il','measure').items():
  if cell in module['cells']:module['cells'][cell].setdefault('attributes',{})['fpga_register_origin']=origin
 paths={}
 for group,prefixes in {'bias':['bias_address_q','ws_channel_q','is_channel_q'],
                        'frame':['frame_status_q','partial_sum_calc_over_q','oa_calc_over_q'],
                        'mode':['bias_flags_q']}.items():
  paths[group]=connected_paths(module,limit=2,group_limit=2,
   root_filter=lambda name,cell,port,prefixes=prefixes:any(cell.get('attributes',{}).get('fpga_register_origin','').startswith(prefix) for prefix in prefixes))
 all_paths=connected_paths(module,limit=4,group_limit=4)
 synthesis=json.loads((folder/'summary.json').read_text())
 if not all_paths['graph_complete'] or not synthesis['functional_verification']['passed']:
  raise RuntimeError('完整组合图或综合映射验证未完成')
 report['cases'][label]=dict(resources=metrics['resources'],complete_paths=all_paths,selected_paths=paths,
  mapped_sha256=hashlib.sha256((folder/'mapped.json').read_bytes()).hexdigest())
 print(label,metrics['resources']['logic_lut_cells'],all_paths['longest_register_path_cells'],
  {group:value['longest_register_path_cells'] for group,value in paths.items()},flush=True)
report['runner_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
(OUT/'measurement.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
