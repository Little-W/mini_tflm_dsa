#!/usr/bin/env python3
"""比较读写仲裁器的授予、计数和描述寄存器；DMA 内部作为黑盒边界。"""
import argparse
import collections
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))


def window_grant_boundary(module):
    """将 DMA 端口作为边界，检查普通请求到窗口接收信号的组合连接。"""
    from netlist_metrics import connected_paths
    design = copy.deepcopy(module)
    cells = design['cells']
    next_bit = max(bit for cell in cells.values() for bits in cell['connections'].values()
                   for bit in bits if isinstance(bit, int)) + 1

    def register(name, data, output):
        cells[name] = dict(type='FDRE', parameters={}, attributes={},
            port_directions={'C': 'input', 'CE': 'input', 'R': 'input', 'D': 'input', 'Q': 'output'},
            connections={'C': ['0'], 'CE': ['1'], 'R': ['0'], 'D': [data], 'Q': [output]})

    for name in ('ia_req', 'kernel_req', 'bias_req', 'quant_req', 'dw_req'):
        register('boundary_source_' + name, '0', design['ports'][name]['bits'][0])
    register('boundary_sink_win_req_ready', design['ports']['win_req_ready']['bits'][0], next_bit)
    next_bit += 1
    for name, cell in list(cells.items()):
        if not cell['type'].startswith('axi_dual_block_dma'):
            continue
        del cells[name]
        register('boundary_sink_dma_win_req_valid', cell['connections']['win_req_valid'][0], next_bit)
        next_bit += 1
    paths = connected_paths(design,
        root_filter=lambda name, cell, port: name.startswith('boundary_source_'),
        sink_filter=lambda name, cell, port: name.startswith('boundary_sink_'))
    return dict(scope='Ordinary request inputs to window ready and DMA window-valid input; DMA is a port boundary',
                graph_complete=paths['graph_complete'],
                longest_combinational_path_cells=paths['longest_register_path_cells'],
                paths=paths['register_to_register_paths'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-ref')
    args = parser.parse_args()
    out = args.out.resolve()
    snapshot = out / 'sources'
    snapshot.mkdir(parents=True, exist_ok=True)
    names = ('rtl/npu/conv/conv_im2col_pkg.sv', 'rtl/npu/dma/axi_block_dma_arbiter.sv',
             'rtl/npu/dma/axi_dual_block_dma.sv')
    sources = []
    hashes = {}
    for name in names:
        content = (subprocess.check_output(['git', 'show', f'{args.reference_ref}:{name}'], cwd=ROOT)
                   if args.reference_ref else (ROOT / name).read_bytes())
        hashes[name] = hashlib.sha256(content).hexdigest()
        path = snapshot / Path(name).name
        path.write_bytes(content)
        sources.append(path)
    dma_text = sources[-1].read_text()
    header_end = re.search(r'^\s*\);', dma_text, re.MULTILINE).end()
    blackbox = snapshot / 'dma_interface.sv'
    blackbox.write_text(dma_text[:header_end] + '\nendmodule\n')
    sources[-1] = blackbox
    mapped = out / 'mapped.json'
    script = out / 'run.ys'
    script.write_text('read_slang --keep-hierarchy --top axi_block_dma_arbiter -GSIZE=16 -GDMA_SIZE=64 '
        '-GBUS_WIDTH=64 -GCACHE_BLOCKS=64 -GCONV_CACHE_SETS=128 ' +
        ' '.join(shlex.quote(str(path)) for path in sources) + '\n' +
        'blackbox axi_dual_block_dma*\n' +
        'hierarchy -check -top axi_block_dma_arbiter\n' +
        'synth_xilinx -top axi_block_dma_arbiter -family xc7 -noiopad -noclkbuf -flatten\n' +
        'check -assert\nstat -tech xilinx\nwrite_json ' + shlex.quote(str(mapped)) + '\n')
    with (out / 'synthesis.log').open('w') as log:
        subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                        '--worker', str(script)], stdout=log, stderr=subprocess.STDOUT, check=True)
    spec = importlib.util.spec_from_file_location('fpga_synth', ROOT / 'scripts/fpga/open_fpga_synth.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    design = json.loads(mapped.read_text())['modules']['axi_block_dma_arbiter']
    cells = design['cells']
    dma_cells = [cell for cell in cells.values() if cell['type'].startswith('axi_dual_block_dma')]
    assert len(dma_cells) == 1
    assert len(dma_cells[0]['connections']['rd_slot_id']) == 6
    assert len(dma_cells[0]['connections']['m_axi_rdata']) == 64
    counts = collections.Counter(cell['type'] for cell in cells.values())
    path = module.logic_depth(cells)
    result = {'scope': 'axi_block_dma_arbiter; axi_dual_block_dma is a black box',
              'reference_ref': args.reference_ref, 'source_sha256': hashes,
              'source_snapshot': str(snapshot),
              'configuration': {'SIZE': 16, 'DMA_SIZE': 64, 'BUS_WIDTH': 64,
                                'CACHE_BLOCKS': 64, 'CONV_CACHE_SETS': 128},
              'lut_cells': sum(n for cell, n in counts.items() if re.fullmatch('LUT[1-6]', cell)),
              'flip_flops': sum(n for cell, n in counts.items() if cell.startswith(('FDCE', 'FDPE', 'FDRE', 'FDSE'))),
              'longest_combinational_path_cells': len(path),
              'longest_combinational_path': path, 'cell_counts': dict(sorted(counts.items())),
              'window_grant_boundary': window_grant_boundary(design)}
    (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({key: result[key] for key in ('lut_cells', 'flip_flops', 'longest_combinational_path_cells')}))


if __name__ == '__main__':
    main()
