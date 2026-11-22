#!/usr/bin/env python3
"""验证 IA 请求寄存与参考模块在相同接受授予下的完整状态对应。"""
import argparse,hashlib,json,re,shlex,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
SOURCES=[Path('rtl/npu/loaders')/(name+'.sv')for name in ('ia_loader','ia_loader_ctrl','ia_loader_cache_mgr')]+[Path('rtl/npu/compute/select_add.sv')]
CASES={
 'production':dict(SIZE=16,BUS_WIDTH=64,COUNT_WIDTH=29,CACHE_BLOCKS=32,EXTERNAL_RAM=1,ORDERED_JOB=1,PS_FRAME_COUNT=16,p_dma_source_layout=1,p_shared_write_stage=1),
 'generic':dict(SIZE=16,BUS_WIDTH=32,COUNT_WIDTH=8,CACHE_BLOCKS=4,EXTERNAL_RAM=1,ORDERED_JOB=0),
 'small':dict(SIZE=4,BUS_WIDTH=32,COUNT_WIDTH=8,CACHE_BLOCKS=2,EXTERNAL_RAM=0,ORDERED_JOB=1),
}
def digest(path):
 return hashlib.sha256(path.read_bytes()).hexdigest()
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--tool-root',type=Path,default=ROOT);p.add_argument('--source-root',type=Path,required=True);p.add_argument('--reference-root',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--cases',nargs='+',choices=tuple(CASES),default=list(CASES));p.add_argument('--registered',type=int,choices=(0,1),default=1);a=p.parse_args();a.out=a.out.resolve();a.out.mkdir(parents=True,exist_ok=True)
roots={'reference':a.reference_root.resolve(),'current':a.source_root.resolve()};paths={};wrappers={};hashes={}
for label,root in roots.items():
 paths[label]=[root/f for f in SOURCES]+sorted(q for q in(root/'rtl/common').iterdir()if q.suffix in('.v','.sv'))
 hashes[label]={str(q.relative_to(root)):digest(q)for q in paths[label]}
 source=(root/SOURCES[0]).read_text();header=source[:source.index(');')+2].replace('module ia_loader #(','module ia_loader_valid #(',1)
 parameters=re.findall(r'parameter\s+(?:int\s+unsigned|bit|integer)\s+(\w+)\s*=',header)
 body='\nlogic[127:0]raw_port_data[0:1],raw_shared_data;\n'
 if label=='reference'and a.registered:
  body+='''logic direct_request,effective_grant;
 always_ff @(posedge clk or negedge rst_n)begin
  if(!rst_n)load_ia_req<=1'b0;
  else if(init_cfg||cache_flush)load_ia_req<=1'b0;
  else load_ia_req<=direct_request;
 end
 assign effective_grant=load_ia_granted&&load_ia_req;
'''
 core_parameters=[f'.{name}({name})'for name in parameters if name!='p_register_dma_request']
 if label=='current':core_parameters.append(f'.p_register_dma_request({a.registered})')
 body+='ia_loader #(\n'+',\n'.join(core_parameters)+')u_core(\n'
 ports=['.ram_port_wr_data(raw_port_data)','.ram_shared_wr_data(raw_shared_data)']
 if label=='reference'and a.registered:ports+=['.load_ia_req(direct_request)','.load_ia_granted(effective_grant)']
 body+=',\n'.join(ports)+',.*);\n'
 body+="for(genvar port_index=0;port_index<2;port_index++)assign ram_port_wr_data[port_index]=ram_port_wr_en[port_index]?raw_port_data[port_index]:128'd0;\nassign ram_shared_wr_data=(|ram_port_wr_en)?raw_shared_data:128'd0;\nendmodule\n"
 wrappers[label]=a.out/(label+'_valid.sv');wrappers[label].write_text(header+body)
report={'passed':False,'inputs_constrained':False,'registered_request':bool(a.registered),'reference_connection':'The reference receives the same delayed reservation and qualified external grant; all remaining outputs and matched internal states are compared at each cycle.','source_sha256':hashes,'wrapper_sha256':{k:digest(v)for k,v in wrappers.items()},'runs':[]}
for name in a.cases:
 opts=['-DSYNTHESIS=1','-DXILINX_FPGA=1','-GRAM_WORD_ADDR_WIDTH=12']+['-G'+k+'='+str(v)for k,v in CASES[name].items()]
 commands=[]
 for label in ('reference','current'):
  commands+=['read_slang --top ia_loader_valid '+shlex.join(opts+[str(q)for q in paths[label]+[wrappers[label]]]),'prep -top ia_loader_valid -flatten','memory_map','async2sync','opt_clean','rename -hide w:*ram_port_wr_data* w:*ram_shared_wr_data* w:raw_port_data w:raw_shared_data w:*cache_slot_rows* w:*u_cache_mgr.slot_rows w:u_core.load_ia_granted w:u_core.load_ia_req','rename ia_loader_valid '+label,'design -stash '+label]
 commands+=['design -copy-from reference -as reference reference','design -copy-from current -as current current','equiv_make reference current equivalent','hierarchy -top equivalent','equiv_simple -seq 2','opt_clean','equiv_induct -seq 3','equiv_status -assert']
 ys=a.out/(name+'.ys');log=a.out/(name+'.log');ys.write_text('\n'.join(commands)+'\n')
 with log.open('w')as f:r=subprocess.run([sys.executable,str(a.tool_root.resolve()/'scripts/fpga/open_fpga_synth.py'),'--worker',str(ys)],stdout=f,stderr=subprocess.STDOUT,timeout=600)
 text=log.read_text();match=re.search(r'Of those cells (\d+) are proven and (\d+) are unproven',text);row={'case':name,'parameters':CASES[name],'passed':r.returncode==0 and'Equivalence successfully proven'in text,'equivalent_bits':int(match[1])if match else None,'log_sha256':digest(log),'script_sha256':digest(ys)}
 report['runs'].append(row);report['passed']=all(x['passed']for x in report['runs']);(a.out/'summary.json').write_text(json.dumps(report,indent=2)+'\n');print(row,flush=True);assert row['passed'],log
assert hashes=={label:{str(q.relative_to(roots[label])):digest(q)for q in values}for label,values in paths.items()}
