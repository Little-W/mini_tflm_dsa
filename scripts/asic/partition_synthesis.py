#!/usr/bin/env python3
"""Map an NPU bottom-up with reusable, independently synthesized modules."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import shutil
import subprocess
import time


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def rtl_sources(root):
    """统一收集计算模块、公共 RTL 和 SRAM 宏封装的源文件。"""
    return sorted(path for folder in ('rtl/npu', 'rtl/common', 'asic/rtl')
                  for path in (root / folder).rglob('*')
                  if path.suffix in ('.sv', '.v'))


def execute(script,directory,env):
    directory.mkdir(parents=True,exist_ok=True)
    path=directory/'run.tcl';path.write_text(script)
    start=time.monotonic()
    timeout=float(env.get('DESIGN_PARTITION_TIMEOUT',300))
    memory_limit=float(env.get('DESIGN_PARTITION_MEMORY_GIB',8))*1024**2
    exceeded=None
    with (directory/'synthesis.log').open('w') as log:
        process=subprocess.Popen(['dc_shell','-f',str(path)],cwd=directory,env=env,
            stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        selector=selectors.DefaultSelector();selector.register(process.stdout,selectors.EVENT_READ)
        last_check=0
        while selector.get_map():
            for key,_ in selector.select(timeout=1):
                data=os.read(key.fd,65536)
                if data:log.write(data.decode(errors='replace'));log.flush()
                else:selector.unregister(key.fileobj)
            now=time.monotonic()
            if now-last_check>=1 and process.poll() is None:
                last_check=now
                tool_pids=[];memory=0
                for status in Path('/proc').glob('[0-9]*/status'):
                    try:
                        command=(status.parent/'cmdline').read_bytes()
                        if b'common_shell_exec' not in command or str(path).encode() not in command:continue
                        tool_pids.append(int(status.parent.name))
                        usage=status.read_text()
                        memory+=sum(int(v) for v in re.findall(r'^Vm(?:RSS|Swap):\s*(\d+)',usage,re.M))
                    except (FileNotFoundError,PermissionError,ProcessLookupError):continue
                if now-start>timeout:exceeded='time budget'
                if memory>memory_limit:exceeded='memory budget'
                if exceeded:
                    log.write('Synthesis exceeded '+exceeded+'\n');log.flush()
                    for pid in tool_pids:
                        try:os.kill(pid,signal.SIGTERM)
                        except ProcessLookupError:pass
        process.wait(timeout=15)
    lines=(directory/'synthesis.log').read_text()
    if exceeded or process.returncode or re.search(r'^(Error:|Fatal:)',lines,re.M):
        raise RuntimeError('DC execution did not complete: '+str(directory/'synthesis.log'))
    return time.monotonic()-start


def setup(root):
    return f'''set sh_continue_on_error false
source {{{root}/asic/synthesis/scripts/1_common_setup.tcl}}
source {{{root}/asic/synthesis/scripts/2_dc_setup.tcl}}
set_app_var simplified_verification_mode true
'''


def export(root,out,elab,env):
    directory=out/'generic';directory.mkdir(exist_ok=True)
    metadata=directory/'input.json'
    input_sha=digest(elab)
    fresh=metadata.is_file() and json.loads(metadata.read_text()).get('input_sha256')==input_sha
    if not fresh or not (directory/'graph.tsv').is_file() or not (directory/'graph.tsv').stat().st_size:
        script=setup(root)+f'''read_ddc {{{elab}}}
set root_design [get_object_name [current_design]]
if {{![link]}} {{error "Unresolved design references"}}
set graph [open {{{directory}/graph.tmp}} w]
puts $graph "R\\t$root_design"
set designs [get_designs *]
foreach_in_collection design $designs {{
    set name [get_object_name $design]
    current_design $design
    puts $graph "D\\t$name"
    foreach_in_collection cell [get_cells -filter {{is_hierarchical == true}}] {{
        set reference [get_attribute $cell ref_name]
        if {{[sizeof_collection [get_designs -quiet $reference]] > 0}} {{
            puts $graph "E\\t$name\\t[get_object_name $cell]\\t$reference"
        }}
    }}
    write -format ddc -output [file join {{{directory}}} "$name.ddc"]
}}
close $graph
file rename -force {{{directory}/graph.tmp}} {{{directory}/graph.tsv}}
exit
'''
        execute(script,directory,env)
        if digest(elab)!=input_sha:raise RuntimeError('Elaborated DDC changed during export')
        metadata.write_text(json.dumps(dict(input_sha256=input_sha))+'\n')
    graph={};root_name=None
    for line in (directory/'graph.tsv').read_text().splitlines():
        parts=line.split('\t')
        if parts[0]=='R':root_name=parts[1]
        elif parts[0]=='D':graph.setdefault(parts[1],[])
        elif parts[0]=='E':graph.setdefault(parts[1],[]).append(parts[2:])
    return directory,root_name,graph


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[2])
    parser.add_argument('--elab-ddc',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--cache',type=Path,required=True)
    parser.add_argument('--std-db',type=Path,required=True)
    parser.add_argument('--libs',type=Path,required=True)
    parser.add_argument('--frequency',type=float,default=50)
    parser.add_argument('--force-raw',action='store_true')
    parser.add_argument('--compile-mode',choices=('quick','ultra'),default='quick')
    parser.add_argument('--timeout',type=float,default=300,help='Time budget in seconds per module')
    parser.add_argument('--max-memory-gib',type=float,default=8,help='Resident plus swapped memory budget per module')
    parser.add_argument('--only',help='Map only the named design and its dependencies')
    parser.add_argument('--logic-block-cells',type=int,default=0,
        help='Maximum generic cells per synthesis block in selected modules; zero disables grouping')
    parser.add_argument('--split-modules',nargs='+',default=[
        'vector_engine','bias_loader_buffer','ps_frame_store','ps_adaptive_encoder',
        'ps_adaptive_decoder','vec_requant_full','vec_s8_to_fifo_full',
        'vec_s16_to_fifo','compute_core','npu_top'],
        help='RTL modules eligible for generic-cell grouping')
    args=parser.parse_args();started=time.monotonic();root=args.root.resolve();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    cache=args.cache.resolve();cache.mkdir(parents=True,exist_ok=True)
    std=args.std_db.resolve();libs=args.libs.resolve();frequency=args.frequency
    env=os.environ.copy();env.update(PROJ_PATH=str(root/'asic/synthesis'),PROJ_ROOT=str(root),
        PROJ_TEMP=str(out),DESIGN_MAX_CORES='1',DESIGN_COMPILE_MODE='quick',
        DESIGN_TARGET_FREQ_MHZ=str(frequency),STD_DB_PATH=str(std.parent),STD_DB_LIST=std.name,
        MEM_DB_PATH=str(libs),MEM_DB_LIST='RAMTP128X16_tt_1p10v_1p10v_25c.db RAMTP1024X16_tt_1p10v_1p10v_25c.db',
        SYN_STD_LIB_NAME=std.stem,SYN_OPER_CONDITION='tt_v1p1_25c',
        DESIGN_PARTITION_TIMEOUT=str(args.timeout),DESIGN_PARTITION_MEMORY_GIB=str(args.max_memory_gib))
    sources=rtl_sources(root)
    source_hashes={str(p.relative_to(root)):digest(p) for p in sources}
    prior=json.loads((args.elab_ddc.parent/'run.json').read_text())
    for name,value in prior['source_sha256'].items():
        if name.startswith(('rtl/npu/','rtl/common/','asic/rtl/')) and source_hashes.get(name)!=value:
            parser.error('Elaborated RTL differs from current source: '+name)
    if prior['force_raw']!=args.force_raw:parser.error('Elaborated storage mode differs')
    generic,top,graph=export(root,out,args.elab_ddc.resolve(),env)
    modules={}
    global_sources=[]
    for path in sources:
        text=path.read_text()
        if re.search(r'\bpackage\s',text):global_sources.append(digest(path))
        for module in re.findall(r'\bmodule\s+(\w+)',text):modules[module]=path
    global_sources+= [digest(p) for p in (root/'include').rglob('*.vh')]
    libraries=[digest(std)]+[digest(p) for p in sorted(libs.glob('*.db'))]
    completed={};records=[]
    def map_design(name):
        if name in completed:return completed[name]
        children={reference:map_design(reference) for _,reference in graph[name]}
        matched=[module for module in modules if name==module or name.startswith(module+'_')]
        if not matched:raise ValueError('Cannot identify RTL module '+name)
        module=max(matched,key=len)
        source=modules[module]
        if digest(source)!=source_hashes[str(source.relative_to(root))]:
            raise RuntimeError('RTL changed while mapping '+name)
        mode=args.compile_mode
        representation=args.force_raw if re.search(r'`(?:ifn?def|elsif)\s+(?:GEMMORA_)?PS_FORCE_RAW',source.read_text()) else False
        key_data=dict(name=name,source=digest(source),global_sources=global_sources,libraries=libraries,
            frequency=frequency,representation=representation,children={k:v['key'] for k,v in children.items()},flow=4)
        if mode!='quick':key_data['compile_mode']=mode
        block_cells=args.logic_block_cells if module in args.split_modules else 0
        if block_cells:
            if block_cells<128:parser.error('Synthesis blocks require at least 128 generic cells')
            key_data['logic_block_cells']=block_cells
        key=hashlib.sha256(json.dumps(key_data,sort_keys=True).encode()).hexdigest()
        directory=cache/key;file=directory/'mapped.ddc';result=dict(key=key,file=str(file),reference='PS_CACHE_'+name)
        reused=file.is_file() and (directory/'metadata.json').is_file()
        result['reused']=reused
        if not reused:
            script=setup(root)+f'read_ddc {{{generic}/{name}.ddc}}\n'
            for child in children.values():script+=f'read_ddc {{{child["file"]}}}\n'
            script+=f'current_design {name}\n'
            linked_instances={}
            for instance,reference in graph[name]:
                linked_instances.setdefault(reference,[]).append(instance)
            for reference,instances in linked_instances.items():
                cells=' '.join('{'+instance+'}' for instance in instances)
                script+=f'change_link [get_cells [list {cells}]] {children[reference]["reference"]}\n'
            script+='if {![link]} {error "Unresolved partition references"}\n'
            script+='''set child_cells [get_cells -filter {is_hierarchical == true}]
if {[sizeof_collection $child_cells]>0} {set_dont_touch $child_cells true}
set_operating_conditions $std_operating_condition -library $std_lib_name
set_fix_multiple_port_nets -all -exclude_clock_network
'''
            if block_cells:
                script+=f'''set parent_name [get_object_name [current_design]]
set generic_cells [get_cells -filter {{is_hierarchical == false}}]
set generic_count [sizeof_collection $generic_cells]
set blocks {{}}
if {{$generic_count>{block_cells}}} {{
    while {{$generic_count>{block_cells}}} {{
        set finish [expr {{{block_cells}-1}}]
        set block_name ${{parent_name}}_logic_[llength $blocks]
        set instance synthesis_block_[llength $blocks]
        if {{![group [index_collection $generic_cells 0 $finish] -design_name $block_name -cell_name $instance]}} {{
            error "Cannot group generic synthesis cells"
        }}
        lappend blocks $block_name
        current_design $parent_name
        set remaining [get_cells -filter {{is_hierarchical == false}}]
        set count [sizeof_collection $remaining]
        if {{$count>=$generic_count}} {{error "Generic synthesis grouping made no progress"}}
        set generic_cells $remaining
        set generic_count $count
    }}
    foreach block $blocks {{
        current_design $block
        compile -map_effort medium -area_effort none -no_design_rule
        set remaining [get_cells -hierarchical -filter {{ref_name =~ GTECH*}}]
        if {{[sizeof_collection $remaining]>0}} {{error "Unmapped grouped logic"}}
        puts "LOGIC_BLOCK_MAPPED $block"
    }}
    current_design $parent_name
    set_dont_touch [get_cells -filter {{is_hierarchical == true}}] true
}}
'''
            constraints='''if {[sizeof_collection [get_ports -quiet clk]]>0} {
    create_clock -name CORE_CLK -period $CLK_PERIOD_NS [get_ports clk]
    set_clock_uncertainty -setup [expr .1*$CLK_PERIOD_NS] [all_clocks]
    set_clock_uncertainty -hold [expr min(.05*$CLK_PERIOD_NS,.125)] [all_clocks]
    set inputs [remove_from_collection [all_inputs] [get_ports -quiet {clk rst_n}]]
    if {[sizeof_collection $inputs]>0} {
        set_input_delay -max [expr .2*$CLK_PERIOD_NS] -clock CORE_CLK $inputs
        set_input_delay -min 0 -clock CORE_CLK $inputs
    }
    if {[sizeof_collection [all_outputs]]>0} {
        set_output_delay -max [expr .2*$CLK_PERIOD_NS] -clock CORE_CLK [all_outputs]
        set_output_delay -min 0 -clock CORE_CLK [all_outputs]
    }
} else {
    set_max_delay [expr .6*$CLK_PERIOD_NS] -from [all_inputs] -to [all_outputs]
}
if {[sizeof_collection [get_ports -quiet rst_n]]>0} {
    set_false_path -from [get_ports rst_n]
    set_ideal_network [get_ports rst_n]
}
'''
            if mode=='ultra':
                script+=constraints+'compile_ultra -no_autoungroup -no_boundary_optimization\n'
            else:
                script+='compile -map_effort medium -area_effort none -no_design_rule\n'+constraints
            script+=f'''report_area > {{{directory}/area.rpt}}
report_timing -max_paths 10 -nworst 1 -significant_digits 6 > {{{directory}/timing.rpt}}
set unmapped [get_cells -hierarchical -filter {{ref_name =~ GTECH*}}]
if {{[sizeof_collection $unmapped]>0}} {{error "Partition contains unmapped logic"}}
reset_design
rename_design -prefix PS_CACHE_ -update_links [current_design]
write -format ddc -hierarchy -output {{{file}}}
exit
'''
            elapsed=execute(script,directory,env)
            (directory/'metadata.json').write_text(json.dumps(dict(**key_data,elapsed_seconds=elapsed),indent=2)+'\n')
            print('MAPPED',name,f'{elapsed:.1f}s',flush=True)
        else:print('REUSED',name,flush=True)
        completed[name]=result;records.append(dict(name=name,**result));return result
    requested=args.only or top
    if requested not in graph:
        matches=[name for name in graph if name.startswith(requested+'_')]
        if len(matches)!=1:parser.error('Select an unambiguous partition name')
        requested=matches[0]
    result=map_design(requested)
    unchanged=all(digest(root/name)==value for name,value in source_hashes.items())
    summary=dict(passed=unchanged,top=top,requested=requested,frequency_mhz=frequency,
        force_raw=args.force_raw,source_sha256=source_hashes,parameters=prior['parameters'],
        source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),
        mapped_ddc=result['file'],records=records)
    summary.update(sources_unchanged=unchanged,compile_mode='hierarchical',elapsed_seconds=time.monotonic()-started,
        logic_block_cells=args.logic_block_cells,split_modules=args.split_modules,
        mapped_modules=sum(not r['reused'] for r in records),reused_modules=sum(r['reused'] for r in records))
    (out/'partitions.json').write_text(json.dumps(summary,indent=2)+'\n')
    if requested==top:
        shutil.copy2(result['file'],out/'npu_top_partition.ddc')
        (out/'run.json').write_text(json.dumps(summary,indent=2)+'\n')
    print('PARTITION_SYNTHESIS_PASS',requested,flush=True)


if __name__=='__main__':main()
