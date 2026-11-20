#!/usr/bin/env python3
"""记录偏置驻留检查的生产参数综合资源和寄存器间连接。"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source
ROOT=Path(__file__).resolve().parents[2]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--reference-ref')
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    name='rtl/npu/loaders/bias_loader_buffer.sv'
    data=read_rtl_source(args.reference_ref+':'+name, cwd=ROOT) if args.reference_ref else (ROOT/name).read_bytes()
    source=out/'source.sv';source.write_bytes(data)
    sources=[source,ROOT/'rtl/common/regfile.v',ROOT/'rtl/common/parallel_prefix_add.sv']
    top='bias_loader_buffer';pre=out/'pre_lut.il';mapped=out/'mapped.json';script=out/'run.ys'
    script.write_text(f'read_slang --top {top} -GSIZE=16 -GBUS_WIDTH=64 -GCOUNT_WIDTH=28 -GGROUP_BLOCKS_MAX=32 '+
                     ' '.join(shlex.quote(str(p)) for p in sources)+'\n'+
                     f'synth_xilinx -top {top} -family xc7 -noiopad -noclkbuf -flatten -run begin:map_luts\n'+
                     f'write_rtlil {shlex.quote(str(pre))}\n'+
                     f'synth_xilinx -top {top} -family xc7 -noiopad -noclkbuf -flatten -run map_luts:\n'+
                     f'check -assert\nstat -tech xilinx\nwrite_json {shlex.quote(str(mapped))}\n')
    with (out/'synthesis.log').open('w') as log:
        subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],
                       stdout=log,stderr=subprocess.STDOUT,cwd=ROOT,check=True)
    sys.path.insert(0,str(ROOT/'scripts/fpga'));import netlist_metrics
    design=json.loads(mapped.read_text())['modules'][top]
    for name_,origin in netlist_metrics.register_origins(pre).items():
        if name_ in design['cells']:design['cells'][name_].setdefault('attributes',{})['fpga_register_origin']=origin
    report=netlist_metrics.analyze(design)
    report.update(reference_ref=args.reference_ref,source_sha256={name:hashlib.sha256(data).hexdigest(),
                  **{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources[1:]}},
                  configuration={'SIZE':16,'BUS_WIDTH':64,'COUNT_WIDTH':28,'GROUP_BLOCKS_MAX':32})
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({**report['resources'],'longest_register_path_cells':report['paths']['longest_register_path_cells']}),flush=True)


if __name__=='__main__':main()
