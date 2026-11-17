#!/usr/bin/env python3
"""Check shared SRAM macro capacity through the production ASIC wrapper.

RAMTP interfaces are black boxes. This verifies dimensions and connectivity;
foundry timing, power, physical placement and signoff are outside this check.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[2]

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--yosys',default='yosys')
    parser.add_argument('--bank-bytes',type=int,nargs='+',choices=(2048,4096,8192),default=[2048,4096,8192])
    parser.add_argument('--bank-count',type=int,nargs='+',choices=range(6,10),default=[6,7,8,9])
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    sources=[ROOT/'rtl/npu/buffers/ia_ps_shared_ram.sv',ROOT/'asic/rtl/smic40_sram_1r1w.sv',
             ROOT/'test/shared_ia_ps/asic_macro_blackboxes.sv',Path(__file__).resolve()]
    before={str(p.relative_to(ROOT)):sha(p) for p in sources}
    widths={'QA':16,'CLKA':1,'CENA':1,'AA':7,'CLKB':1,'CENB':1,'WENB':16,
            'AB':7,'DB':16,'EMAA':3,'EMAB':3,'RET1N':1,'COLLDISN':1}
    profiles=[]
    for bank_bytes in args.bank_bytes:
        for banks in args.bank_count:
            name=f'bank_{bank_bytes}_count_{banks}'
            netlist=out/(name+'.json');script=out/(name+'.ys')
            read=(f'read_slang --top ia_ps_shared_ram -D SYNTHESIS -D ASIC_SRAM '
                  f'-GBANK_BYTES={bank_bytes} -GTOTAL_BYTES={bank_bytes*banks} '
                  '--blackboxed-module RAMTP128X16 --blackboxed-module RAMTP1024X16 '
                  + ' '.join(str(p) for p in sources[:3]))
            script.write_text(read+'\nopt\nmemory_collect\ncheck -assert\nstat\nwrite_json '+str(netlist)+'\n')
            command=[args.yosys,'-Q','-T','-s',str(script)]
            with (out/(name+'.log')).open('w') as stream:
                result=subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
            if result.returncode:raise RuntimeError((out/(name+'.log')).read_text()[-6000:])
            design=json.loads(netlist.read_text())
            cells=[(module_name+'.'+cell_name,cell)
                   for module_name,module in design['modules'].items()
                   for cell_name,cell in module.get('cells',{}).items()]
            macros=[(n,c) for n,c in cells if c['type']=='RAMTP128X16']
            expected=banks*(bank_bytes//2048)*8
            if len(macros)!=expected:raise RuntimeError(f'{name}: expected {expected} RAMTP128X16, got {len(macros)}')
            if any(c['type']=='RAMTP1024X16' for _,c in cells):raise RuntimeError('Unexpected macro depth')
            if any(c['type'].startswith('$mem') for _,c in cells) or any(
                module.get('memories') for module in design['modules'].values()
            ):raise RuntimeError('Unexpected inferred data memory')
            if any('latch' in c['type'].lower() for _,c in cells):raise RuntimeError('Unexpected latch')
            for instance,cell in macros:
                if {p:len(bits) for p,bits in cell['connections'].items()}!=widths:
                    raise RuntimeError(f'Macro interface differs: {instance}')
                if cell['connections']['CLKA']!=cell['connections']['CLKB']:
                    raise RuntimeError(f'Macro clocks differ: {instance}')
                if cell['connections']['RET1N']!=['1'] or cell['connections']['COLLDISN']!=['1']:
                    raise RuntimeError(f'Macro mode differs: {instance}')
            physical_bits=len(macros)*128*16;logical_bits=bank_bytes*banks*8
            assert physical_bits==logical_bits
            profiles.append(dict(passed=True,bank_bytes=bank_bytes,bank_count=banks,
                ram_macros=len(macros),macro_name='RAMTP128X16',macro_depth=128,macro_width=16,
                logical_data_bits=logical_bits,physical_data_bits=physical_bits,unused_data_bits=0,
                extra_inferred_memories=0,
                read_write_clock_checks=len(macros),macro_port_checks=len(macros)*len(widths),
                compile_command=command,script_sha256=sha(script),netlist_sha256=sha(netlist)))
    assert before=={str(p.relative_to(ROOT)):sha(p) for p in sources}
    report=dict(passed=True,validation='structural macro capacity and connectivity',
        foundry_timing_validated=False,macro_model='black-box interface declarations',
        source_sha256=before,profiles=profiles,
        yosys_version=subprocess.check_output([args.yosys,'-V'],text=True).strip())
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed=True,profiles=len(profiles),seven_bank_macro_counts=
        {p['bank_bytes']:p['ram_macros'] for p in profiles if p['bank_count']==7})))

if __name__=='__main__':main()
