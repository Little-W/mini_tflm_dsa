#!/usr/bin/env python3
"""独立检查实际算术网表的转换内容及选中 DSP 的组合连接。"""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/fpga'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def integer(value):
    return int(value,2) if isinstance(value,str) else value


def independent_lut_inputs(cell, output):
    """枚举原始引脚地址，用同信号引脚掩码比较两个完整地址的输出。"""
    width=(5 if output=='O5' else 6) if cell['type']=='LUT6_2' else int(cell['type'][-1])
    bindings=[cell['connections'].get(f'I{i}',['x'])[0] for i in range(width)]
    variables={bit for bit in bindings if isinstance(bit,int)}
    raw=cell.get('parameters',{}).get('INIT')
    if raw is None or isinstance(raw,str) and not re.fullmatch('[01]+',raw.strip()):
        return variables
    table=integer(raw)
    masks={bit:sum(1<<i for i,value in enumerate(bindings) if value==bit) for bit in variables}
    addresses=[]
    for address in range(1<<width):
        if any(bit in ('0','1') and ((address>>i)&1)!=int(bit) for i,bit in enumerate(bindings)):
            continue
        if any(address&mask not in (0,mask) for mask in masks.values()):
            continue
        addresses.append(address)
    return {bit for bit,mask in masks.items()
            if any(((table>>address)^(table>>(address^mask)))&1 for address in addresses)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--mapped',type=Path,required=True)
    parser.add_argument('--selection',type=Path,required=True)
    parser.add_argument('--top',required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    args.out.parent.mkdir(parents=True,exist_ok=True)
    with (args.out.parent/'unit_tests.log').open('w') as stream:
        suite=unittest.TestLoader().discover(str(ROOT/'scripts/fpga'),pattern='test_*.py')
        result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    assert result.wasSuccessful()
    selection=json.loads(args.selection.read_text())
    assert selection.get('maximum_selected_combinational_dsps',1)==1
    assert digest(args.input)==selection['input_sha256']
    assert digest(args.mapped)==selection['output_sha256']
    original=json.loads(args.input.read_text())
    mapped=json.loads(args.mapped.read_text())
    selected={row['cell'] for row in selection['selected']}
    assert len(selected)==selection['additional_dsp_cells']
    assert original.keys()==mapped.keys()
    for key in original:
        if key!='modules':assert original[key]==mapped[key]
    assert original['modules'].keys()==mapped['modules'].keys()
    for name,module in original['modules'].items():
        actual=mapped['modules'][name]
        if name!=args.top:
            assert module==actual
            continue
        assert module.keys()==actual.keys()
        for key in module:
            if key!='cells':assert module[key]==actual[key]
        assert module['cells'].keys()==actual['cells'].keys()
        for cell_name,before in module['cells'].items():
            after=actual['cells'][cell_name]
            expected={**before,'type':'$__FPGA_DSP_ALU'} if cell_name in selected else before
            assert after==expected,cell_name
    del mapped
    cells=original['modules'][args.top]['cells']
    drivers=defaultdict(list)
    for name,c in cells.items():
        for port,bits in c['connections'].items():
            if c['port_directions'][port]=='output':
                for bit in bits:
                    if isinstance(bit,int):drivers[bit].append((name,port))
    sequential=re.compile(r'^\$(?:dff|sdff|adff|aldff|dlatch|adlatch|sr|ff)[a-z]*$|^\$_(?:DFF|SDFF|DFFE|DLATCH)|^FD[CRPS]E$|^LD[CP]E$')
    cache={}
    def inputs(name,output=None):
        key=(name,output)
        if key in cache:return cache[key]
        c=cells[name]; kind=c['type']
        if sequential.match(kind) or kind.startswith(('RAMB','URAM')):value=set()
        elif re.fullmatch(r'LUT(?:[1-6]|6_2)',kind):value=independent_lut_inputs(c,output)
        elif kind.startswith(('RAM','SRL')):
            value={bit for port,bits in c['connections'].items()
                   if re.fullmatch(r'A|A[0-9]+|ADDR[A-D]?|DPRA[0-9]*|RADR[0-9]*',port)
                   for bit in bits if isinstance(bit,int)}
        else:
            value={bit for port,bits in c['connections'].items() if c['port_directions'][port]=='input'
                   for bit in bits if isinstance(bit,int)}
        cache[key]=value
        return value
    def dsp_unregistered(c,port):
        params=c.get('parameters',{})
        if integer(params.get('PREG',1))==0:return True
        parameter={'ACOUT':'ACASCREG','BCOUT':'BCASCREG'}.get(port)
        return parameter is not None and integer(params.get(parameter,1))==0
    def upstream(starts):
        pending=list(starts); seen=set(); barriers=set()
        while pending:
            bit=pending.pop()
            if bit in seen:continue
            seen.add(bit)
            for name,port in drivers.get(bit,[]):
                c=cells[name]
                if name in selected:barriers.add(name)
                elif c['type']=='DSP48E1':
                    if dsp_unregistered(c,port):barriers.add(name)
                else:pending.extend(inputs(name,port))
        return barriers
    for name in sorted(selected):
        assert not upstream(inputs(name)),f'Combinational DSP predecessor of {name}'
    existing=0; checked_existing=0
    for name,c in cells.items():
        if c['type']!='DSP48E1':continue
        existing+=1; params=c.get('parameters',{}); starts=set()
        if integer(params.get('PREG',1))==0:starts=inputs(name)
        else:
            for parameter,ports in [('ACASCREG',('A','ACIN')),('BCASCREG',('B','BCIN'))]:
                if integer(params.get(parameter,1))==0:
                    starts.update(bit for port in ports for bit in c['connections'].get(port,[]) if isinstance(bit,int))
        if starts:
            checked_existing+=1
            assert not upstream(starts)&selected,f'Selected DSP precedes existing DSP {name}'
    assert existing==selection['existing_dsp_cells']
    assert existing+len(selected)+selection['dsp_reserve']<=selection['dsp_budget']
    sources=['scripts/fpga/lut_dependencies.py','scripts/fpga/map_wide_alu.py',
        'scripts/fpga/netlist_metrics.py','scripts/fpga/open_fpga_synth.py',
        'scripts/fpga/test_lut_dependencies.py','test/lut_dependencies/check_checkpoint.py',
        'test/vector_address_dsp/inspect_paths.py']
    report={'passed':True,'input_sha256':digest(args.input),'mapped_sha256':digest(args.mapped),
        'selection_sha256':digest(args.selection),'source_sha256':{p:digest(ROOT/p) for p in sources},
        'unit_tests_passed':result.testsRun,'unit_test_log_sha256':digest(args.out.parent/'unit_tests.log'),
        'existing_dsp_cells':existing,'selected_dsp_cells':len(selected),
        'maximum_selected_combinational_dsps':1,
        'resulting_dsp_cells':existing+len(selected),'checked_existing_combinational_dsps':checked_existing,
        'selected_dsp_combinational_predecessors':0,'selected_to_existing_combinational_dsp_paths':0,
        'netlist_change':'Only the selected $alu cell types become $__FPGA_DSP_ALU.',
        'dependency_check':'Independent original-pin truth-table enumeration and backward traversal across combinational cells.'}
    args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
