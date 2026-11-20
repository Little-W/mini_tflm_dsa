#!/usr/bin/env python3
"""为两种 FIFO 布局准备相同的有效端口和封装引脚约束。"""
import argparse
import csv
import json
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--synthesis',type=Path,required=True)
    p.add_argument('--package-pins',type=Path,required=True)
    p.add_argument('--xdc',type=Path,required=True)
    args=p.parse_args()
    names=None
    for case in ('reference','cyclic'):
        folder=args.synthesis/case
        design=json.loads((folder/'mapped.json').read_text())
        module=design['modules']['vec_s8_to_fifo_full']
        used={bit for cell in module['cells'].values() for port,bits in cell['connections'].items()
              if cell['port_directions'][port]!='output' for bit in bits if isinstance(bit,int)}
        removed={}
        for port in ('coalesce_rows','coalesce_cols'):
            removed[port]=module['ports'][port]['bits'][5:]
            if any(bit in used for bit in removed[port]):
                raise RuntimeError('Port trimming would remove a connected input: '+port)
            module['ports'][port]['bits']=module['ports'][port]['bits'][:5]
        (folder/'mapped_ports.json').write_text(json.dumps(design))
        (folder/'unused_port_bits.json').write_text(json.dumps(removed,indent=2)+'\n')
        current=[name if len(port['bits'])==1 else f'{name}[{index}]'
                 for name,port in module['ports'].items() for index in range(len(port['bits']))]
        if names is not None and names!=current:raise RuntimeError('The port order differs between configurations')
        names=current
    with args.package_pins.open() as stream:
        pins=[row['pin'] for row in csv.DictReader(stream) if row['site'].startswith('IOB_') and row['pin']!='R4']
    if len(pins)+1<len(names):raise RuntimeError('Insufficient package pins')
    pin_iter=iter(pins)
    lines=['# 输出 FIFO 独立资源测量的封装引脚。',
           'create_clock -name clk -period 6.666666667 [get_ports clk]']
    for name in names:
        pin='R4' if name=='clk' else next(pin_iter)
        lines += [f'set_property PACKAGE_PIN {pin} [get_ports {{{name}}}]',
                  f'set_property IOSTANDARD LVCMOS15 [get_ports {{{name}}}]']
    args.xdc.parent.mkdir(parents=True,exist_ok=True)
    args.xdc.write_text('\n'.join(lines)+'\n')


if __name__=='__main__':main()
