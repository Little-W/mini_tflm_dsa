#!/usr/bin/env python3
"""测量两种部分和存储布局的资源，并记录完整存储位数。"""
import argparse
import collections
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_current_source as read_rtl_text

ROOT=Path(__file__).resolve().parents[2]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--kind',choices=('memory','store'),default='memory')
    parser.add_argument('--layout',choices=('rotating','fixed'),required=True)
    parser.add_argument('--bank-bytes',type=int,default=8192)
    parser.add_argument('--banks',type=int,default=7)
    args=parser.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    sys.path.insert(0,str(ROOT/'scripts/fpga'))
    import open_fpga_synth
    import netlist_metrics
    import pyosys
    size=args.bank_bytes;banks=args.banks
    sources=[ROOT/'rtl/common/regfile.v']
    if args.kind=='memory':
        sources.append(ROOT/'rtl/npu/buffers/ia_ps_shared_ram.sv')
        top='ia_ps_channel_ram' if args.layout=='fixed' else 'ia_ps_shared_ram'
        options=(f'-Gp_bank_bytes={size} -Gp_total_bytes={size*banks}' if args.layout=='fixed'
                 else f'-GBANK_BYTES={size} -GTOTAL_BYTES={size*banks}')
    else:
        sources.append(ROOT/'rtl/npu/ps_compact/ps_frame_store.sv')
        top='ps_frame_store'
        options=(f'-GEXTERNAL_RAM=1 -Gp_fixed_ps_channels={int(args.layout=="fixed")} '
                 f'-GPOOL_BYTES={size*(banks-1)} -GBANK_BYTES={size} -GMAX_FRAME_ROWS={size//16} '
                 f'-GRAM_ADDR_BITS={(banks*(size//16)-1).bit_length()}')
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    primitive_options,manifest=open_fpga_synth.primitive_models(out,list(map(str,sources)),Path(pyosys.__file__).parent/'share/xilinx')
    pre=out/'pre_lut.il';mapped=out/'mapped.json';structure=out/'storage.json';script=out/'run.ys'
    script.write_text(f'read_slang --top {top} -D SYNTHESIS -D XILINX_FPGA {options} {primitive_options} '+
        ' '.join(shlex.quote(str(p)) for p in sources)+'\n'
        'read_verilog -lib -specify -overwrite +/xilinx/cells_sim.v\n'
        f'hierarchy -check -top {top}\n'
        f'synth_xilinx -top {top} -family xc7 -noiopad -noclkbuf -flatten -run begin:map_memory\n'
        f'select {top}\nwrite_json -selected {shlex.quote(str(structure))}\nselect *\n'
        f'synth_xilinx -top {top} -family xc7 -noiopad -noclkbuf -flatten -run map_memory:map_luts\n'
        f'write_rtlil {shlex.quote(str(pre))}\n'
        f'synth_xilinx -top {top} -family xc7 -noiopad -noclkbuf -flatten -run map_luts:\n'
        f'check -assert\nstat -tech xilinx\nwrite_json {shlex.quote(str(mapped))}\n')
    with (out/'synthesis.log').open('w') as log:
        subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],cwd=ROOT,
                       stdout=log,stderr=subprocess.STDOUT,check=True)
    design=json.loads(read_rtl_text(mapped))['modules'][top]
    for name,origin in netlist_metrics.register_origins(pre).items():
        if name in design['cells']:design['cells'][name].setdefault('attributes',{})['fpga_register_origin']=origin
    metrics=netlist_metrics.analyze(design)
    storage=[]
    for name,cell in json.loads(read_rtl_text(structure))['modules'][top]['cells'].items():
        if cell['type']=='$mem_v2':
            params=cell['parameters'];entry={'name':name}
            for key in ('WIDTH','SIZE','RD_PORTS','WR_PORTS','RD_CLK_ENABLE','WR_CLK_ENABLE'):
                entry[key.lower()]=int(params[key],2)
            storage.append(entry)
    total_bits=sum(m['width']*m['size'] for m in storage)
    if args.kind=='memory' and total_bits!=size*banks*8:raise RuntimeError('Storage size differs')
    if any(m['rd_ports']!=1 or m['wr_ports']!=1 or m['rd_clk_enable']!=1 or m['wr_clk_enable']!=1 for m in storage):
        raise RuntimeError('Memory port shape differs')
    if hashes!={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}:
        raise RuntimeError('Source changed during synthesis')
    result={'kind':args.kind,'layout':args.layout,'bank_bytes':size,'banks':banks,'source_sha256':hashes,
            'primitive_models':manifest,'storage_bits':total_bits,'memories':storage,**metrics}
    (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'kind':args.kind,'layout':args.layout,'storage_bits':total_bits,**metrics['resources'],
                      'longest_register_path_cells':metrics['paths']['longest_register_path_cells']}),flush=True)


if __name__=='__main__':
    main()
