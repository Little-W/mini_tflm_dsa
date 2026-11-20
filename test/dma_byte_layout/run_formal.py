#!/usr/bin/env python3
"""比较线性 DMA 的全部状态与公开输出。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
SOURCE='rtl/npu/dma/axi_linear_block_dma.sv'


def observe_context_storage(source):
    entry = ('{u_context_storage.mem[context_index], rd_context_tag_q[context_index]}'
             if 'u_context_storage (' in source else 'rd_context[context_index]')
    observation = '''
    (* keep *) wire [RD_CTX_DEPTH*$bits(read_context_t)-1:0] context_state;
    for (genvar context_index = 0; context_index < RD_CTX_DEPTH; context_index++) begin : g_context_state
        assign context_state[context_index*$bits(read_context_t) +: $bits(read_context_t)] = CONTEXT_ENTRY;
    end
'''.replace('CONTEXT_ENTRY', entry)
    if 'read_context_t' not in source or '\nendmodule' not in source:
        raise RuntimeError('Descriptor storage declaration is missing')
    return source.replace('\nendmodule', observation + '\nendmodule')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--reference-ref',default='e19e4f4')
    parser.add_argument('--address-parameters', action='store_true',
                        help='Include narrow addresses and shorter physical burst limits')
    parser.add_argument('--context-parameters', action='store_true',
                        help='Include a non-power-of-two descriptor count')
    parser.add_argument('--production-parameters', action='store_true',
                        help='Include the complete SoC DMA size and cache-slot count')
    parser.add_argument('--observe-context-storage', action='store_true',
                        help='Expose matching complete descriptor words in verification copies')
    parser.add_argument('--fpga', action='store_true')
    parser.add_argument('--asic', action='store_true', help='Verify the generic RTL implementation')
    args=parser.parse_args()
    if args.fpga and args.asic:
        parser.error('--fpga and --asic select separate hardware implementations')
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    original=subprocess.check_output(['git','show',args.reference_ref+':'+SOURCE],cwd=ROOT,text=True)
    current=ROOT/SOURCE
    reference=out/'reference.sv'
    candidate=out/'current.sv'
    reference.write_text(observe_context_storage(original) if args.observe_context_storage else original)
    candidate.write_text(observe_context_storage(current.read_text())
                         if args.observe_context_storage else current.read_text())
    structure_compare = args.observe_context_storage and (
        ('u_context_storage (' in original) != ('u_context_storage (' in current.read_text()))
    common=ROOT/'rtl/common/REGFILE.v'
    common_snapshot=out/'REGFILE.v';common_snapshot.write_bytes(common.read_bytes())
    comparator=ROOT/'rtl/common/add_equal.sv'
    comparator_snapshot=out/'add_equal.sv';comparator_snapshot.write_bytes(comparator.read_bytes())
    dependencies=(current,common,comparator)
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in dependencies}
    summary={'passed':False,'reference_ref':args.reference_ref,'source_sha256':hashes,
             'inputs_constrained':False,
             'original_reference_sha256':hashlib.sha256(original.encode()).hexdigest(),'runs':[]}
    primitive_options = ' -D ASIC_SYNTHESIS=1' if args.asic else ''
    if args.fpga:
        import pyosys
        library = Path(pyosys.__file__).parent / 'share/xilinx/cells_sim.v'
        model = out/'lut6_2.sv'
        model.write_text(re.search(r'^module LUT6_2\b.*?^endmodule', library.read_text(), re.M | re.S).group(0)+'\n')
        primitive_options = ' -D SYNTHESIS '+shlex.quote(str(model))
        summary['primitive_library_sha256'] = hashlib.sha256(library.read_bytes()).hexdigest()
    summary['fpga'] = args.fpga
    summary['asic'] = args.asic
    if args.observe_context_storage:
        summary['state_observation'] = {
            'scope': 'Every complete descriptor word, reconstructed from actual payload and tag storage',
            'state_updates_modified': False, 'input_assumptions_added': False,
            'forward_structure_comparison': structure_compare,
            'reference_prepared_sha256': hashlib.sha256(reference.read_bytes()).hexdigest(),
            'current_prepared_sha256': hashlib.sha256(candidate.read_bytes()).hexdigest(),
        }
    profiles = [(size, bus, data_width, contexts, 32, 256 * (bus // 8))
                for size,bus,data_width,contexts in
                ((4,32,8,1),(16,32,16,4),(16,64,16,4),(16,128,16,4),(16,64,32,2))]
    if args.address_parameters:
        profiles.extend([(16,1024,16,1,16,32768), (16,1024,16,4,17,32768),
                         (16,64,16,4,32,8), (16,64,16,4,32,256)])
    if args.context_parameters:
        profiles.append((16,64,16,3,32,2048))
    profiles = [(*profile, 4) for profile in profiles]
    if args.production_parameters:
        profiles.append((64,64,16,4,32,2048,64))
    for size,bus,data_width,contexts,reg_width,dma_max_bytes,cache_blocks in profiles:
        folder=out/f's{size}_b{bus}_d{data_width}_c{contexts}_a{reg_width}_m{dma_max_bytes}_k{cache_blocks}'
        folder.mkdir(exist_ok=True)
        options=(f'-GSIZE={size} -GBUS_WIDTH={bus} -GDATA_WIDTH={data_width} '
                 f'-GRD_CONTEXT_DEPTH={contexts} -GREG_WIDTH={reg_width} -GDMA_MAX_BYTES={dma_max_bytes} '
                 f'-GCACHE_BLOCKS={cache_blocks}')
        commands=[]
        for name,source in (('reference',reference),('current',candidate)):
            commands.extend([f'read_slang --top axi_linear_block_dma {options} {shlex.quote(str(source))} {shlex.quote(str(common_snapshot))} {shlex.quote(str(comparator_snapshot))}{primitive_options}',
                             'prep -top axi_linear_block_dma -flatten','memory_map','async2sync',
                             'opt -full' if args.observe_context_storage else 'opt_clean',
                             f'rename axi_linear_block_dma {name}',f'design -stash {name}'])
        commands.extend(['design -copy-from reference -as reference reference','design -copy-from current -as current current',
                         'equiv_make reference current equivalent','hierarchy -top equivalent'])
        if structure_compare:
            commands.append('equiv_struct -fwd -icells')
        commands.extend(['equiv_simple -seq 1',
                         'opt_clean','equiv_induct -seq 2','equiv_status -assert'])
        script=folder/'run.ys';script.write_text('\n'.join(commands)+'\n');log=folder/'formal.log'
        with log.open('w') as stream:
            result=subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],
                                  stdout=stream,stderr=subprocess.STDOUT,cwd=ROOT)
        text=log.read_text();match=re.search(r'Of those cells (\d+) are proven and (\d+) are unproven',text)
        report={'SIZE':size,'BUS_WIDTH':bus,'DATA_WIDTH':data_width,'RD_CONTEXT_DEPTH':contexts,
                'REG_WIDTH':reg_width,'DMA_MAX_BYTES':dma_max_bytes,
                'CACHE_BLOCKS':cache_blocks,
                'passed':result.returncode==0 and 'Equivalence successfully proven' in text,
                'equivalent_bits':int(match[1]) if match else None,'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()}
        summary['runs'].append(report);print(json.dumps(report),flush=True)
        if not report['passed']:raise RuntimeError(text[-9000:])
    if hashes!={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in dependencies}:
        raise RuntimeError('Source changed during verification')
    summary['passed']=True
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')


if __name__=='__main__':main()
