#!/usr/bin/env python3
"""检查固定通道的综合存储容量，以及 IA 和部分和地址的完整覆盖。"""
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
    args=parser.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    sources=[ROOT/'rtl/npu/buffers/ia_ps_shared_ram.sv',ROOT/'rtl/common/regfile.v']
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    summary={'passed':False,'source_sha256':hashes,'profiles':[]}
    for size in (2048,4096,8192):
        for banks in (6,7,8,9):
            folder=out/f'b{size}_n{banks}';folder.mkdir(exist_ok=True)
            script=folder/'run.ys';netlist=folder/'storage.json'
            script.write_text(f'read_slang --top ia_ps_channel_ram -Gp_bank_bytes={size} -Gp_total_bytes={size*banks} '+
                ' '.join(shlex.quote(str(p)) for p in sources)+'\n'
                'opt\nmemory_dff\nmemory_share\nopt_clean\nmemory_collect\nopt_clean\ncheck -assert\n'
                f'write_json {shlex.quote(str(netlist))}\n')
            with (folder/'structure.log').open('w') as log:
                subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],
                               stdout=log,stderr=subprocess.STDOUT,check=True,cwd=ROOT)
            design=json.loads(netlist.read_text())['modules']['ia_ps_channel_ram'];memories=[]
            for name,cell in design['cells'].items():
                if 'latch' in cell['type'].lower():raise RuntimeError('Latch found')
                if cell['type']=='$mem_v2':
                    entry={'name':name}
                    for key in ('WIDTH','SIZE','RD_PORTS','WR_PORTS','RD_CLK_ENABLE','WR_CLK_ENABLE'):
                        entry[key.lower()]=int(cell['parameters'][key],2)
                    if (entry['width'],entry['rd_ports'],entry['wr_ports'],entry['rd_clk_enable'],entry['wr_clk_enable'])!=(128,1,1,1,1):
                        raise RuntimeError('Memory width or synchronous ports differ')
                    if 'ram_style' in cell['attributes']:raise RuntimeError('Memory type was forced')
                    memories.append(entry)
            total_bits=sum(m['width']*m['size'] for m in memories)
            if total_bits!=size*banks*8:raise RuntimeError('Storage size differs')
            rows=size//16;chunk=rows//4;maximum_ia=4 if banks>=8 else 2
            expected_sizes=[rows]+[chunk]*(4*(maximum_ia-1))+[(banks-maximum_ia)*chunk]*4
            if sorted(m['size'] for m in memories)!=sorted(expected_sizes):raise RuntimeError('Memory geometry differs')
            allocations=[]
            for allocation in (1,2,4):
                if allocation>maximum_ia:continue
                positions={}
                for address in range(allocation*rows):
                    physical=(address%allocation)*rows+address//allocation
                    if physical in positions:raise RuntimeError('IA alias')
                    positions[physical]=('ia',address)
                for channel in range(4):
                    for address in range((banks-allocation)*chunk):
                        physical=(allocation+address//chunk)*rows+channel*chunk+address%chunk
                        if physical in positions:raise RuntimeError('PS alias or overlap')
                        positions[physical]=('ps',channel,address)
                if set(positions)!=set(range(banks*rows)):raise RuntimeError('Address coverage differs')
                allocations.append({'ia_banks':allocation,'ia_words':allocation*rows,
                                    'ps_rows_per_channel':(banks-allocation)*chunk,'physical_words_checked':len(positions)})
            report={'passed':True,'bank_bytes':size,'banks':banks,'storage_bits':total_bits,'memories':memories,'allocations':allocations}
            summary['profiles'].append(report)
            print(json.dumps({'passed':True,'bank_bytes':size,'banks':banks,'storage_bits':total_bits}),flush=True)
    if hashes!={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}:
        raise RuntimeError('Source changed during storage analysis')
    summary['passed']=True
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')


if __name__=='__main__':
    main()
