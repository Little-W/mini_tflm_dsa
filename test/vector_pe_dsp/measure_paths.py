#!/usr/bin/env python3
"""统计 PE 寄存器边界和完整向量模块中的实际连接路径。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/fpga'))
from netlist_metrics import connected_paths, parameter, register_origins, resources


def is_pe_dsp(cell):
    return (cell['type'] == 'DSP48E1' and
            'vector_pe.sv' in cell.get('attributes',{}).get('src','') and
            parameter(cell, 'AREG') == 1 and parameter(cell, 'BREG') == 1)


def measure(folder):
    mapped = folder/'mapped.json'
    module = json.loads(mapped.read_text())['modules']['vector_engine']
    for name,origin in register_origins(folder/'pre_lut.il').items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes',{})['fpga_register_origin'] = origin
    selected = {name:cell for name,cell in module['cells'].items() if is_pe_dsp(cell)}
    assert len(selected) == 8,len(selected)
    registers = {name:{key:parameter(cell,key) for key in ['AREG','BREG','CREG','MREG','PREG']}
                 for name,cell in selected.items()}
    paths = {}
    analyses = {
        'pe_input_capture':{'sink_filter':lambda name,cell,port:is_pe_dsp(cell) and port in ['A','B']},
        'pe_registered_arithmetic_output':{'root_filter':lambda name,cell,port:is_pe_dsp(cell) and port == 'P'},
        'pe_operand_registers':{'root_filter':lambda name,cell,port:
            any(token in cell.get('attributes',{}).get('fpga_register_origin','')
                for token in ['pe_a_q','pe_b_q','pe_acc_q','operand_a_q','operand_acc_q'])},
    }
    for name,filters in analyses.items():
        analysis = connected_paths(module,limit=1,group_limit=0,**filters)
        assert analysis['graph_complete']
        paths[name] = {'longest_register_path_cells':analysis['longest_register_path_cells'],
                       'paths':analysis['register_to_register_paths']}
    overall = connected_paths(module,limit=1,group_limit=12)
    assert overall['graph_complete']
    return {'mapped_sha256':hashlib.sha256(mapped.read_bytes()).hexdigest(),
            'resources':resources(module['cells']),'pe_dsp_registers':registers,'pe_paths':paths,
            'longest_register_path_cells':overall['longest_register_path_cells'],
            'meets_15_cell_limit':overall['longest_register_path_cells'] <= 15,
            'distinct_register_path_groups':overall['distinct_register_path_groups']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--synthesis',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args = parser.parse_args()
    report = {'method':'Connected register-to-register cell paths. Internal DSP arithmetic and route delay require device timing analysis.',
              'reference':measure(args.synthesis/'vector_reference'),
              'registered':measure(args.synthesis/'vector_registered')}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,indent=2)+'\n')
    for label,item in report.items():
        if label == 'method':continue
        print(label,item['longest_register_path_cells'],
              {name:entry['longest_register_path_cells'] for name,entry in item['pe_paths'].items()})


if __name__ == '__main__':
    main()
