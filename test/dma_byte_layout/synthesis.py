#!/usr/bin/env python3
"""记录 DMA 字节排列的生产参数综合资源和寄存器间连接。"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[2]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--reference-ref')
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    name='rtl/npu/dma/axi_linear_block_dma.sv'
    data=subprocess.check_output(['git','show',args.reference_ref+':'+name],cwd=ROOT) if args.reference_ref else (ROOT/name).read_bytes()
    source=out/'source.sv';source.write_bytes(data)
    common=ROOT/'rtl/common/REGFILE.v'
    comparator=ROOT/'rtl/common/add_equal.sv'
    sources=[source,common,comparator]
    top='axi_linear_block_dma';pre=out/'pre_lut.il';mapped=out/'mapped.json';script=out/'run.ys'
    script.write_text(f'read_slang --top {top} -GSIZE=16 -GBUS_WIDTH=64 -GDATA_WIDTH=16 -GRD_CONTEXT_DEPTH=4 '+
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
                  'rtl/common/REGFILE.v':hashlib.sha256(common.read_bytes()).hexdigest(),
                  'rtl/common/add_equal.sv':hashlib.sha256(comparator.read_bytes()).hexdigest()},
                  configuration={'SIZE':16,'BUS_WIDTH':64,'DATA_WIDTH':16,'RD_CONTEXT_DEPTH':4})
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({**report['resources'],'longest_register_path_cells':report['paths']['longest_register_path_cells']}),flush=True)


if __name__=='__main__':main()
