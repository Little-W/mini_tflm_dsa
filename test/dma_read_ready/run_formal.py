#!/usr/bin/env python3
"""证明生产模式控制及实际读取保护和请求复用的完整状态、输出关系。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
SOURCES=('rtl/npu/dma/axi_dual_block_dma.sv','rtl/npu/conv/conv_axi_read_guard.sv',
         'rtl/npu/conv/conv_axi_read_mux.sv')


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference',default='414099fa')
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    inputs=out/'inputs'
    subprocess.run([sys.executable,str(HERE/'prepare_measurement.py'),'--reference',args.reference,
                    '--out',str(inputs)],cwd=ROOT,check=True)
    hashes={name:digest(ROOT/name) for name in SOURCES}
    assert (inputs/'reference/conv_axi_read_mux.sv').read_bytes()==(inputs/'current/conv_axi_read_mux.sv').read_bytes()
    originals={label:(inputs/label/'axi_dual_block_dma.sv').read_text() for label in ('reference','current')}
    normalized=originals['current'].replace('job_read_guard','job_range')
    normalized=normalized.replace('job_range <= (conv_enable && CONV_SUPPORTED) || dma_range_enable;',
                                  'job_range <= dma_range_enable;')
    normalized=normalized.replace('.enable(job_range)', '.enable(job_conv || job_range)')
    def code(text):return re.sub(r'\s+','',re.sub(r'//[^\n]*','',text))
    assert code(normalized)==code(originals['reference'])

    report={'passed':False,'reference':args.reference,'source_sha256':hashes,
            'inputs_constrained':False,'mode_control':[],'connected_pair':[]}
    mode_sources={}
    for label,source in originals.items():
        begin=source.index('    always_ff @(posedge clk or negedge rst_n) begin')
        control=source[begin:source.index('    // The old engine',begin)]
        name=re.search(r'logic job_conv, (job_\w+);',source).group(1)
        states=sorted(set(re.findall(r'\b(\w+)\s*<=',control))-{name})
        if label=='reference':expected_states=states
        else:assert states==expected_states
        guard='job_conv || job_range' if name=='job_range' else name
        wrapper=(HERE/'mode_control.sv.inc').read_text().replace('@@MODE_NAME@@',name)
        wrapper=wrapper.replace('@@CONTROL@@',control).replace('@@STATE@@',','.join(states)).replace('@@GUARD@@',guard)
        path=out/(label+'_mode.sv');path.write_text(wrapper);mode_sources[label]=path
    report['compared_mode_state_fields']=len(expected_states)

    import pyosys
    library=Path(pyosys.__file__).parent/'share/xilinx/cells_sim.v'
    model=out/'lut6_2.sv'
    text=re.search(r'^module LUT6_2\b.*?^endmodule',library.read_text(),re.M|re.S)[0]
    model.write_text(re.sub(r'\bspecify\b.*?\bendspecify\b','',text,flags=re.S)+'\n')
    report['primitive_library_sha256']=digest(library)

    def compare(name,top,sources,options):
        commands=[]
        for label,paths in sources.items():
            commands += [f'read_slang --top {top} {options} '+
                         ' '.join(shlex.quote(str(p)) for p in paths),
                         f'prep -top {top} -flatten','memory_map','async2sync','opt_clean',
                         'rename -hide w:*.s1 w:*.s2 w:*.s3 w:*.s4 w:*.s5 w:*.s5_0 w:*.s5_1',
                         f'rename {top} {label}',f'design -stash {label}']
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from current -as current current',
                     'equiv_make reference current equivalent','hierarchy -top equivalent',
                     'opt_merge','equiv_simple -short -seq 1','opt_clean',
                     'equiv_induct -seq 2','equiv_status -assert']
        script,log=out/(name+'.ys'),out/(name+'.log')
        script.write_text('\n'.join(commands)+'\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],
                cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=180)
        text=log.read_text();assert 'Equivalence successfully proven' in text
        match=re.search(r'Of those cells (\d+) are proven and (\d+) are unproven',text)
        assert match and int(match[2])==0
        return {'passed':True,'equivalent_bits':int(match[1]),'log_sha256':digest(log)}

    for supported in (0,1):
        row=compare('mode_'+str(supported),'read_mode_control',
            {label:[p] for label,p in mode_sources.items()},f'-GCONV_SUPPORTED={supported}')
        row['conv_supported']=supported;report['mode_control'].append(row);print(json.dumps(row),flush=True)
    for label in ('reference','current'):
        path=inputs/label/'read_pair.sv'
        text=path.read_text()
        expression='job_conv || job_range' if label=='reference' else 'job_read_guard'
        text=text.replace('endmodule',f'    (* keep *) wire formal_read_mode={expression};\nendmodule')
        (out/(label+'_pair.sv')).write_text(text)
    for bus in (32,64):
        sources={label:[out/(label+'_pair.sv'),inputs/label/'conv_axi_read_guard.sv',
                   inputs/label/'conv_axi_read_mux.sv',model] for label in ('reference','current')}
        row=compare('pair_'+str(bus),'read_ready_top',sources,
                    f'-D SYNTHESIS=1 -D XILINX_FPGA=1 -GBUS_WIDTH={bus}')
        row['bus_width']=bus;report['connected_pair'].append(row);print(json.dumps(row),flush=True)
    assert hashes=={name:digest(ROOT/name) for name in SOURCES}
    report['passed']=True
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':main()
