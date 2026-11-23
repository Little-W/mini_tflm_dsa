#!/usr/bin/env python3
"""统计实际 ASIC 参数下前端的乘法位宽与寄存器位数。"""
from pathlib import Path
import argparse
import collections
import hashlib
import json
import runpy
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source-root', type=Path, default=ROOT)
parser.add_argument('--reference-source', type=Path)
parser.add_argument('--prepare-only', action='store_true')
parser.add_argument('--out', type=Path, default=ROOT/'build/frontend_pipeline/structure')
args = parser.parse_args()
OUT = args.out.resolve()
OUT.mkdir(parents=True, exist_ok=True)
relative_sources = [
    'rtl/npu/conv/conv_im2col_pkg.sv',
    'rtl/npu/dma/cache/conv_sdp_ram.sv',
    'rtl/npu/dma/cache/conv_next_use_predictor.sv',
    'rtl/npu/conv/conv_axi_span_reader.sv',
    'rtl/npu/dma/cache/conv_read_cache.sv',
    'rtl/npu/conv/conv_im2col_frontend.sv',
    'rtl/common/regfile.v', 'rtl/common/onehot_check.sv',
    'rtl/common/add_equal.sv', 'rtl/common/parallel_prefix_add.sv',
    'rtl/common/unsigned_compare.sv',
]
source_tools = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))
resolve_sources = source_tools['with_dependencies']
results = {}
prepared_sources = {}
sources = [('current', args.source_root.resolve())]
if args.reference_source is not None:
    sources.insert(0, ('reference', args.reference_source.resolve()))
for name, source in sources:
    script = OUT / (name + '.ys')
    log = OUT / (name + '.log')
    netlist = OUT / (name + '.json')
    resolved = resolve_sources([source/path for path in relative_sources], source)
    prepared_sources[name] = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                             for path in source_tools['input_files'](resolved, source)}
    script.write_text('read_slang --top conv_im2col_frontend -D ASIC_SYNTHESIS=1 -D SYNTHESIS=1 '
                     '-GSIZE=16 -GSLOT_W=6 -GLANES=16 -GBUS_WIDTH=64 -GCACHE_SETS=16 '
                     '-GCACHE_WAYS=2 -GLINE_BYTES=128 -GCACHE_RESPONSE_DEPTH=2 ' +
                     '-I'+shlex.quote(str(source/'include'))+' ' +
                     '-I'+shlex.quote(str(source/'asic/rtl'))+' ' +
                     ' '.join(map(str, resolved)) + '\n'
                     'proc\nflatten\nopt\nwreduce\nopt\nmemory_collect\nstat\n'
                     f'write_json {netlist}\n')
    if args.prepare_only:
        continue
    with log.open('w') as output:
        run = subprocess.run([sys.executable, str(ROOT/'scripts/fpga/open_fpga_synth.py'),
                              '--worker', str(script)], stdout=output, stderr=subprocess.STDOUT)
    assert run.returncode == 0, log
    design = json.loads(netlist.read_text())
    module = design['modules']['conv_im2col_frontend']
    cells = module['cells']
    body = {name: cell for name, cell in cells.items()
            if re.search(r'conv_im2col_(?:frontend|geometry|descriptor|stream|prefetch)\.sv:',
                         cell.get('attributes', {}).get('src', ''))}
    multipliers = []
    registers = collections.Counter()
    register_bits = 0
    register_names = collections.Counter()
    by_bit = collections.defaultdict(list)
    for net_name, net in module['netnames'].items():
        if net.get('hide_name', 0) == 0:
            for bit in net['bits']:
                if isinstance(bit, int):
                    by_bit[bit].append(net_name)
    for cell_name, cell in body.items():
        kind = cell['type']
        if kind == '$mul':
            params = cell['parameters']
            multipliers.append({'name': cell_name,
                'a_width': int(params['A_WIDTH'], 2),
                'b_width': int(params['B_WIDTH'], 2),
                'y_width': int(params['Y_WIDTH'], 2),
                'src': cell['attributes']['src']})
        if kind.startswith(('$dff', '$adff', '$sdff')):
            width = len(cell['connections']['Q'])
            registers[kind] += width
            register_bits += width
            for bit in cell['connections']['Q']:
                names = by_bit.get(bit, [])
                if names:
                    register_names[min(names, key=lambda name: (len(name), name))] += 1
    results[name] = {'source_sha256': hashlib.sha256(
        (source/'rtl/npu/conv/conv_im2col_frontend.sv').read_bytes()).hexdigest(),
        'multipliers': multipliers, 'multiplier_count': len(multipliers),
        'register_bits': register_bits, 'register_bits_by_type': dict(registers),
        'register_families': dict(register_names)}
summary = {'prepared_only': args.prepare_only, 'prepared_source_sha256': prepared_sources, 'scope': 'RTL arithmetic after width reduction and register optimization; no ASIC cell mapping.',
           'parameters': {'SIZE': 16, 'SLOT_W': 6, 'LANES': 16, 'BUS_WIDTH': 64,
                          'CACHE_SETS': 16, 'CACHE_WAYS': 2, 'LINE_BYTES': 128},
           'results': results}
(OUT/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
print(json.dumps({name: {'multiplier_count': result['multiplier_count'],
                         'register_bits': result['register_bits']} for name, result in results.items()}))
