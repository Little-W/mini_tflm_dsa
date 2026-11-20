#!/usr/bin/env python3
"""核对实际 FASM 中的 LUT、进位入口和触发器输入选择。"""
import argparse,hashlib,json,re
from pathlib import Path

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--physical',type=Path,required=True)
p.add_argument('--fasm',type=Path,required=True)
p.add_argument('--lut-init',type=Path,required=True)
p.add_argument('--tilegrid',type=Path,required=True)
p.add_argument('--out',type=Path,required=True)
a=p.parse_args()
grid=json.loads(a.tilegrid.read_text());site_tiles={site:(tile,kind) for tile,data in grid.items() for site,kind in data['sites'].items()}
modules=json.loads(a.physical.read_text())['modules'];m=next(x for x in modules.values() if x.get('cells'));cells=m['cells']
features=set(line.strip() for line in a.fasm.read_text().splitlines() if line.strip() and not line.startswith('#'))
actual_init={name:int(value,2) for name,value in re.findall(r"(\S+)\.INIT\[63:0\] = 64'b([01]{64})",a.fasm.read_text())}
expected_init=json.loads(a.lut_init.read_text())

def prefix(site):
    tile,kind=site_tiles[site];x=int(re.search(r'_X(\d+)Y',site).group(1))
    return f'{tile}.{kind}_X{x%2}'

def unique_feature(stem,expected):
    selected=sorted(x for x in features if x.startswith(stem+'.'))
    assert selected==[stem+'.'+expected],(stem,selected,expected)

for site_lut,value in expected_init.items():
    site,letter=site_lut.split('/');name=prefix(site)+'.'+letter+'LUT'
    assert actual_init.get(name,0)==value,(name,actual_init.get(name),value)

net_routes={data['bits'][0]:data['attributes'].get('ROUTING','') for data in m['netnames'].values() if len(data['bits'])==1}
constants={}
for c in cells.values():
    if c['type'] in ('PSEUDO_GND','PSEUDO_VCC'):
        for port,bits in c['connections'].items():
            if c['port_directions'][port]=='output':
                for bit in bits:constants[bit]=int(c['type']=='PSEUDO_VCC')
carry_rows=[];ff_rows=[]
for name,c in cells.items():
    if c['type']=='CARRY4':
        site=c['attributes']['NEXTPNR_BEL'].split('/')[0]
        cin=c['connections'].get('CIN',[]);cyinit=c['connections'].get('CYINIT',[])
        if 'PRECYINIT_CONST' in c['parameters']:
            expected='C'+str(int(c['parameters']['PRECYINIT_CONST'],2))
        elif cin and cin[0] not in constants:
            expected='CIN'
        elif cyinit and cyinit[0] not in constants:
            expected='AX'
        else:
            expected='C'+str(constants.get((cyinit or cin or [None])[0],0))
        unique_feature(prefix(site)+'.PRECYINIT',expected)
        carry_rows.append({'cell':name,'site':site,'selection':expected})
    elif c['type']=='SLICE_FFX':
        site,bel=c['attributes']['NEXTPNR_BEL'].split('/');mux=bel+'MUX';letter=bel[0]
        routes=[part for part in net_routes[c['connections']['D'][0]].split(';') if part.startswith(f'SITEPIP/{site}/{mux}/')]
        assert len(routes)==1,(name,routes)
        source=routes[0].rsplit('/',1)[1]
        if '5FF' in bel:
            options={letter+'5LUT_O5':'IN_A',letter+'X':'IN_B'}
        else:
            index='ABCD'.index(letter)
            options={f'CARRY4_O{index}':'XOR',f'CARRY4_CO{index}':'CY',letter+'X':letter+'X',
                     letter+'5LUT_O5':'O5',letter+'6LUT_O6':'O6'}
        assert source in options,(name,bel,source)
        expected=options[source];unique_feature(prefix(site)+'.'+mux,expected)
        ff_rows.append({'cell':name,'site':site,'mux':mux,'source':source,'selection':expected})
result={'passed':True,'lut_positions':len(expected_init),'carry_muxes':len(carry_rows),'ff_input_muxes':len(ff_rows),
        'carry_selections':carry_rows,'ff_selections':ff_rows,
        'sha256':{str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in [a.physical,a.fasm,a.lut_init,a.tilegrid]},
        'method':'Compare emitted FASM LUT INIT, PRECYINIT and FFMUX selections against physical netlist parameters, site map and per-net routed site pips.'}
a.out.write_text(json.dumps(result,indent=2)+'\n');print({k:result[k] for k in ['passed','lut_positions','carry_muxes','ff_input_muxes']})
