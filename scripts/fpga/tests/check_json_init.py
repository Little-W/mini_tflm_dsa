#!/usr/bin/env python3
"""Check routed physical LUT INIT against the packed logical functions."""
import argparse
import hashlib
import itertools
import json
import re
import subprocess
from collections import defaultdict
from pathlib import Path

from review_lut_packing import PREFIX, braced


def module(path):
    modules=json.loads(path.read_text())['modules']
    return next(m for m in modules.values() if m.get('cells'))


def names(m):
    result=defaultdict(set)
    for name,net in m['netnames'].items():
        for index,bit in enumerate(net['bits']):
            result[bit].add(name if len(net['bits'])==1 else f'{name}[{index}]')
    result['0'].add('$PACKER_GND_NET')
    result['1'].add('$PACKER_VCC_NET')
    return result


def constants(aliases):
    return {bit:int('$PACKER_VCC_NET' in value) for bit,value in aliases.items()
            if {'$PACKER_GND_NET','$PACKER_VCC_NET'}&value}


def logical_pins(cell):
    pins={}
    for port,bits in cell['connections'].items():
        if not bits:continue
        for original in re.findall(r'I\d+',cell['attributes'].get('X_ORIG_PORT_'+port,'')):
            assert original not in pins
            pins[original]=bits[0]
    return pins


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--packed',type=Path,required=True)
    p.add_argument('--physical',type=Path,required=True)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    old,new=module(a.packed),module(a.physical)
    old_names,new_names=names(old),names(new);constant=constants(new_names)
    sites=defaultdict(dict);logical={};comparisons=0;pin_checks=0
    for name,c in new['cells'].items():
        if c['type']!='SLICE_LUTX':continue
        original=c['attributes'].get('X_ORIG_TYPE','')
        if not re.fullmatch('LUT[1-6]',original):continue
        oc=old['cells'][name]
        assert original==oc['attributes']['X_ORIG_TYPE'],name
        assert c['parameters']['INIT']==oc['parameters']['INIT'],name
        op,np=logical_pins(oc),logical_pins(c)
        assert op.keys()==np.keys(),(name,op,np)
        for pin in op:
            assert old_names[op[pin]] & new_names[np[pin]],(name,pin,old_names[op[pin]],new_names[np[pin]])
            pin_checks+=1
        logical[name]=np
        bel=c['attributes'].get('NEXTPNR_BEL',c['attributes'].get('BEL',''))
        match=re.fullmatch(r'(.+/[A-D])([56])LUT',bel)
        assert match,(name,bel)
        site,half=match.groups();assert half not in sites[site]
        sites[site][half]=(name,c)
        output='O5' if half=='5' else 'O6'
        assert c['connections'].get(output), (name,output)
    fasm=(a.source/'fasm.cc').read_text()
    cpp=PREFIX+braced(fasm,fasm.index('std::vector<IdString> get_inputs'))+'\n'
    cpp+=braced(fasm,fasm.index('std::vector<bool> get_lut_init'))+'\n};\nint main(){Harness h;\n'
    for index,(site,halves) in enumerate(sorted(sites.items())):
        cpp+='{\n'
        for half,(name,c) in halves.items():
            var='c'+half;cpp+=f'CellInfo {var};\n'
            for key,value in c['attributes'].items():
                if key=='X_ORIG_TYPE' or key.startswith('X_ORIG_PORT_A'):
                    cpp+=f'{var}.attrs[h.id({json.dumps(key)})]=std::string({json.dumps(value)});\n'
            init=int(c['parameters']['INIT'],2)
            cpp+=f'h.set_init({var},UINT64_C({init}));\n'
        cpp+=f'auto bits=h.get_lut_init({"&c6" if "6" in halves else "nullptr"},{"&c5" if "5" in halves else "nullptr"});\n'
        cpp+='uint64_t value=0;for(int i=0;i<64;i++)if(bits[i])value|=UINT64_C(1)<<i;\n'
        cpp+=f'std::cout<<{index}<<" "<<value<<"\\n";\n}}\n'
    cpp+='}\n'
    src=a.out/'physical_init.cc';src.write_text(cpp);exe=a.out/'physical_init'
    subprocess.run(['g++','-O2','-std=c++17',str(src),'-o',str(exe)],check=True)
    actual=dict(tuple(map(int,line.split())) for line in subprocess.check_output([str(exe)],text=True).splitlines())
    for index,(site,halves) in enumerate(sorted(sites.items())):
        physical={};used=set()
        for half,(name,c) in halves.items():
            for port,bits in c['connections'].items():
                if not re.fullmatch('A[1-6]',port) or not bits:continue
                net=bits[0]
                if port in physical:assert physical[port]==net,(site,port,physical[port],net)
                physical[port]=net;used.add(net)
        variables=sorted(used-constant.keys(),key=str)
        assert len(variables)<=6,(site,variables)
        if len(halves)==2:
            upper,lower=halves['6'][1],halves['5'][1]
            cofactor=upper['attributes'].get('X_LUT_COFACTOR_PAIR')
            if cofactor:
                assert lower['attributes'].get('X_LUT_COFACTOR_PAIR')==cofactor
                assert upper['attributes'].get('X_ORIG_PORT_A6')=='I5'
                assert not lower['connections'].get('A6')
                assert int(upper['parameters']['INIT'],2)&0xffffffff==int(lower['parameters']['INIT'],2)&0xffffffff
                for pin in ('A1','A2','A3','A4','A5'):
                    assert upper['connections'].get(pin)==lower['connections'].get(pin)
                    assert upper['attributes'].get('X_ORIG_PORT_'+pin)==lower['attributes'].get('X_ORIG_PORT_'+pin)
            else:
                assert len(used-{physical.get('A6')} if physical.get('A6') in constant else used)<=5
                assert physical.get('A6') in constant and constant[physical['A6']]==1
        for assignment in itertools.product([0,1],repeat=len(variables)):
            values=constant|dict(zip(variables,assignment))
            pi=sum(values.get(physical.get(f'A{k+1}'),0)<<k for k in range(6))
            for half,(name,c) in halves.items():
                original=old['cells'][name]
                li=sum(values[bit]<<int(pin[1:]) for pin,bit in logical[name].items())
                expected=int(original['parameters']['INIT'],2)>>li&1
                observed=actual[index]>>(pi if half=='6' else pi&31)&1
                assert observed==expected,(site,name,assignment,observed,expected)
                comparisons+=1
    summary={'packed_json':str(a.packed.resolve()),'physical_json':str(a.physical.resolve()),
             'logical_luts':len(logical),'physical_lut_sites':len(sites),
             'paired_sites':sum(len(x)==2 for x in sites.values()),
             'logical_input_connections_checked':pin_checks,'output_comparisons':comparisons,
             'fasm_source_sha256':hashlib.sha256((a.source/'fasm.cc').read_bytes()).hexdigest(),'passed':True}
    (a.out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    (a.out/'physical_lut_init.json').write_text(json.dumps(
        {site: actual[index] for index, site in enumerate(sorted(sites))}, indent=2) + '\n')
    print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
