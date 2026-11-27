#!/usr/bin/env python3
"""按实际 SoC 参数映射完整缓存或前端，比较替换发送路径与资源数量。"""
from pathlib import Path
import argparse
import json
import runpy
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def run(command):
    subprocess.run(list(map(str, command)), cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='3b1c0c5b664d28397dcb257ad8b9cbadea730b6b')
    parser.add_argument('--labels', nargs='+', choices=('reference','current'),
                        default=('reference','current'))
    parser.add_argument('--frontend', action='store_true')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    controller = ROOT / 'rtl/npu/dma/cache/conv_windowed_cache.sv'
    reference = out / 'reference_controller.sv'
    reference.write_bytes(subprocess.check_output(['git','show',args.reference+':'+
        str(controller.relative_to(ROOT))],cwd=ROOT))
    resolve = runpy.run_path(str(ROOT / 'scripts/rtl/source_files.py'))['with_dependencies']
    if args.frontend:
        top = 'conv_im2col_frontend'
        initial = [ROOT / 'rtl/npu/conv/conv_im2col_pkg.sv', ROOT / 'rtl/npu/conv/conv_im2col_frontend.sv']
        parameters = dict(SIZE=16,LANES=8,BUS_WIDTH=64,SLOT_W=6,CACHE_SETS=16,CACHE_WAYS=2,
            LINE_BYTES=128,CACHE_POLICY=3,REGISTER_DESCRIPTOR=1,REGISTER_ROW_ADDRESS=1,
            REGISTER_CACHE_REQUEST=1,CACHE_RESPONSE_DEPTH=2,DMA_MAX_BYTES=2048)
    else:
        top = 'conv_windowed_cache'
        initial = [controller]
        parameters = dict(SETS=16,WAYS=2,LINE_BYTES=128,BUS_WIDTH=64,READ_WIDTH=64,
                          CACHE_POLICY=3,DEMAND_DEPTH=2,p_preview_request=1)
    sources = resolve(initial, ROOT)
    options = ['-D','SYNTHESIS=1','-D','XILINX_FPGA=1','-I'+str(ROOT/'include')]
    options += [f'-G{name}={value}' for name,value in parameters.items()]
    cases = {label:dict(top=top,parameters=parameters,options=options,
        configuration='实际 SoC 参数，保留全部端口和寄存状态',
        sources=[str(reference if label=='reference' and path==controller else path) for path in sources])
        for label in args.labels}
    config = out / 'cases.json';config.write_text(json.dumps(cases,ensure_ascii=False,indent=2)+'\n')
    resume = ['--resume'] if args.resume else []
    for label in args.labels:
        run([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--case-config',config,
             '--cases',label,'--out',out,'--through','pre_lut',*resume])
        run([sys.executable,ROOT/'scripts/fpga/remap_fpga_luts.py','--source',out/label,
             '--out',out/(label+'_mapped'),'--mode','physical-cost','--delay-target-ps','6667',
             '--wire-delay-ps','300','--max-lut-inputs','8','--discard-abc9-temporaries',*resume])
        run([sys.executable,ROOT/'test/cache_select_launch/paths.py','--source',out/label,
             '--mapped',out/(label+'_mapped'),'--out',out/(label+'_paths')])


if __name__ == '__main__':
    main()
