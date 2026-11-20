#!/usr/bin/env python3
"""测量完整向量引擎与实际范围读取保护器的原生 RTL。"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/conv/vector_engine.sv')
CHECKER = Path('rtl/npu/conv/vector_config_check.sv')
RANGE_STATE = ('u_range_guard.end_q', 'u_engine.u_config_check.range_end_q',
               'u_engine.u_config_check.range_end_low', 'u_engine.u_config_check.range_end_carry',
               'u_engine.u_config_check.o_read_end')
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
sys.path.insert(0, str(ROOT / 'test'))
from netlist_metrics import connected_paths, register_origins, resources
from open_fpga_synth import run_stage
from rtl_reference import read_rtl_source


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def segments(text):
    result, level, first = [], 0, 0
    for index, char in enumerate(text):
        if char in '([{': level += 1
        elif char in ')]}': level -= 1
        elif char == ',' and level == 0:
            result.append(text[first:index].strip()); first = index+1
    result.append(text[first:].strip())
    return result


def port_name(segment):
    return re.search(r'(\w+)\s*(?:\[[^\]]+\]\s*)*$', segment)[1]


def wrapper(engine, guard):
    prefix = engine[:engine.index('  import vector_engine_pkg::*;')]
    begin = prefix.index(') (')+3
    engine_ports = segments(prefix[begin:prefix.rfind(');')].strip().lstrip('('))
    guard_header = guard[:guard.index('    localparam int BUS_BYTES')]
    begin = guard_header.index(') (')+3
    guard_ports = segments(guard_header[begin:guard_header.rfind(');')].strip().lstrip('('))
    shared = {'clk', 'rst_n', 'enable', 'cfg_valid', 'cfg_base', 'cfg_end'}
    public = [item for item in guard_ports if port_name(item) not in shared]
    extra = ',\n    '.join(re.sub(r'\b'+port_name(item)+r'\b', 'guard_'+port_name(item), item)
                           for item in public)
    extra = re.sub(r'\bADDR_W\b', '32', extra)
    extra = re.sub(r'\bDATA_W\b', 'BUS_WIDTH', extra)
    prefix = prefix[:prefix.rfind(');')].rstrip()+',\n    input logic guard_enable,\n    '+extra+'\n);\n'
    prefix = prefix.replace('module vector_engine #(', 'module vector_ranges_measure #(', 1)
    body = '  vector_engine #(.TILE(TILE), .BUS_WIDTH(BUS_WIDTH), .DMA_SIZE(DMA_SIZE),\n'
    body += '      .PE_COUNT(PE_COUNT), .MAX_TAPS(MAX_TAPS), .POOL_MAX_TAPS(POOL_MAX_TAPS)) u_engine (\n'
    body += ',\n'.join('      .'+port_name(item)+'('+port_name(item)+')' for item in engine_ports)+'\n  );\n'
    mapping = {'clk':'clk', 'rst_n':'rst_n', 'enable':'guard_enable',
               'cfg_valid':'dma_cfg_valid && dma_cfg_ready', 'cfg_base':'dma_range_base', 'cfg_end':'dma_range_end'}
    body += "  conv_axi_read_guard #(.ADDR_W(32), .DATA_W(BUS_WIDTH), .SPLIT_GEMM_4K(1'b1),\n"
    body += '      .READ_OUTSTANDING(4)) u_range_guard (\n'
    body += ',\n'.join('      .'+port_name(item)+'('+mapping.get(port_name(item), 'guard_'+port_name(item))+')'
                       for item in guard_ports)+'\n  );\nendmodule\n'
    return prefix+body


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='2297cb12')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    original = out / 'reference.sv'
    original.write_text(read_rtl_source(args.reference+':'+str(SOURCE), cwd=ROOT, text=True))
    current = out / 'current.sv'; current.write_bytes((ROOT/SOURCE).read_bytes())
    checker_original = out/'checker_reference.sv'
    checker_original.write_text(read_rtl_source(args.reference+':'+str(CHECKER), cwd=ROOT, text=True))
    checker_current = out/'checker_current.sv'; checker_current.write_bytes((ROOT/CHECKER).read_bytes())
    measurement = out/'measure.sv'
    measurement.write_text(wrapper(current.read_text(), (ROOT/'rtl/npu/conv/conv_axi_read_guard.sv').read_text()))
    conv = ROOT/'rtl/npu/conv'
    dependencies = [conv/'conv_im2col_pkg.sv', conv/'vector_engine_pkg.sv']
    dependencies += [path for path in sorted(conv.glob('*.sv')) if path not in dependencies and
                     path not in (ROOT/SOURCE, ROOT/CHECKER)]
    dependencies += list(sorted((ROOT/'rtl/common').glob('*.v')))+list(sorted((ROOT/'rtl/common').glob('*.sv')))
    cases = {name: {'top': 'vector_ranges_measure',
                   'options': ['-D', 'SYNTHESIS=1', '-GTILE=16', '-GBUS_WIDTH=64', '-GPE_COUNT=8'],
                   'sources': list(map(str, dependencies+[source, checker, measurement])),
                   'configuration': '完整向量引擎和实际读取保护器，原生算术映射'}
             for name, source, checker in (('reference', original, checker_original),
                                            ('current', current, checker_current))}
    configuration = out / 'cases.json'
    configuration.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + '\n')
    with (out / 'prepare.log').open('w') as log:
        subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                        '--case-config', str(configuration), '--cases', 'reference', 'current',
                        '--out', str(out / 'native'), '--through', 'pre_lut'],
                       cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    cost = out / 'unit_lut_cost.lut'
    cost.write_text(''.join(f'{width} 1 1\n' for width in range(1, 7)))
    report = {'source_sha256': digest(current), 'reference': args.reference,
              'parameters': {'tile':16,'bus_width':64,'pe_count':8}, 'dsp_remapping': False,
              'physical_lut_packing': False, 'checker_sha256': digest(checker_current),
              'dependencies_sha256': {str(p.relative_to(ROOT)):digest(p) for p in dependencies},
              'wrapper_sha256':digest(measurement), 'mapping': {}}
    for name in ('reference', 'current'):
        folder = out / 'native' / name
        pre = folder / 'pre_lut.il'
        target = folder / 'mapped.json'
        script = folder / 'native_map.ys'
        script.write_text(f'''read_rtlil {shlex.quote(str(pre))}
read_verilog -lib -specify -overwrite +/xilinx/cells_sim.v
read_verilog -lib -overwrite +/xilinx/cells_xtra.v
opt_expr -mux_undef -noclkinv
read_verilog -icells -lib -specify +/xilinx/abc9_model.v
scratchpad -set abc9.xaiger 1
scratchpad -set abc9.verify 1
abc9 -W 500 -lut {shlex.quote(str(cost))} -D 6667
clean
techmap -map +/xilinx/lut_map.v -map +/xilinx/cells_map.v -D LUT_WIDTH=6
xilinx_dffopt
opt_lut_ins -tech xilinx
synth_xilinx -top vector_ranges_measure -family xc7 -noiopad -noclkbuf -run finalize:
check -assert
write_json {shlex.quote(str(target))}
stat
''')
        stage = run_stage(script, folder / 'native_map.log', dict(os.environ))
        module = json.loads(target.read_text())['modules']['vector_ranges_measure']
        for cell, origin in register_origins(pre).items():
            if cell in module['cells']:
                module['cells'][cell].setdefault('attributes', {})['fpga_register_origin'] = origin
        report['mapping'][name] = {'resources': resources(module['cells']),
                                   'paths': connected_paths(module, limit=6, group_limit=128),
                                   'range_paths': connected_paths(module, limit=4, group_limit=8,
                                       sink_filter=lambda name, cell, port: any(state in
                                           cell.get('attributes', {}).get('fpga_register_origin', '')
                                           for state in RANGE_STATE)),
                                   'mapped_json_sha256': digest(target), 'stage': stage}
        for path in (target, pre, folder / 'elaborated.il'):
            with path.open('rb') as source, gzip.open(str(path) + '.gz', 'wb') as dest:
                shutil.copyfileobj(source, dest)
            path.unlink()
    if digest(current) != digest(ROOT / SOURCE) or digest(checker_current) != digest(ROOT / CHECKER):
        raise RuntimeError('测量期间 RTL 内容发生变化')
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({name: {'lut': row['resources']['logic_lut_cells'],
                            'ff': row['resources']['flip_flops'],
                            'maximum_depth': row['paths']['longest_register_path_cells']}
                      for name, row in report['mapping'].items()}, indent=2), flush=True)


if __name__ == '__main__':
    main()
