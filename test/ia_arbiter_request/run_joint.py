#!/usr/bin/env python3
"""保留实际 NPU 的 IA 与仲裁连接，测量坐标请求和槽号至仲裁状态的路径。"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
import open_fpga_synth as flow
import remap_fpga_luts as remap
from netlist_metrics import connected_paths, register_origins, resources

CHANGED = ('rtl/npu/loaders/ia_loader.sv', 'rtl/npu/dma/axi_block_dma_arbiter.sv')
BOUNDARIES = ('axi_dual_block_dma', 'ia_loader_cache_mgr', 'kernel_loader', 'bias_loader',
              'vector_engine', 'compute_core', 'vec_requant', 'vec_s8_to_fifo', 'vec_s16_to_fifo',
              'oa_writer', 'ia_ps_shared_ram', 'ia_ps_channel_ram')
QUERIES = {
    'request_p0_to_grant': (r'u_ia_loader\.u_ctrl\.(request_p0|load_cursor_p0) \[', r'u_block_dma_arbiter\.rd_grant_client \['),
    'request_q0_to_grant': (r'u_ia_loader\.u_ctrl\.request_q0 \[', r'u_block_dma_arbiter\.rd_grant_client \['),
    'slot_to_client_counts': (r'u_ia_loader\.u_ctrl\.tl_slot_id_r \[', r'u_block_dma_arbiter\.(rd_client_inflight\[|g_client_inflight\[\d+\]\.count_q)'),
    'slot_to_dw_count': (r'u_ia_loader\.u_ctrl\.tl_slot_id_r \[', r'u_block_dma_arbiter\.(rd_client_inflight\[4\]|g_client_inflight\[4\]\.count_q)'),
    'ia_to_arbiter': (r'u_ia_loader\.', r'u_block_dma_arbiter\.'),
    'all_to_grant': (r'.', r'u_block_dma_arbiter\.rd_grant_client \['),
    'all_to_client_counts': (r'.', r'u_block_dma_arbiter\.(rd_client_inflight\[|g_client_inflight\[\d+\]\.count_q)'),
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(folder, name, script):
    path = folder / (name + '.ys')
    path.write_text(script)
    with (folder / (name + '.log')).open('w') as stream:
        subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                        '--worker', str(path)], cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, check=True)


def measure(mapped, pre_lut):
    module = json.loads(mapped.read_text())['modules']['npu_top']
    usage = resources(module['cells'])
    for name, origin in register_origins(pre_lut).items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
    removed = []
    analysis_boundaries = []
    next_bit = max(bit for net in module['netnames'].values() for bit in net['bits'] if isinstance(bit, int)) + 1
    for name, cell in list(module['cells'].items()):
        if cell['type'].startswith('ia_loader_ctrl'):
            # 在端口之后测量组合路径；Q 坐标的控制器内部选择不属于本次范围。
            # P 坐标和槽号为寄存器的直接连接，三个端口的所有位均保留为分析起点。
            for port in ('request_p0', 'request_q0', 'tl_slot_id'):
                if cell['port_directions'][port] != 'output':
                    raise RuntimeError('Expected a controller register output: ' + port)
                bits = cell['connections'][port]
                analysis_boundaries.append({'cell': name, 'port': port, 'width': len(bits),
                    'retained_bits': sum(isinstance(bit, int) for bit in bits),
                    'origin_kind': 'combinational_port' if port == 'request_q0' else 'register_alias',
                    'analysis_only': True})
                for index, bit in enumerate(bits):
                    if not isinstance(bit, int):
                        continue
                    signal = 'tl_slot_id_r' if port == 'tl_slot_id' else port
                    boundary = 'analysis_ctrl_' + port + '_' + str(index)
                    module['cells'][boundary] = {'type': 'FDRE', 'parameters': {},
                        'attributes': {'fpga_register_origin': f'u_ia_loader.u_ctrl.{signal} [{index}]'},
                        'port_directions': {'D': 'input', 'Q': 'output'},
                        'connections': {'D': [next_bit], 'Q': [bit]}}
                    next_bit += 1
        if cell['type'] == '$scopeinfo' or cell['type'].startswith(BOUNDARIES):
            removed.append({'cell': name, 'type': cell['type']})
            del module['cells'][name]
    paths = {}
    for name, (start, end) in QUERIES.items():
        first, last = re.compile(start), re.compile(end)
        paths[name] = connected_paths(module, limit=5, group_limit=4,
            root_filter=lambda n, c, p: bool(first.search(c.get('attributes', {}).get('fpga_register_origin', ''))),
            sink_filter=lambda n, c, p: bool(last.search(c.get('attributes', {}).get('fpga_register_origin', ''))))
        if not paths[name]['graph_complete']:
            raise RuntimeError('IA request graph is incomplete: ' + name)
    return {'resources': usage, 'paths': paths, 'interface_boundaries': removed,
            'analysis_boundaries': analysis_boundaries,
            'mapped_sha256': digest(mapped), 'pre_lut_sha256': digest(pre_lut)}


def main():
    global BOUNDARIES
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='437a8d81')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--cases', nargs='+', choices=('reference', 'current'), default=('reference', 'current'))
    parser.add_argument('--lock-file', type=Path, required=True)
    parser.add_argument('--control-boundary', action='store_true')
    args = parser.parse_args()
    if args.control_boundary:
        BOUNDARIES = (*BOUNDARIES, 'ia_loader_ctrl')
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    import pyosys
    library = Path(pyosys.__file__).parent / 'share/xilinx'
    case = flow.CASES['npu_top']
    with args.lock_file.open('a') as lock:
        print('Waiting for synthesis lock: ' + str(args.lock_file), flush=True)
        fcntl.flock(lock, fcntl.LOCK_EX)
        for label in args.cases:
            folder = out / label
            folder.mkdir(exist_ok=True)
            source_paths, hashes = [], {}
            for name in case['sources']:
                data = ((ROOT / name).read_bytes() if label == 'current' and name in CHANGED else
                        subprocess.check_output(['git', 'show', args.reference + ':' + name], cwd=ROOT))
                path = folder / 'sources' / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                source_paths.append(path)
                hashes[name] = hashlib.sha256(data).hexdigest()
            primitive_options, primitive_info = flow.primitive_models(folder,
                [str(path) for path in source_paths], library)
            manifest = {'reference_revision': args.reference, 'changed_files': CHANGED,
                        'source_sha256': hashes, 'options': case['options'],
                        'primitive_models': primitive_info, 'boundaries': BOUNDARIES,
                        'controller_output_analysis_boundaries': args.control_boundary}
            (folder / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
            pre_lut = folder / 'pre_lut.il'
            commands = ('read_slang --keep-hierarchy --top npu_top -I ' +
                shlex.quote(str(ROOT / 'include')) + ' -I ' + shlex.quote(str(ROOT / 'rtl/npu/ps_compact')) +
                ' ' + primitive_options + ' ' + ' '.join(map(shlex.quote, case['options'])) + ' ' +
                ' '.join(shlex.quote(str(path)) for path in source_paths) + '\n' +
                'read_verilog -lib -specify -overwrite +/xilinx/cells_sim.v\n' +
                'read_verilog -lib -overwrite +/xilinx/cells_xtra.v\n' +
                'blackbox ' + ' '.join(name + '*' for name in BOUNDARIES) + '\n' +
                'hierarchy -check -top npu_top\n' +
                'synth_xilinx -top npu_top -family xc7 -noiopad -noclkbuf -flatten -run begin:map_luts\n' +
                'write_rtlil ' + shlex.quote(str(pre_lut)) + '\n')
            run(folder, '02_pre_lut', commands)
            cost_library = folder / 'physical.lut'
            raw_library = folder / 'native.lut'
            run(folder, '01_lut_library', 'read_verilog -lib -specify +/xilinx/cells_sim.v\n'
                'add -mod lut_library_top\nabc9_ops -prep_lut 0\nabc9_ops -write_lut ' +
                shlex.quote(str(raw_library)) + '\n')
            library_info = remap.physical_cost_library(raw_library, cost_library, 8)
            run(folder, '03_map_lut', remap.mapping_commands('npu_top', pre_lut, folder,
                'physical-cost', 6667, 300, cost_library))
            verification = remap.verify_mapping('physical-cost', folder, os.environ.copy())
            report = measure(folder / 'mapped.json', pre_lut)
            report.update(manifest=manifest, manifest_sha256=digest(folder / 'manifest.json'),
                          lut_library=library_info, functional_verification=verification)
            (folder / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
            print(json.dumps({'case': label, 'logic_luts': report['resources']['logic_lut_cells'],
                'paths': {name: value['longest_register_path_cells'] for name, value in report['paths'].items()}}), flush=True)
    summaries = {label: json.loads((out / label / 'summary.json').read_text())
                 for label in ('reference', 'current') if (out / label / 'summary.json').exists()}
    (out / 'summary.json').write_text(json.dumps(summaries, indent=2) + '\n')


if __name__ == '__main__':
    main()
