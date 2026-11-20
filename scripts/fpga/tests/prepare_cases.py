#!/usr/bin/env python3
"""Generate explicit primitive cases without folding repeated input ports."""
import argparse
import json
import subprocess
from pathlib import Path


CASES = {
    'shared_five': ([0, 1, 2], [2, 3, 4], True),
    'distinct_six': ([0, 1, 2], [3, 4, 5], False),
    'repeated_six': ([0, 0, 0, 1, 2], [0, 0, 3, 4, 5], False),
    'repeated_three': ([0, 0, 1], [1, 2, 2], True),
}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--out',type=Path,default=Path('build/lut_packing_cases'))
    p.add_argument('--constrain',type=Path)
    p.add_argument('--write',type=Path)
    a=p.parse_args()
    if a.constrain:
        d=json.loads(a.constrain.read_text())
        m=next(iter(d['modules'].values()))
        upper=m['cells']['u_upper']['attributes']
        lower=m['cells']['u_lower']['attributes']
        for c in [upper,lower]:
            assert 'BEL' not in c
            assert c.get('X_LUT_LOGICAL_OUTPUT') not in [None,0,'00000000000000000000000000000000']
        upper['CONSTR_CHILDREN']='u_lower'
        upper['CONSTR_ABS_Z']=f'{1:032b}'
        upper['CONSTR_Z']=f'{0:032b}'
        lower['CONSTR_PARENT']='u_upper'
        lower['CONSTR_X']=f'{0:032b}'
        lower['CONSTR_Y']=f'{0:032b}'
        lower['CONSTR_Z']=f'{1:032b}'
        lower['CONSTR_ABS_Z']=f'{0:032b}'
        (a.write or a.constrain.with_name('packed_pair.json')).write_text(json.dumps(d,indent=2)+'\n')
        return
    a.out.mkdir(parents=True,exist_ok=True)
    from pyosys import libyosys as ys
    manifest={}
    for name,(upper,lower,legal) in CASES.items():
        dest=(a.out/name).resolve();dest.mkdir(parents=True,exist_ok=True)
        lines=['module soc_top(input wire [5:0] i_data, output wire [1:0] o_data);']
        for part,pins,value in [('upper',upper,0x96969696),('lower',lower,0xE8E8E8E8)]:
            n=len(pins);init=value&((1<<(1<<n))-1)
            inputs=', '.join(f'.I{k}(i_data[{v}])' for k,v in enumerate(pins))
            obit=0 if part=='upper' else 1
            lines.append(f'  (* keep = 1 *) LUT{n} #(.INIT({1<<n}\'h{init:x})) u_{part} ({inputs}, .O(o_data[{obit}]));')
        lines.append('endmodule')
        (dest/'design.sv').write_text('\n'.join(lines)+'\n')
        xdc=[]
        for port,pin in zip([f'i_data[{i}]' for i in range(6)]+['o_data[0]','o_data[1]'],['AA1','AA3','AA4','AA5','AA6','AA8','AB3','AB5']):
            xdc.append(f'set_property PACKAGE_PIN {pin} [get_ports {{{port}}}]')
            xdc.append(f'set_property IOSTANDARD LVCMOS15 [get_ports {{{port}}}]')
        (dest/'pins.xdc').write_text('\n'.join(xdc)+'\n')
        commands=[
            'read_verilog -lib -specify +/xilinx/cells_sim.v',
            'read_verilog -lib +/xilinx/cells_xtra.v',
            f'read_verilog {dest}/design.sv',
            'hierarchy -check -top soc_top',
            'iopadmap -inpad IBUF O:I -outpad OBUF I:O',
            'clean',
            'check -assert',
            'blackbox =A:whitebox',
            f'write_json {dest}/implementation.json',
        ]
        (dest/'prepare.ys').write_text('\n'.join(commands)+'\n')
        design=ys.Design()
        for command in commands:ys.run_pass(command,design)
        mapped=json.loads((dest/'implementation.json').read_text())['modules']['soc_top']['cells']
        for cell,pins in [('u_upper',upper),('u_lower',lower)]:
            assert mapped[cell]['type']==f'LUT{len(pins)}'
            actual=[mapped[cell]['connections'][f'I{i}'][0] for i in range(len(pins))]
            assert len(set(actual))==len(set(pins))
        manifest[name]={'upper_inputs':upper,'lower_inputs':lower,'unique_inputs':len(set(upper+lower)), 'same_position_legal':legal,'directory':str(dest)}
    (a.out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(manifest,indent=2))


if __name__=='__main__':main()
