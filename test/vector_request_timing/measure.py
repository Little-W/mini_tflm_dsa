#!/usr/bin/env python3
"""比较完整向量引擎，并提取请求有效和读取地址的实际组合路径。"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins


def boundary_paths(source, target):
    """仅为端口路径统计增加接收边界，资源统计使用原始映射网表。"""
    module = json.loads((target/'mapped.json').read_text())['modules']['vector_engine']
    for name, origin in register_origins(source/'pre_lut.il').items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
    for index, port in enumerate(('rd_base_addr', 'win_req_valid')):
        bits = module['ports'][port]['bits']
        module['cells']['port_boundary_'+port] = {
            'type': 'FDRE', 'parameters': {}, 'attributes': {'fpga_register_origin': port},
            'port_directions': {'D': 'input', 'Q': 'output', 'C': 'input', 'CE': 'input', 'R': 'input'},
            'connections': {'D': bits, 'Q': list(range(990000+100*index, 990000+100*index+len(bits))),
                            'C': ['0'], 'CE': ['1'], 'R': ['0']}}
    def starts(name, cell, port):
        origin = cell.get('attributes', {}).get('fpga_register_origin', '')
        return origin == 'u_control.state_pool_read' or origin.startswith('u_control.tap [')
    return connected_paths(module, limit=2, group_limit=2, root_filter=starts,
                           sink_filter=lambda name, cell, port: name.startswith('port_boundary_'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    names = ('vector_engine_address', 'vector_read_address_add', 'vector_config_check')
    reference = []
    for name in names:
        path = out/(name+'.sv')
        path.write_text(subprocess.check_output(['git', 'show',
            '548bda54:rtl/npu/conv/'+name+'.sv'], cwd=ROOT, text=True))
        reference.append(str(path))
    options = ['-DSYNTHESIS=1', '-DXILINX_FPGA=1', '-GTILE=16', '-GBUS_WIDTH=64',
               '-GPE_COUNT=8', '-GWINDOW_LANES=8', '-GSHARED_STORAGE_ENABLE=1',
               '-GSHARED_QUANT_ENABLE=0', '-GSHARED_STORAGE_ADDR_WIDTH=12']
    cases = {name: {'top': 'vector_engine',
                   'sources': [str(ROOT/'rtl/npu/conv/vector_engine.sv'), *files],
                   'options': options, 'configuration': '16通道、8个PE、64位总线、共享存储、本地量化'}
             for name, files in [('reference', reference),
                                ('candidate', [str(ROOT/'rtl/npu/conv'/(name+'.sv')) for name in names])]}
    configuration = out/'cases.json'
    configuration.write_text(json.dumps(cases, indent=2)+'\n')
    subprocess.run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--case-config', configuration,
                    '--cases', 'reference', 'candidate', '--out', out, '--through', 'pre_lut'], cwd=ROOT, check=True)
    results = {}
    for name in cases:
        target = out/(name+'_cost')
        subprocess.run([sys.executable, ROOT/'scripts/fpga/remap_fpga_luts.py', '--source', out/name,
                        '--out', target, '--mode', 'physical-cost', '--delay-target-ps', '6667',
                        '--wire-delay-ps', '300', '--max-lut-inputs', '8'], cwd=ROOT, check=True)
        data = json.loads((target/'metrics.json').read_text())
        results[name] = {'resources': data['resources'], 'paths': data['paths'],
                        'request_boundary_paths': boundary_paths(out/name, target),
                        'manifest': json.loads((target/'manifest.json').read_text()),
                        'verification': json.loads((target/'verification.json').read_text())}
    (out/'summary.json').write_text(json.dumps({'production_options': options, 'results': results}, indent=2)+'\n')

if __name__ == '__main__':
    main()
