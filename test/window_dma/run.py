#!/usr/bin/env python3
"""Verify ordered outstanding window requests through the production DMA."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "test"))
from rtl_reference import read_rtl_source
HERE=Path(__file__).resolve().parent

def command(args,log):
    with log.open('w') as stream:
        stream.write('$ '+' '.join(map(str,args))+'\n');stream.flush()
        result=subprocess.run(list(map(str,args)),cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(log.read_text()[-12000:])

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--verilator',default='verilator')
    parser.add_argument('--jobs',type=int,default=2)
    parser.add_argument('--reference-ref',help='Compare resident-stream cycles with this Git revision')
    parser.add_argument('--fpga', action='store_true', help='使用官方 FPGA 原语模型')
    parser.add_argument('--source-root', type=Path, default=ROOT, help='包含候选 RTL 的独立源码目录')
    parser.add_argument('--single-response-interval', type=int, default=1,
                        help='单拍窗口允许的最大返回间隔，用于显式选择流水配置')
    parser.add_argument('--descriptor-response-interval', type=int, default=3,
                        help='连续窗口之间允许的最大返回间隔')
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    if args.single_response_interval < 1:
        parser.error('--single-response-interval 必须为正整数')
    if args.descriptor_response_interval < 1:
        parser.error('--descriptor-response-interval 必须为正整数')
    conv=ROOT/'rtl/npu/conv'
    sources=[conv/'conv_im2col_pkg.sv',conv/'vector_engine_pkg.sv']
    sources += [p for p in sorted(conv.rglob('*.sv')) if p not in sources]
    sources += sorted((ROOT/'rtl/npu/dma').rglob('*.sv'))
    sources += [ROOT/'rtl/common/pseudo_dual_port_ram.v',HERE/'window_dma_top.sv',HERE/'main.cpp']
    sources = runpy.run_path(str(ROOT / "test/monitors/sources.py"))["with_observers"](sources)
    source_root = args.source_root.resolve()
    sources = [source_root / source.relative_to(ROOT)
               if source.is_relative_to(ROOT) and source.relative_to(ROOT).parts[0] == 'rtl' else source
               for source in sources]
    defines = []
    cppflags = '-std=c++20 -DWINDOW_SINGLE_RESPONSE_INTERVAL=' + str(args.single_response_interval)
    cppflags += ' -DWINDOW_DESCRIPTOR_RESPONSE_INTERVAL=' + str(args.descriptor_response_interval)
    if args.fpga:
        import pyosys
        library = Path(pyosys.__file__).parent / 'share/xilinx/cells_sim.v'
        content = library.read_text()
        names = ('LUT1', 'LUT6', 'LUT6_2', 'MUXF7', 'MUXF8', 'DSP48E1', 'FDRE', 'CARRY4')
        models = []
        for name in names:
            match = re.search(r'^module ' + name + r'\b.*?^endmodule', content, re.M | re.S)
            if match is None:
                raise RuntimeError('Missing FPGA model: ' + name)
            models.append(match[0])
        primitive_file = out / 'xilinx_primitives.sv'
        primitive_file.write_text('\n\n'.join(models) + '\n')
        simulation_sources = []
        simulation_text = runpy.run_path(str(ROOT / 'test/monitors/observer_text.py'))['simulation_text']
        for source in sources:
            if source.parent == ROOT / 'test/monitors':
                text = source.read_text()
                destination = out / 'observers' / source.name
                destination.parent.mkdir(exist_ok=True)
                destination.write_text(simulation_text(text))
                simulation_sources.append(destination)
            else:
                simulation_sources.append(source)
        sources = [*simulation_sources, primitive_file]
        defines = ['-DSYNTHESIS=1', '-DXILINX_FPGA=1', '-DNPU_SIM_ASSERT=1']
        cppflags += ' -DWINDOW_RESPONSE_INTERVAL=3 -fsanitize=undefined -fno-sanitize-recover=all'
    dependency_tools = runpy.run_path(str(ROOT / 'scripts/rtl/source_files.py'))
    def verify(name,source_files,folder,include_root):
        folder.mkdir(parents=True,exist_ok=True)
        inputs = dependency_tools['input_files'](source_files, include_root,
                                                 include_dirs=(include_root / 'include',))
        inputs += [Path(__file__).resolve(), ROOT / 'test/monitors/sources.py',
                   ROOT / 'test/monitors/observer_text.py', ROOT / 'scripts/rtl/source_files.py']
        hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
        command([args.verilator,'--cc','--exe','--timing','--assert','--top-module','window_dma_top',
                 '-Wno-fatal','-Wno-PINMISSING','--Mdir',folder/'obj','--output-groups','0',
                 '--output-split','12000','-CFLAGS',cppflags,
                 '-I'+str(include_root/'include'),
                 *(['-LDFLAGS', '-fsanitize=undefined'] if args.fpga else []),
                 *defines, ROOT/'test/conv_npu/simulator.vlt',*source_files],folder/'elaborate.log')
        command(['make','-C',folder/'obj','-f','Vwindow_dma_top.mk','-j',args.jobs,
                 'OPT_FAST=-O1','OPT_SLOW=-O0','OPT_GLOBAL=-O1','VK_PCH_I_FAST=',
                 'VK_PCH_I_SLOW=','CFG_CXXFLAGS_PCH=-E'],folder/'compile.log')
        assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==v for p,v in hashes.items())
        trace=folder/'resident_stream.csv'
        command([folder/'obj/Vwindow_dma_top',f'+WINDOW_TRACE={trace}'],folder/'run.log')
        text=(folder/'run.log').read_text();assert 'WINDOW_DMA_PASS' in text
        result={'passed':True,'name':name,'source_sha256':hashes,'fpga':args.fpga,
                'maximum_response_intervals':{'single_beat':args.single_response_interval,
                    'within_descriptor':3,'descriptor_boundary':args.descriptor_response_interval},
                'executable_sha256':hashlib.sha256((folder/'obj/Vwindow_dma_top').read_bytes()).hexdigest(),
                'resident_stream_sha256':hashlib.sha256(trace.read_bytes()).hexdigest(),
                'resident_stream_cycles':len(trace.read_text().splitlines()),
                'log':str(folder/'run.log'),
                'tests':[line for line in text.splitlines() if line.startswith(('CASE ','WINDOW_DMA_PASS'))]}
        (folder/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
        print(text,end='')
        return result,trace
    current,current_trace=verify('current',sources,out,source_root)
    if args.reference_ref:
        reference_sources=[]
        reference=out/'reference'
        for source in sources:
            relative = source.relative_to(source_root) if source.is_relative_to(source_root) else None
            if relative is not None and relative.parts[0] == 'rtl':
                revision_file=f'{args.reference_ref}:{relative}'
                try:
                    content=read_rtl_source(revision_file,cwd=ROOT)
                except subprocess.CalledProcessError:
                    if source.name=='regfile.v':
                        continue
                    raise
                target=reference/'sources'/relative;target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(content);reference_sources.append(target)
            else:
                reference_sources.append(source)
        for header in (source_root/'include').glob('*.svh'):
            target = reference/'sources/include'/header.name
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(read_rtl_source(f'{args.reference_ref}:include/{header.name}',cwd=ROOT))
        previous,previous_trace=verify(args.reference_ref,reference_sources,reference,reference/'sources')
        if current_trace.read_bytes()!=previous_trace.read_bytes():
            raise RuntimeError('Resident-stream cycle comparison differs')
        current.update(reference=previous,reference_ref=args.reference_ref,
                       resident_stream_cycle_equivalent=True)
        (out/'summary.json').write_text(json.dumps(current,indent=2)+'\n')
        print('WINDOW_DMA_CYCLE_COMPARE_PASS revision='+args.reference_ref)

if __name__=='__main__':main()
