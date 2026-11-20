#!/usr/bin/env python3
"""读取实际映射，记录预取状态至接收请求及占用条件的组合段。"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import sys

from model import ROOT, digest
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from lut_dependencies import lut_output_dependencies
from netlist_metrics import FF_PATTERN, net_names, register_origins


def analyze(mapped, pre):
    module = json.loads(mapped.read_text())['modules']['measurement_top']
    cells, names, origins = module['cells'], net_names(module), register_origins(pre)
    drivers = {}
    for name, cell in cells.items():
        for port, bits in cell['connections'].items():
            if cell['port_directions'][port] == 'output':
                for index, bit in enumerate(bits):
                    if isinstance(bit, int):
                        assert bit not in drivers
                        drivers[bit] = (name, port, index)

    @lru_cache(maxsize=None)
    def walk(bit):
        if not isinstance(bit, int) or bit not in drivers:
            return None
        name, output, index = drivers[bit]
        cell = cells[name]
        if FF_PATTERN.fullmatch(cell['type']):
            return () if origins.get(name) == 'prefetch_state [1]' else None
        inputs = lut_output_dependencies(cell, output)
        if inputs is None:
            if cell['type'] == 'CARRY4':
                inputs = []
                for port in ('CI', 'CYINIT', 'S', 'DI'):
                    values = cell['connections'][port]
                    stop = index + (1 if output == 'CO' or port == 'S' else 0)
                    selected = range(len(values)) if port in ('CI', 'CYINIT') else range(min(stop, len(values)))
                    inputs.extend((port, i, values[i]) for i in selected)
            elif cell['type'] in ('INV', 'MUXF7', 'MUXF8'):
                inputs = [(port, i, value) for port, values in cell['connections'].items()
                          if cell['port_directions'][port] == 'input' for i, value in enumerate(values)]
            else:
                raise RuntimeError('组合段出现未支持的原语：' + cell['type'])
        options = []
        for port, _, upstream in inputs:
            path = walk(upstream)
            if path is not None:
                options.append(path + ({'cell': name, 'type': cell['type'], 'input_port': port,
                    'output_port': output, 'input_net': names.get(upstream, str(upstream)),
                    'output_net': names.get(bit, str(bit))},))
        return max(options, key=len) if options else None

    targets = {'request': 'u_impl.kernel_loader_o_admission_request',
               'occupied': 'u_impl.u_admission.g_admission_fpga.admission_kernel_occupied',
               'quiescent': 'kernel_quiescent', 'ready': 'sa_ready', 'vector_start': 'vector_start'}
    result = {}
    for label, name in targets.items():
        bits = module['netnames'][name]['bits']
        assert len(bits) == 1
        path = walk(bits[0])
        assert path is not None
        result[label] = {'combinational_cells': len(path), 'path': path}
    return {'mapped_sha256': digest(mapped), 'pre_lut_sha256': digest(pre), 'targets': result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--local', type=Path, required=True)
    args = parser.parse_args()
    local = args.local.resolve()
    results = {name: analyze(local/'mapped'/name/'mapped.json', local/'pre'/name/'pre_lut.il')
               for name in ('reference','current')}
    report = {'passed': True, 'source': 'prefetch_state[1]', 'no_netlist_modification': True,
              'scope': '已经映射的寄存器输出至内部组合信号；不新增映射输入或测量寄存器。',
              'results': results, 'script_sha256': digest(Path(__file__))}
    (local/'segments.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print({name: {key: item['combinational_cells'] for key, item in value['targets'].items()}
           for name, value in results.items()})


if __name__ == '__main__':
    main()
