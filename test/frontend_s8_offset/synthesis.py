#!/usr/bin/env python3
"""映射实际前端写入表达式，比较状态选择到数值结果的寄存器路径。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/fpga'))
from netlist_metrics import connected_paths,register_origins,resources


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--proof',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    args=p.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    proof=json.loads((args.proof/'summary.json').read_text())
    if not proof['passed']:raise RuntimeError('Complete formal proof is required')
    ports=runpy.run_path(str(ROOT/'test/frontend_s8_offset/formal.py'))['PORTS']
    declarations=[];updates=[];connections=[]
    for name,width in ports:
        saved=name+'_saved'
        declarations.append('logic ['+width+'-1:0] '+saved+';')
        updates.append(saved+' <= '+name+';')
        connections.append('.'+name+'('+saved+')')
    cases={}
    for label in ('reference','current'):
        folder=out/label;folder.mkdir(exist_ok=True)
        source=folder/'registered.sv'
        source.write_text((args.proof/(label+'.sv')).read_text()+'\nmodule write_data_registered #(parameter int LANES=4, TILE_COUNT_W=5, OBSERVED_W=49+$clog2(LANES+1)+18*LANES)(\ninput logic clk,\n'+
          ',\n'.join('input logic ['+width+'-1:0] '+name for name,width in ports)+
          ',\noutput logic [OBSERVED_W-1:0] o_observed\n);\n'+ '\n'.join(declarations)+
          '\nlogic [OBSERVED_W-1:0] calc_observed;\nalways_ff @(posedge clk)begin\n'+ '\n'.join(updates)+
          '\no_observed <= calc_observed;\nend\n'+label+'_write_data #(.LANES(LANES),.TILE_COUNT_W(TILE_COUNT_W)) u_calc('+','.join(connections)+',.observed(calc_observed));\nendmodule\n')
        mapped,pre_lut,script=folder/'mapped.json',folder/'pre_lut.il',folder/'run.ys'
        top='write_data_registered'
        script.write_text('read_slang --keep-hierarchy --top '+top+' '+shlex.quote(str(source))+'\n'+
          'hierarchy -check -top '+top+'\n'+
          'synth_xilinx -top '+top+' -family xc7 -noiopad -noclkbuf -flatten -run begin:map_luts\n'+
          'write_rtlil '+shlex.quote(str(pre_lut))+'\n'+
          'synth_xilinx -top '+top+' -family xc7 -noiopad -noclkbuf -flatten -run map_luts:\n'+
          'check -assert\nstat -tech xilinx\nwrite_json '+shlex.quote(str(mapped))+'\n')
        log=folder/'synthesis.log'
        with log.open('w') as stream:
            subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True)
        module=json.loads(mapped.read_text())['modules'][top]
        for name,origin in register_origins(pre_lut).items():
            if name in module['cells']:module['cells'][name].setdefault('attributes',{})['fpga_register_origin']=origin
        for name in list(module['cells']):
            if module['cells'][name]['type']=='$scopeinfo':del module['cells'][name]
        all_paths=connected_paths(module,limit=6,group_limit=6)
        paths=connected_paths(module,limit=8,group_limit=8,
            root_filter=lambda n,c,p:bool(re.search(r'(i_state_saved|u_calc\.state)(?: |$)',c.get('attributes',{}).get('fpga_register_origin',''))),
            sink_filter=lambda n,c,p:p=='D' and bool(re.search(r'o_observed \[(?:[0-5]?[0-9]|6[0-3])\]$',c.get('attributes',{}).get('fpga_register_origin',''))))
        if not all_paths['graph_complete'] or not paths['graph_complete']:raise RuntimeError('Incomplete mapped graph')
        row=dict(resources=resources(module['cells']),longest_register_path_cells=all_paths['longest_register_path_cells'],
          state_to_data=paths,all_paths=all_paths,source_sha256=digest(source),mapped_sha256=digest(mapped),pre_lut_sha256=digest(pre_lut),log_sha256=digest(log))
        cases[label]=row;(folder/'summary.json').write_text(json.dumps(row,indent=2)+'\n')
        print(label,row['resources']['logic_lut_cells'],row['resources']['carry4'],row['longest_register_path_cells'],paths['longest_register_path_cells'],flush=True)
    result=dict(passed=True,reference_commit=proof['reference_commit'],source_sha256=proof['source_sha256'],
      reference_sha256=proof['reference_sha256'],configuration=dict(LANES=4,TILE_COUNT_W=5),
      cases=cases,proof_summary_sha256=digest(args.proof/'summary.json'),metrics_tool_sha256=digest(ROOT/'scripts/fpga/netlist_metrics.py'))
    (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n')


if __name__=='__main__':main()
