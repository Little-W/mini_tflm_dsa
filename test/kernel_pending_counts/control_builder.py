from pathlib import Path
import re
import sys
p=Path(sys.argv[1]).resolve()
ref=(p/'reference/kernel_loader_ctrl.sv').read_text()
ref=re.sub(r'\b(kernel_loader_ctrl|kernel_count_increment|kernel_count_compare)\b',lambda m:m[0]+'_reference',ref)
(p/'control_reference.sv').write_text(ref)
s=Path('rtl/npu/loaders/kernel_loader_ctrl.sv').read_text()
header=s.split(');',1)[0]
inputs=[];outputs=[]
for line in header.splitlines():
 m=re.match(r'\s*(input|output)\s+logic\s*(signed\s+)?(\[[^\]]+\]\s*)?(\w+)(?:\s*=.*)?[,]?$',line.rstrip().rstrip(','))
 if not m:continue
 direction,sign,width,name=m.groups();decl='logic '+(sign or '')+(width or '')
 (inputs if direction=='input' else outputs).append((name,decl))
assert len(inputs)==24,(len(inputs),inputs)
old_first=(p/'reference/kernel_loader_ctrl.sv').read_text().split('endmodule',1)[0]
states=sorted(set(re.findall(r'\b([A-Za-z_][A-Za-z_0-9]*)\s*<=',old_first)))
ports=[f'    input {decl}{"requested_rst_n" if name=="rst_n" else name}' for name,decl in inputs]
ports+=['    output logic equivalent,bounds']
src='module pending_control_proof #(parameter int SIZE=16, REG_WIDTH=32, COUNT_WIDTH=29) (\n'+',\n'.join(ports)+'\n);\n'
src+='    logic initial_cycle=1; logic rst_n; always_ff @(posedge clk) initial_cycle<=0; assign rst_n=requested_rst_n&&!initial_cycle;\n'
src+='    logic [3*COUNT_WIDTH-1:0] pending_loads,pending_sends;\n'
src+='    assign pending_loads=gold.issued_count-gold.loaded_count;\n    assign pending_sends=gold.issued_count-gold.sent_count;\n'
for label in ('gold','gate'):
 for name,decl in outputs:src+=f'    {decl}{label}_{name};\n'
 connect=[]
 for name,decl in inputs:
  value=name
  if name=='load_weight_granted':value='load_weight_granted && pending_loads < 2 && pending_sends < 3'
  if name=='load_done':value='load_done && pending_loads != 0'
  if name=='buf_weight_sending_done':value='buf_weight_sending_done && pending_sends > pending_loads'
  connect.append(f'.{name}({value})')
 connect +=[f'.{name}({label}_{name})' for name,decl in outputs]
 mod='kernel_loader_ctrl_reference' if label=='gold' else 'kernel_loader_ctrl'
 src+=f'    {mod} #(.SIZE(SIZE),.REG_WIDTH(REG_WIDTH),.COUNT_WIDTH(COUNT_WIDTH)) {label} (\n'+',\n'.join('        '+x for x in connect)+'\n    );\n'
compare=[f'gold.{x} == gate.{x}' for x in states]+[f'gold_{name} == gate_{name}' for name,decl in outputs]
src+='    assign equivalent = !rst_n || ('+' &&\n        '.join(compare)+');\n'
src+='    assign bounds = !rst_n || (pending_loads <= 2 && pending_sends <= 3 && pending_loads <= pending_sends);\nendmodule\n'
(p/'pending_control_proof.sv').write_text(src)
(p/'control.ys').write_text(f'''read_slang -D SYNTHESIS=1 -D ASIC_SYNTHESIS=1 --top pending_control_proof {p/'pending_control_proof.sv'} {p/'control_reference.sv'} rtl/npu/loaders/kernel_loader_ctrl.sv rtl/common/add_equal.sv rtl/common/add3_equal.sv rtl/common/parallel_prefix_add.sv
prep -top pending_control_proof -flatten
async2sync
opt -full
sat -verify -tempinduct -seq 2 -maxsteps 6 -timeout 45 -set-init-zero -prove equivalent 1 -prove bounds 1 -show-inputs -show-outputs
''')
print('State fields',len(states),'public outputs',len(outputs))
