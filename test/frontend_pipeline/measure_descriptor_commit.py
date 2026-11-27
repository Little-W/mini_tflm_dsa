#!/usr/bin/env python3
"""按 xc7 物理 LUT 成本比较完整描述符提交模块的组合路径。"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import runpy
import shlex
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'rtl/npu/conv/conv_descriptor_commit.sv'
REFERENCE=Path(__file__).with_name('descriptor_commit_reference.sv')


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    text=SOURCE.read_text();ports=[]
    for line in text.splitlines():
        m=re.match(r'\s*(input|output)\s+(?:wire )?(.+?)\s+([io]_\w+),?\s*//',line)
        if m:ports.append(m.groups())
    parameters=re.findall(r'^\s*parameter (?:int|bit) (\w+)',text,re.M)
    header=text[text.index('module conv_descriptor_commit #('):text.index('  //! 0.')]
    declarations='\n'.join(t+' saved_'+n+';'for d,t,n in ports if d=='input')+'\n'
    declarations+='\n'.join(t+' result_'+n+';'for d,t,n in ports if d=='output')
    assignments='\n'.join('saved_'+n+' <= '+n+';'if d=='input'else n+' <= result_'+n+';'for d,t,n in ports)
    connections=','.join('.'+n+'('+('saved_'if d=='input'else'result_')+n+')'for d,t,n in ports)
    library=out/'physical_lut_cost.lut'
    library.write_text('1 1 127\n2 1 127 238\n3 1 127 238 407\n4 1 127 238 407 472\n'
                       '5 1 127 238 407 472 631\n6 1 127 238 407 472 631 642\n'
                       '7 2 470 524 635 804 869 1028 1039\n8 4 465 592 646 757 926 991 1150 1161\n')
    resolver=runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))
    sys.path.insert(0,str(ROOT/'scripts/fpga'));from netlist_metrics import resources,connected_paths,register_origins
    report={'parameters':{'coordinate_width':35,'lanes':8,'slot_width':6,'line_bytes':128},
            'mapping':{'wire_delay_ps':300,'target_ps':6667,'library_sha256':digest(library)},'cases':{},'source_sha256':{}}
    for name,module,source in [('reference','conv_descriptor_commit_reference',REFERENCE),('candidate','conv_descriptor_commit',SOURCE)]:
        top='registered_'+name;folder=out/name;folder.mkdir(exist_ok=True)
        wrapper=folder/'registered.sv'
        wrapper.write_text(header.replace('module conv_descriptor_commit #(','module '+top+' #(',1).replace(') (',') (\ninput logic clk,',1)+
            declarations+'\nalways_ff @(posedge clk)begin\n'+assignments+'\nend\n'+module+' #('+
            ','.join('.'+n+'('+n+')'for n in parameters)+') u_commit('+connections+');\nendmodule\n')
        sources=resolver['with_dependencies']([source,wrapper],ROOT)
        for path in resolver['input_files'](sources,ROOT):
            if path.is_relative_to(ROOT):report['source_sha256'][str(path.relative_to(ROOT))]=digest(path)
        pre,mapped,script,log=[folder/n for n in ('pre.il','mapped.json','run.ys','run.log')]
        script.write_text(shlex.join(['read_slang','--best-effort-hierarchy','--top',top,'-DSYNTHESIS=1',
             '-I'+str(ROOT/'include'),'-Gp_lanes=8','-Gp_slot_w=6','-Gp_line_bytes=128',*map(str,sources)])+'\n'+
            'read_verilog -lib -specify -overwrite +/xilinx/cells_sim.v\nread_verilog -lib -overwrite +/xilinx/cells_xtra.v\n'+
            f'hierarchy -check -top {top}\nflatten -noscopeinfo\nsynth_xilinx -top {top} -family xc7 -noiopad -noclkbuf -flatten -run begin:map_luts\n'+
            f'write_rtlil {pre}\nopt_expr -mux_undef -noclkinv\nread_verilog -icells -lib -specify +/xilinx/abc9_model.v\n'+
            f'scratchpad -set abc9.verify 1\nabc9 -W 300 -lut {library} -D 6667\nclean\nxilinx_srl -fixed -minlen 3\n'+
            'techmap -map +/xilinx/lut_map.v -map +/xilinx/cells_map.v -D LUT_WIDTH=6\nxilinx_dffopt\nopt_lut_ins -tech xilinx\n'+
            f'synth_xilinx -top {top} -family xc7 -noiopad -noclkbuf -flatten -run finalize:\n'+
            'setattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\nflatten -noscopeinfo\nopt_clean\ncheck -assert\n'+f'write_json {mapped}\n')
        with log.open('w')as output:
            subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],
                           stdout=output,stderr=subprocess.STDOUT,check=True,timeout=240)
        netlist=json.loads(mapped.read_text())['modules'][top]
        for key,value in register_origins(pre).items():
            if key in netlist['cells']:netlist['cells'][key].setdefault('attributes',{})['fpga_register_origin']=value
        netlist['cells']={key:value for key,value in netlist['cells'].items()if value['type']!='$scopeinfo'}
        # 当前参数下，坐标字段之前包含两组填充标志、保存字标签、通道范围和三项地址。
        coordinate_first=191+8-3
        def coordinate_sink(name,cell,port):
            match=re.search(r'o_committing_tile_packed \[(\d+)\]',cell.get('attributes',{}).get('fpga_register_origin',''))
            return match is not None and coordinate_first<=int(match[1])<coordinate_first+70
        paths=connected_paths(netlist,limit=8,group_limit=8)
        coordinates=connected_paths(netlist,limit=8,group_limit=8,sink_filter=coordinate_sink)
        if not paths['graph_complete']or not coordinates['graph_complete']:raise RuntimeError('描述符提交组合连接统计不完整')
        report['cases'][name]={'resources':resources(netlist['cells']),'paths':paths,'coordinate_paths':coordinates,
                               'log_sha256':digest(log),'wrapper_sha256':digest(wrapper)}
        print('DESCRIPTOR_COMMIT_MAPPING '+json.dumps({'case':name,
             'lut':report['cases'][name]['resources']['logic_lut_cells'],'all_depth':paths['longest_register_path_cells'],
             'coordinate_depth':coordinates['longest_register_path_cells']}),flush=True)
    if any(digest(ROOT/path)!=value for path,value in report['source_sha256'].items()):raise RuntimeError('映射过程中源码发生变化')
    report['passed']=True
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
