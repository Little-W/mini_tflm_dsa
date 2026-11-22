#!/usr/bin/env python3
"""展开实际 FPGA 分支并核对完整 NPU 的存储容量和计算单元。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scripts.capacity import config,elaboration


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--verilator',default='verilator-modern')
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    values=config.validate_config(config.selected_config(ROOT/'config/npu_fpga.mk'),check_budget=False)
    hashes=elaboration.sources_sha256()
    generic=elaboration.measure(values,verilator=args.verilator,output_dir=out/'generic')
    if not generic['passed']:raise RuntimeError('Generic capacity check failed')
    import pyosys
    library=Path(pyosys.__file__).parent/'share/xilinx/cells_sim.v'
    content=library.read_text();models=[]
    for name in ('LUT1','LUT2','LUT3','LUT4','LUT5','LUT6','LUT6_2','MUXF7','MUXF8','DSP48E1','FDRE','CARRY4'):
        match=re.search(r'^module '+name+r'\b.*?^endmodule',content,re.M|re.S)
        if not match:raise RuntimeError('Primitive model missing: '+name)
        models.append(match[0])
    clock_library=library.with_name('cells_xtra.v')
    clock_model=re.search(r'^module BUFGCE\b.*?^endmodule',clock_library.read_text(),re.M|re.S)
    if not clock_model:raise RuntimeError('Clock primitive declaration missing')
    models.append(clock_model[0])
    primitives=out/'xilinx_primitives.sv';primitives.write_text('\n\n'.join(models)+'\n')
    tree_path=out/'elaborated.tree.json'
    command=generic['command'].copy()
    command[command.index('-DASIC_SYNTHESIS')]='-DXILINX_FPGA'
    command[command.index('--json-only-output')+1]=str(tree_path)
    command[command.index('--Mdir')+1]=str(out/'obj')
    command.append(str(primitives))
    with (out/'elaboration.log').open('w') as log:
        subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
    tree=json.loads(tree_path.read_text());state=elaboration.inventory(tree)
    counts=state['module_instances']
    expected=generic['expected_buffer_arrays_bits']
    if state['buffer_arrays_bits']!=expected:raise RuntimeError('FPGA storage capacity differs')
    if state['register_arrays_bits']!=generic['expected_register_arrays_bits']:raise RuntimeError('FPGA metadata dimensions differ')
    if counts.get('ia_ps_channel_ram')!=1 or counts.get('ia_ps_shared_ram',0)!=0:raise RuntimeError('Fixed channel memory absent')
    if counts.get('BUFGCE')!=1:raise RuntimeError('Clock buffer declaration count differs')
    if counts.get('ws_systolic_cell')!=256 or counts.get('registered_vector_pe')!=8:
        raise RuntimeError('Compute array dimensions differ')
    pe_parameters=elaboration.constant_parameters(tree,'registered_vector_pe',('p_accumulator_preselected',))
    if counts.get('vector_pe',0)!=counts['registered_vector_pe']:
        raise RuntimeError('Registered FPGA vector arithmetic differs')
    if counts.get('ps_frame_store')!=1 or state['declaration_counts']['ia_ps_shared_ram']!=9:raise RuntimeError('Storage instance count differs')
    memories=[d for d in state['sequential_declarations'] if d['buffer_category']=='ia_ps_shared_ram']
    expected_shapes=[128*512]+[128*128]*4+[128*640]*4
    if sorted(d['bits'] for d in memories)!=sorted(expected_shapes):raise RuntimeError('Storage geometry differs')
    parameters=elaboration.constant_parameters(tree,'npu_top',('p_fixed_ps_channels','SHARED_RAM_ENABLED','SHARED_MAX_IA_BANKS','IA_MAX_CACHE_BLOCKS','IA_REUSE_NUM_MAX'))
    if parameters['p_fixed_ps_channels']!=1 or parameters['SHARED_RAM_ENABLED']!=1:raise RuntimeError('FPGA layout parameter differs')
    if hashes!=elaboration.sources_sha256():raise RuntimeError('Source changed during FPGA elaboration')
    result={'passed':True,'configuration':values,'source_sha256':hashes,'command':command,
            'primitive_library_sha256':hashlib.sha256(library.read_bytes()).hexdigest(),
            'generated_primitive_models_sha256':hashlib.sha256(primitives.read_bytes()).hexdigest(),
            'clock_primitive_declaration_library_sha256':hashlib.sha256(clock_library.read_bytes()).hexdigest(),
            'clock_primitive_scope':'BUFGCE declaration for structural enumeration',
            'buffer_arrays_bits':state['buffer_arrays_bits'],'register_arrays_bits':state['register_arrays_bits'],
            'module_instances':counts,'shared_memory_declarations':memories,'parameters':parameters,
            'vector_pe_parameters':pe_parameters}
    (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n');tree_path.unlink()
    print(json.dumps({'passed':True,'shared_data_bits':state['buffer_arrays_bits']['ia_ps_shared_ram'],
                      'shared_memories':len(memories),'systolic_cells':counts['ws_systolic_cell'],
                      'registered_vector_pe':counts['registered_vector_pe']}))


if __name__=='__main__':main()
