#!/usr/bin/env python3
"""证明实际错误至配置接收连接，并比较完整仲裁器和权重加载器。"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

from extract import (ROOT, REFERENCE, SOURCES, TOP, ARB, KERNEL, digest, source_at,
                     load, connected, verify_extensions, r22)


def run(out, name, commands, expected):
    script, log = out/(name+'.ys'), out/(name+'.log')
    script.write_text('\n'.join(commands)+'\n')
    with log.open('w') as stream:
        subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),
            '--worker',str(script)],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,
            check=True,timeout=300)
    content=log.read_text()
    if expected not in content:
        raise RuntimeError('Formal result is incomplete: '+str(log))
    return {'passed':True,'script_sha256':digest(script),'log_sha256':digest(log)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--reference',default=REFERENCE)
    parser.add_argument('--connected-only',action='store_true')
    args=parser.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    old={p:source_at(p,args.reference) for p in SOURCES}
    current={p:source_at(p) for p in SOURCES}
    hashes={str(p):digest(ROOT/p) for p in SOURCES}
    import pyosys
    library=Path(pyosys.__file__).parent/'share/xilinx/cells_sim.v'
    model=out/'lut_models.v'
    model.write_text('\n\n'.join(re.sub(r'\bspecify\b.*?\bendspecify\b','',
        re.search(r'^module '+name+r'\b.*?^endmodule',library.read_text(),re.M|re.S)[0],flags=re.S)
        for name in ('LUT1','LUT2','LUT3','LUT4','LUT5','LUT6','LUT6_2','MUXF7','MUXF8','DSP48E1'))+'\n')
    report={'passed':False,'reference_commit':args.reference,'source_sha256':hashes,
        'inputs_constrained':False,'state_constraints':False,
        'test_source_sha256':{str(p.relative_to(ROOT)):digest(p) for p in (Path(__file__),
            Path(__file__).with_name('extract.py'),ROOT/'test/npu_admission/run_formal.py',
            ROOT/'test/npu_fault_fanin/extract_fault.py',ROOT/'test/npu_admission_r22/extract.py',
            ROOT/'test/dma_return_admission/run_arbiter_formal.py',ROOT/'test/kernel_request_idle/run_formal.py')},
        'extension_check':verify_extensions(old,current),
        'primitive_library_sha256':digest(library),'primitive_models_sha256':digest(model),
        'connected':[]}
    for label,data in (('reference',old),('current',current)):
        (out/(label+'.sv')).write_text(connected(data))
    for fpga in (0,1):
        for quant in (0,1):
            for gating in (0,1):
                name=f'connected_fpga{fpga}_quant{quant}_gating{gating}'
                commands=[]
                for label in ('reference','current'):
                    mode='-DSYNTHESIS=1 -DXILINX_FPGA=1' if fpga else '-DASIC_SYNTHESIS=1'
                    commands += [f'read_slang {mode} --top admission_connected '
                        f'-GENABLE_QUANT_CLIENT={quant} -GENABLE_CLOCK_GATING={gating} '
                        f'{out/(label+".sv")} {model}',
                        'prep -top admission_connected -flatten','check -assert',
                        f'rename admission_connected {label}',f'design -stash {label}']
                commands += ['design -copy-from reference -as reference reference',
                    'design -copy-from current -as current current',
                    'miter -equiv -flatten reference current miter','hierarchy -top miter',
                    'sat -verify -prove trigger 0 -show-inputs -show-outputs']
                row=run(out,name,commands,'SAT proof finished - no model found: SUCCESS!')
                report['connected'].append({'fpga':bool(fpga),'quant':quant,'clock_gating':gating,**row})
                print(name,'PASS',flush=True)
    if not args.connected_only:
        arbiter=load('complete_arbiter_proof','test/dma_return_admission/run_arbiter_formal.py')
        original=arbiter.expand_dma_ports
        observed=[]
        def expand(path,output):
            ports=original(path,output)
            data=json.loads(output.read_text())
            top=data['modules'][arbiter.TOP]
            top['ports'].pop('o_kernel_eligible',None)
            top['netnames'].pop('o_kernel_eligible',None)
            output.write_text(json.dumps(data)+'\n')
            observed.append({'file':output.name,**r22.retain_public_and_state(output,arbiter.TOP)})
            return ports
        arbiter.expand_dma_ports=expand
        saved=sys.argv
        try:
            sys.argv=['run_arbiter_formal.py','--out',str(out/'arbiter'),'--reference-rev',args.reference]
            arbiter.main()
        finally:sys.argv=saved
        report['arbiter']=json.loads((out/'arbiter/summary.json').read_text())
        report['arbiter']['state_observation']=observed
        kernel=load('complete_kernel_proof','test/kernel_request_idle/run_formal.py')
        folder=out/'kernel';folder.mkdir(exist_ok=True)
        kernel_report={'passed':False,'reference':args.reference,'source_sha256':{},
            'inputs_constrained':False,'state_constraints':False,'runs':[]}
        for path in (KERNEL,*kernel.DEPENDENCIES):
            kernel_report['source_sha256'][str(path)]=digest(ROOT/path)
            if path != KERNEL:
                assert source_at(path,args.reference)==source_at(path)
        snapshots={}
        for label,data in (('reference',old),('current',current)):
            snapshots[label]=folder/(label+'.sv');snapshots[label].write_text(data[KERNEL])
        for size,count,bus,fpga in ((4,8,32,False),(16,32,64,False),
                                     (16,29,32,True),(16,29,64,True)):
            name=f'loader_s{size}_c{count}_b{bus}_f{int(fpga)}'
            observation={}
            for label in ('reference','current'):
                mode='-DSYNTHESIS=1 -DXILINX_FPGA=1' if fpga else '-DASIC_SYNTHESIS=1'
                inputs=' '.join(str(p) for p in (snapshots[label],*(ROOT/p for p in kernel.DEPENDENCIES),model))
                net=folder/(name+'_'+label+'.json')
                run(folder,name+'_'+label,[f'read_slang {mode} --top kernel_loader '
                    f'-GSIZE={size} -GCOUNT_WIDTH={count} -GBUS_WIDTH={bus} -GDATA_WIDTH=16 '+inputs,
                    'prep -top kernel_loader -flatten','memory_map','opt_clean',
                    'delete -output kernel_loader/o_prefetch_quiescent',f'write_json {net}'],
                    'Executing JSON backend.')
                observation[label]=r22.retain_public_and_state(net,'kernel_loader')
            assert observation['reference']==observation['current']
            commands=[]
            for label in ('reference','current'):
                commands += [f'read_json {folder/(name+"_"+label+".json")}',
                    'prep -top kernel_loader','async2sync',f'rename kernel_loader {label}',f'design -stash {label}']
            commands += ['design -copy-from reference -as reference reference',
                'design -copy-from current -as current current','equiv_make reference current equivalent',
                'hierarchy -top equivalent','opt_merge','equiv_simple -short -seq 1','opt_clean',
                'equiv_induct -seq 2','equiv_status -assert']
            proof=run(folder,name,commands,'Equivalence successfully proven')
            content=(folder/(name+'.log')).read_text()
            equivalent=int(re.search(r'Of those cells (\d+) are proven and 0 are unproven',content)[1])
            row={'size':size,'count_width':count,'bus_width':bus,'fpga':fpga,
                'equivalent_bits':equivalent,**observation['current'],**proof}
            kernel_report['runs'].append(row)
            print(name,'PASS',equivalent,flush=True)
        kernel_report['passed']=True
        (folder/'summary.json').write_text(json.dumps(kernel_report,ensure_ascii=False,indent=2)+'\n')
        report['kernel']=kernel_report
    assert hashes=={str(p):digest(ROOT/p) for p in SOURCES}
    report['passed']=True
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(out/'summary.json',flush=True)


if __name__=='__main__':main()
